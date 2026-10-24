"""Search execution (brief section 19).

- No Gmail part (e.g. just `folder:Work tag:later`): answered from our own database.
- With a Gmail part: users.messages.list q=<Gmail part> runs on each selected account in
  parallel, results are merged newest first, Sift filters are applied, and paging continues
  through Gmail until the page is full. Results Sift never stored (older mail) are shown from
  Gmail's headers; Sift filters other than account: can only match mail Sift stored.
- Results are one row per conversation (the newest matching message).

The cursor is opaque to clients: per-account Gmail page token and position, plus the
conversations already shown, so pages never repeat a thread.
"""
import base64
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import and_, exists, func, not_, or_, select, true
from sqlalchemy.orm import Session

from app import accounts as account_service
from app import demo, folders
from app.mail.base import AuthRevoked
from app.mail.message import parse_metadata
from app.models import (Folder, FolderItem, GmailAccount, GroupMember, MailNote, MailTag, Message, Notification, Opportunity,
                        OpportunityEvent, Rule, SavedSearch, Tag)
from app.search.local import Unknown, gmail_match
from app.search.query import Filter, Parsed, QueryError, parse

GMAIL_CHUNK = 40  # ids per Gmail list call
MAX_ROUNDS = 5  # list calls per account per page, at most (bounded cost when filters reject a lot)
SEEN_LIMIT = 400  # conversations remembered in the cursor to avoid repeats across pages
SEARCHABLE_STATUSES = ("processed", "silenced", "ignored")


class SearchError(ValueError):
    pass


# ---- saved searches inside a query --------------------------------------------------------------

def expand_saved(db: Session, user_id: uuid.UUID, q: str) -> str:
    """saved:NAME becomes that saved search's own query, once (no nesting)."""
    p = parse(q)
    names = [f.value for f in p.filters if f.key == "saved"]
    if not names:
        return q
    out = q
    for f in [f for f in p.filters if f.key == "saved"]:
        s = db.scalar(select(SavedSearch).where(SavedSearch.user_id == user_id, func.lower(SavedSearch.name) == f.value.lower()))
        if s is None:
            raise SearchError(f"no saved search called {f.value}")
        if f.negated:
            raise SearchError("saved: can't be negated")
        inner = parse(s.query)
        if any(x.key == "saved" for x in inner.filters):
            raise SearchError("a saved search can't use another saved search")
        out = out.replace(f.text(), s.query, 1)
    return out


# ---- Sift filters as SQL ------------------------------------------------------------------------

def _accounts(db: Session, user_id: uuid.UUID) -> list[GmailAccount]:
    return list(db.scalars(select(GmailAccount).where(GmailAccount.user_id == user_id).order_by(GmailAccount.created_at)))


def _account_match(a: GmailAccount, value: str) -> bool:
    v = value.lower()
    return a.email.lower() == v or (a.label or "").lower() == v or a.email.lower().split("@")[0] == v


def _condition(db: Session, user_id: uuid.UUID, f: Filter, accounts: list[GmailAccount]):
    v = f.value
    if f.key == "folder":
        if v.lower() == "none":
            c = ~exists().where(FolderItem.account_id == Message.account_id, FolderItem.thread_id == Message.thread_id,
                                FolderItem.folder_id.in_(select(Folder.id).where(Folder.user_id == user_id)))
            return c
        tree = folders.load_tree(db, user_id)
        roots = [x for x in tree.by_id.values() if x.name.lower() == v.lower()]
        if not roots:
            raise SearchError(f"no folder called {v}")
        ids = {fid for r in roots for fid in tree.subtree(r.id)}
        c = exists().where(FolderItem.account_id == Message.account_id, FolderItem.thread_id == Message.thread_id, FolderItem.folder_id.in_(ids))
    elif f.key == "tag":
        c = exists().where(MailTag.message_id == Message.id, MailTag.tag_id == Tag.id, Tag.user_id == user_id, func.lower(Tag.name) == v.lower())
    elif f.key == "priority":
        c = Message.priority == v
    elif f.key == "type":
        c = func.lower(Message.category) == v.lower().replace(" ", "_")
    elif f.key == "company":
        like = f"%{v.lower()}%"
        c = exists().where(OpportunityEvent.message_id == Message.id, OpportunityEvent.opportunity_id == Opportunity.id,
                           Opportunity.user_id == user_id, func.lower(Opportunity.company).like(like))
    elif f.key == "account":
        ids = [a.id for a in accounts if _account_match(a, v)]
        if not ids:
            raise SearchError(f"no connected account matches {v}")
        c = Message.account_id.in_(ids)
    elif f.key == "rule":
        c = Message.matched_rule_id.in_(select(Rule.id).where(Rule.user_id == user_id, func.lower(Rule.name).like(f"%{v.lower()}%")))
    elif f.key == "is" and v == "silenced":
        c = Message.status.in_(("silenced", "ignored"))
    elif f.key == "is" and v == "grouped":
        c = exists().where(GroupMember.message_id == Message.id, GroupMember.added_by != "removed")
    elif f.key == "is" and v == "notified":
        c = exists().where(Notification.message_id == Message.id, Notification.sent_at.is_not(None))
    elif f.key == "is" and v == "acked":
        c = exists().where(Notification.message_id == Message.id, Notification.acknowledged_at.is_not(None))
    elif f.key == "has" and v == "note":
        c = exists().where(MailNote.message_id == Message.id)
    elif f.key == "has" and v == "link":
        c = func.coalesce(func.jsonb_array_length(Message.extraction["links"]), 0) > 0
    else:
        raise SearchError(f"unsupported filter {f.text()}")
    return not_(c) if f.negated else c


def conditions(db: Session, user_id: uuid.UUID, p: Parsed, accounts: list[GmailAccount]) -> list:
    conds = [_condition(db, user_id, f, accounts) for f in p.filters if f.key != "saved"]
    for group in p.any_of:
        conds.append(or_(*[_condition(db, user_id, f, accounts) for f in group]))
    return conds


def selected_accounts(p: Parsed, accounts: list[GmailAccount]) -> list[GmailAccount]:
    chosen = accounts
    for f in p.filters:
        if f.key == "account":
            matches = [a for a in accounts if _account_match(a, f.value)]
            chosen = [a for a in chosen if (a not in matches) == f.negated]
    return chosen


# ---- results -----------------------------------------------------------------------------------

@dataclass
class Hit:
    account: GmailAccount
    gmail_id: str
    thread_id: str
    date: datetime | None
    row: Message | None = None
    meta: dict = field(default_factory=dict)
    idx: int = 0  # position in its Gmail result page, so paging resumes exactly after it

    @property
    def key(self) -> str:
        return f"{self.account.id}:{self.thread_id}"


def hit_json(h: Hit, message_json) -> dict:
    if h.row is not None:
        return {**message_json(h.row, h.account), "source": "sift", "gmail_id": h.gmail_id}
    m = h.meta
    return {
        "id": None, "source": "gmail", "gmail_id": h.gmail_id, "thread_id": h.thread_id, "account_id": str(h.account.id),
        "account": h.account.label or h.account.email, "account_color": h.account.color,
        "sender": m.get("sender"), "sender_name": m.get("sender_name"), "subject": m.get("subject"), "snippet": m.get("snippet"),
        "received_at": h.date.isoformat() if h.date else None, "unread": m.get("unread", False), "has_attachment": m.get("has_attachment", False),
        "priority": None, "category": None, "status": "not_in_sift", "links": [], "summary": None, "company": None,
    }


def _encode(state: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(state, separators=(",", ":")).encode()).decode()


def _decode(cursor: str | None) -> dict:
    if not cursor:
        return {}
    try:
        return json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except (ValueError, json.JSONDecodeError) as exc:
        raise SearchError("bad page cursor") from exc


# ---- local-only search -------------------------------------------------------------------------

def local_search(db: Session, user_id: uuid.UUID, p: Parsed, accounts: list[GmailAccount], cursor: str | None, limit: int):
    """Newest message per conversation among stored mail matching the Sift filters."""
    state = _decode(cursor)
    chosen = selected_accounts(p, accounts)
    base = select(Message.id, func.row_number().over(
        partition_by=(Message.account_id, Message.thread_id), order_by=Message.received_at.desc().nulls_last()).label("rn")).where(
        Message.user_id == user_id, Message.status.in_(SEARCHABLE_STATUSES), Message.account_id.in_([a.id for a in chosen] or [uuid.uuid4()]),
        *conditions(db, user_id, p, accounts))
    latest = base.subquery()
    stmt = select(Message).join(latest, and_(Message.id == latest.c.id, latest.c.rn == 1))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if state.get("before"):
        stmt = stmt.where(Message.received_at < datetime.fromisoformat(state["before"]))
    rows = list(db.scalars(stmt.order_by(Message.received_at.desc().nulls_last()).limit(limit)))
    by_id = {a.id: a for a in accounts}
    hits = [Hit(by_id[r.account_id], r.gmail_id, r.thread_id, r.received_at, r) for r in rows]
    nxt = _encode({"before": rows[-1].received_at.isoformat()}) if len(rows) == limit and rows[-1].received_at else None
    return hits, nxt, total, False


# ---- Gmail search ------------------------------------------------------------------------------

def _fetch_page(account: GmailAccount, q: str, token: str | None):
    if demo.is_demo(account):
        return [], None, 0  # the demo account has no Gmail; its mail is searched locally (see gmail_search)
    return account_service.provider_for(account).search(q, token, GMAIL_CHUNK)


def _demo_hits(db: Session, account: GmailAccount, p: Parsed) -> list[Hit]:
    q = select(Message).where(Message.account_id == account.id, Message.status.in_(SEARCHABLE_STATUSES))
    for w in p.words:
        like = f"%{w.replace('%', '').replace('_', '')}%"
        q = q.where(or_(Message.subject.ilike(like), Message.snippet.ilike(like), Message.sender.ilike(like), Message.sender_name.ilike(like)))
    return [Hit(account, r.gmail_id, r.thread_id, r.received_at, r) for r in db.scalars(q.order_by(Message.received_at.desc()).limit(200))]


def gmail_search(db: Session, user_id: uuid.UUID, p: Parsed, accounts: list[GmailAccount], cursor: str | None, limit: int):
    state = _decode(cursor)
    chosen = [a for a in selected_accounts(p, accounts) if a.status == "active" and (a.encrypted_refresh_token or demo.is_demo(a))]
    by_id = {str(a.id): a for a in chosen if not demo.is_demo(a)}
    pos: dict = {k: v for k, v in (state.get("acc") or {k: {"pt": None, "i": 0} for k in by_id}).items() if k in by_id}
    seen: list[str] = state.get("seen", [])
    seen_set = set(seen)
    conds = conditions(db, user_id, p, accounts)
    sift_filters = bool([f for f in p.filters if f.key != "account"] or p.any_of)
    estimate, failed = 0, []
    queue: dict[str, list[Hit]] = {}  # per account: resolved hits not yet consumed, newest first
    next_token: dict[str, str | None] = {}

    def load(a_id: str):
        try:
            return a_id, _fetch_page(by_id[a_id], p.gmail, pos[a_id]["pt"])
        except Exception as exc:  # one failing account must not fail the search
            return a_id, exc

    out: list[Hit] = []
    for _round in range(MAX_ROUNDS):
        need = [k for k, v in pos.items() if not v.get("done") and not queue.get(k)]
        if need:
            fresh: dict[str, list[dict]] = {}
            with ThreadPoolExecutor(max_workers=min(8, len(need))) as ex:
                for a_id, res in ex.map(load, need):
                    if isinstance(res, Exception):
                        if isinstance(res, AuthRevoked):
                            account_service.mark_auth_failure(by_id[a_id], res)
                        failed.append(by_id[a_id].email)
                        pos[a_id]["done"] = True
                        continue
                    ids, nxt, est = res
                    estimate += est
                    fresh[a_id] = [{**x, "_idx": pos[a_id]["i"] + j} for j, x in enumerate(ids[pos[a_id]["i"]:])]
                    next_token[a_id] = nxt
                    if not fresh[a_id] and not nxt:
                        pos[a_id]["done"] = True
            # with Sift filters, mail Sift never stored can't match: don't fetch its headers at all
            for a_id, hits in _resolve(db, by_id, fresh, need_meta=not sift_filters).items():
                queue[a_id] = hits
        # merge newest first: Gmail lists each account newest first, so take from the newest head
        while len(out) < limit:
            heads = [k for k in queue if queue[k]]
            if not heads:
                break
            k = max(heads, key=lambda k: queue[k][0].date or datetime.min.replace(tzinfo=UTC))
            h = queue[k].pop(0)
            pos[k]["i"] = h.idx + 1
            if h.key in seen_set or (sift_filters and not _passes(db, h, conds)):
                continue
            seen_set.add(h.key)
            seen.append(h.key)
            out.append(h)
        for k in list(queue):
            if not queue[k]:  # this Gmail page is used up: next page, or the account is finished
                del queue[k]
                if next_token.get(k):
                    pos[k] = {"pt": next_token[k], "i": 0}
                else:
                    pos[k]["done"] = True
        if len(out) >= limit or all(v.get("done") for v in pos.values()):
            break

    if not cursor:  # the demo account has no Gmail: its stored mail is matched by the plain words, on page 1
        for a in chosen:
            if demo.is_demo(a):
                for h in _demo_hits(db, a, p):
                    if len(out) >= limit:
                        break
                    if h.key not in seen_set and (not sift_filters or _passes(db, h, conds)):
                        seen_set.add(h.key)
                        out.append(h)
                        estimate += 1
    out.sort(key=lambda h: h.date or datetime.min.replace(tzinfo=UTC), reverse=True)
    more = any(not v.get("done") for v in pos.values())
    nxt = _encode({"acc": pos, "seen": seen[-SEEN_LIMIT:]}) if more else None
    return out, nxt, estimate, failed


def _resolve(db: Session, by_id: dict, buffers: dict[str, list[dict]], need_meta: bool = True) -> dict[str, list[Hit]]:
    out: dict[str, list[Hit]] = {}
    unknown: list[tuple[str, str]] = []
    for a_id, items in buffers.items():
        ids = [x["id"] for x in items]
        rows = {r.gmail_id: r for r in db.scalars(select(Message).where(Message.account_id == uuid.UUID(a_id), Message.gmail_id.in_(ids)))}
        out[a_id] = []
        for x in items:
            r = rows.get(x["id"])
            if r is not None and r.status in SEARCHABLE_STATUSES:
                out[a_id].append(Hit(by_id[a_id], r.gmail_id, r.thread_id, r.received_at, r, idx=x.get("_idx", 0)))
            elif need_meta:
                out[a_id].append(Hit(by_id[a_id], x["id"], x.get("threadId", ""), None, idx=x.get("_idx", 0)))
                unknown.append((a_id, x["id"]))
    if unknown:
        def meta(item):
            a_id, gid = item
            try:
                return item, parse_metadata(account_service.provider_for(by_id[a_id]).get_metadata(gid))
            except Exception:
                return item, None

        with ThreadPoolExecutor(max_workers=16) as ex:
            got = dict(ex.map(meta, unknown))
        for a_id, hits in out.items():
            for h in hits:
                m = got.get((a_id, h.gmail_id))
                if h.row is None and m is not None:
                    h.date, h.thread_id = m.received_at, m.thread_id
                    h.meta = {"sender": m.sender, "sender_name": m.sender_name, "subject": m.subject, "snippet": m.snippet,
                              "unread": "UNREAD" in m.labels, "has_attachment": m.has_attachment}
            out[a_id] = [h for h in hits if h.row is not None or h.meta]
    return out


def _passes(db: Session, h: Hit, conds: list) -> bool:
    if h.row is None:
        return False  # Sift knows nothing about mail it never stored
    return db.scalar(select(true()).where(Message.id == h.row.id, *conds)) is not None


def run(db: Session, user_id: uuid.UUID, q: str, cursor: str | None = None, limit: int = 30):
    """Returns (hits, next cursor, total or Gmail's estimate, accounts that failed)."""
    try:
        q = expand_saved(db, user_id, q)
        p = parse(q)
    except QueryError as exc:
        raise SearchError(str(exc)) from exc
    accounts = _accounts(db, user_id)
    if not p.has_gmail:
        if not p.filters and not p.any_of:
            raise SearchError("type something to search for")
        hits, nxt, total, _ = local_search(db, user_id, p, accounts, cursor, limit)
        return hits, nxt, total, [], p
    if [f for f in p.filters if f.key != "account"] or p.any_of:
        try:
            hits, nxt, total = filtered_search(db, user_id, p, accounts, cursor, limit)
            return hits, nxt, total, [], p
        except Unknown:
            pass  # Gmail syntax only Gmail can decide: search through Gmail instead
    hits, nxt, total, failed = gmail_search(db, user_id, p, accounts, cursor, limit)
    return hits, nxt, total, failed, p


LOCAL_SCAN_LIMIT = 5000


def filtered_search(db: Session, user_id: uuid.UUID, p: Parsed, accounts: list[GmailAccount], cursor: str | None, limit: int):
    """Sift filters plus a Gmail part this server can decide itself: every match is mail Sift
    stored, so it's answered from the database, exactly (no Gmail calls, exact count).
    Raises Unknown when the Gmail part needs Gmail."""
    state = _decode(cursor)
    offset = int(state.get("off", 0)) if state else 0
    chosen = selected_accounts(p, accounts)
    base = select(Message.id, func.row_number().over(
        partition_by=(Message.account_id, Message.thread_id), order_by=Message.received_at.desc().nulls_last()).label("rn")).where(
        Message.user_id == user_id, Message.status.in_(SEARCHABLE_STATUSES), Message.account_id.in_([a.id for a in chosen] or [uuid.uuid4()]),
        *conditions(db, user_id, p, accounts))
    latest = base.subquery()
    rows = list(db.scalars(select(Message).join(latest, and_(Message.id == latest.c.id, latest.c.rn == 1))
                           .order_by(Message.received_at.desc().nulls_last()).limit(LOCAL_SCAN_LIMIT)))
    now = datetime.now(UTC)
    matched = [r for r in rows if gmail_match(p.gmail, r, now)]  # Unknown propagates on the first undecidable part
    by_id = {a.id: a for a in accounts}
    page = matched[offset:offset + limit]
    hits = [Hit(by_id[r.account_id], r.gmail_id, r.thread_id, r.received_at, r) for r in page]
    nxt = _encode({"off": offset + limit}) if offset + limit < len(matched) else None
    return hits, nxt, len(matched)



def answered_locally(p: Parsed) -> bool:
    """Whether run() answered this from the database (exact totals) rather than Gmail."""
    if not ([f for f in p.filters if f.key != "account"] or p.any_of):
        return False
    try:
        gmail_match(p.gmail, Message(subject="", snippet="", sender="", sender_name="", labels=[], received_at=datetime.now(UTC)))
        return True
    except Unknown:
        return False

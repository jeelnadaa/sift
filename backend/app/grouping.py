"""Opt-in grouping of similar mail (brief section 21). Display only: it never touches Gmail
and never changes notifications, except for a group the user explicitly muted (and even
then urgent mail still notifies).

A mail joins a group by the first rule that finds a partner — an open group with the same
key, or another ungrouped mail with the same key in the window:
  0. sender the user marked "always group"   (kind "sender")
  1. same Gmail thread as a grouped mail      (joins that mail's group)
  2. same opportunity (company)               (kind "opportunity")
  3. same List-Id                             (kind "list")
  4. same sender address + subject template   (kind "template")
  5. same sender domain + similar subject     (kind "similar", trigram similarity >= 0.6)
Membership is stable: a mail is assigned once, and existing groups are never reshuffled.
A group shows as a group from MIN_GROUP_SIZE members; it closes after GROUP_WINDOW without
new mail, and the next mail starts a new group.
The optional AI suggestion layer is not built (see PROGRESS.md).
"""
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import user_settings
from app.fingerprint import fingerprint, normalize_subject
from app.models import GroupMember, GroupPreference, MailGroup, Message, Opportunity, Setting

log = logging.getLogger(__name__)
MIN_GROUP_SIZE = 3
GROUP_WINDOW = timedelta(days=30)
SIMILARITY = 0.6
MAX_PROMPTS = 3
CHOICES = ("not_asked", "yes", "no")
GROUPABLE_STATUSES = ("processed",)  # silenced mail stays in the Silenced view, never grouped


class GroupError(ValueError):
    pass


# ---- consent -------------------------------------------------------------------------------------

def _settings_row(db: Session, user_id: uuid.UUID) -> Setting:
    row = db.scalar(select(Setting).where(Setting.user_id == user_id, Setting.account_id.is_(None)))
    if row is None:
        row = Setting(user_id=user_id, account_id=None, data={})
        db.add(row)
    return row


def enabled(db: Session, user_id: uuid.UUID) -> bool:
    return user_settings.get(db, user_id)["grouping_enabled"] == "yes"


def status(db: Session, user_id: uuid.UUID) -> dict:
    s = user_settings.get(db, user_id)
    prompts = int(s.get("grouping_prompts", 0))
    return {"grouping_enabled": s["grouping_enabled"], "prompts": prompts,
            "should_ask": s["grouping_enabled"] == "not_asked" and prompts < MAX_PROMPTS}


def answer(db: Session, user_id: uuid.UUID, choice: str) -> bool:
    """`yes`, `no`, or `dismissed` (closed without answering: ask again next open, up to
    MAX_PROMPTS times). Also used by Settings to change the choice. Returns True when grouping
    was just turned on (the caller starts the 30-day backfill)."""
    row = _settings_row(db, user_id)
    data = dict(row.data or {})
    was = data.get("grouping_enabled", "not_asked")
    if choice == "dismissed":
        data["grouping_prompts"] = int(data.get("grouping_prompts", 0)) + 1
    elif choice in ("yes", "no"):
        data["grouping_enabled"] = choice
    else:
        raise GroupError("answer must be yes, no or dismissed")
    row.data = data
    db.flush()
    return choice == "yes" and was != "yes"


# ---- similarity ----------------------------------------------------------------------------------

def trigrams(text: str) -> set[str]:
    """pg_trgm-style trigrams: each word padded with two spaces in front and one behind."""
    grams: set[str] = set()
    for word in "".join(c if c.isalnum() else " " for c in text.lower()).split():
        w = f"  {word} "
        grams.update(w[i:i + 3] for i in range(len(w) - 2))
    return grams


def similarity(a: str, b: str) -> float:
    ta, tb = trigrams(a), trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# ---- assignment ----------------------------------------------------------------------------------

def _sender_domain(m: Message) -> str | None:
    return m.authenticated_domain or (m.sender.rsplit("@", 1)[-1].lower() if m.sender and "@" in m.sender else None)


def _preference(db: Session, m: Message) -> tuple[str | None, str | None]:
    """(mode, the address or domain it was set for). The exact address beats its domain."""
    keys = [k for k in ((m.sender or "").lower(), _sender_domain(m)) if k]
    prefs = {p.sender_or_domain: p.mode for p in db.scalars(
        select(GroupPreference).where(GroupPreference.user_id == m.user_id, GroupPreference.sender_or_domain.in_(keys)))}
    for k in keys:
        if k in prefs:
            return prefs[k], k
    return None, None


def _open_group(db: Session, m: Message, kind: str, key: str) -> MailGroup | None:
    since = (m.received_at or datetime.now(UTC)) - GROUP_WINDOW
    return db.scalar(select(MailGroup).where(MailGroup.user_id == m.user_id, MailGroup.kind == kind, MailGroup.key == key,
                                             MailGroup.last_activity_at >= since)
                     .order_by(MailGroup.last_activity_at.desc()).limit(1))


def _ungrouped(db: Session, m: Message):
    """Other groupable mail in the window that has never been in a group (incl. removed)."""
    when = m.received_at or datetime.now(UTC)
    return (select(Message).where(
        Message.user_id == m.user_id, Message.id != m.id, Message.status.in_(GROUPABLE_STATUSES),
        Message.received_at >= when - GROUP_WINDOW, Message.received_at <= when,
        ~select(GroupMember.message_id).join(MailGroup, MailGroup.id == GroupMember.group_id)
        .where(GroupMember.message_id == Message.id, MailGroup.kind != "custom").exists(),
    ).order_by(Message.received_at.desc()))


def _title(m: Message, kind: str, db: Session) -> str:
    if kind == "opportunity":
        opp = db.get(Opportunity, uuid.UUID((m.extraction or {})["opportunity_id"]))
        if opp is not None:
            return opp.company[:200]
    if kind == "list" and m.list_id:
        name = m.list_id.split("<")[0].strip().strip('"')
        if name:
            return name[:200]
    return (m.sender_name or _sender_domain(m) or m.sender or "Similar mail")[:200]


def _add(db: Session, group: MailGroup, m: Message) -> None:
    db.add(GroupMember(group_id=group.id, message_id=m.id, account_id=m.account_id, added_by="system"))
    when = m.received_at or datetime.now(UTC)
    if group.last_activity_at is None or when > group.last_activity_at:
        group.last_activity_at = when


def _join_or_start(db: Session, m: Message, kind: str, key: str, partner_filter) -> MailGroup | None:
    group = _open_group(db, m, kind, key)
    if group is not None:
        _add(db, group, m)
        return group
    partner = db.scalar(partner_filter(_ungrouped(db, m)).limit(1))
    if partner is None:
        return None
    group = MailGroup(user_id=m.user_id, title=_title(m, kind, db), kind=kind, key=key[:320])
    db.add(group)
    db.flush()
    _add(db, group, partner)
    _add(db, group, m)
    return group


def assign(db: Session, m: Message) -> MailGroup | None:
    """Put one mail in a group, or leave it alone. Safe to call twice (stable)."""
    if m.status not in GROUPABLE_STATUSES:
        return None
    if db.scalar(select(GroupMember.group_id).join(MailGroup, MailGroup.id == GroupMember.group_id)
                 .where(GroupMember.message_id == m.id, MailGroup.kind != "custom").limit(1)) is not None:
        return None  # already assigned (or removed by the user: stays out); custom groups are extra
    pref, pref_key = _preference(db, m)
    if pref == "never":
        return None
    domain = _sender_domain(m)
    sender = (m.sender or "").lower()

    if pref == "always":
        same = (func.lower(Message.sender) == sender) if pref_key == sender else (Message.authenticated_domain == domain)
        g = _join_or_start(db, m, "sender", pref_key, lambda q: q.where(same))
        if g:
            return g

    # 1. same thread: follow the thread's existing group
    thread_group = db.scalar(
        select(MailGroup).join(GroupMember, GroupMember.group_id == MailGroup.id).join(Message, Message.id == GroupMember.message_id)
        .where(Message.account_id == m.account_id, Message.thread_id == m.thread_id, Message.id != m.id,
               GroupMember.added_by != "removed", MailGroup.user_id == m.user_id, MailGroup.kind != "custom").limit(1))
    if thread_group is not None:
        _add(db, thread_group, m)
        return thread_group

    opp = (m.extraction or {}).get("opportunity_id")
    if opp:
        g = _join_or_start(db, m, "opportunity", str(opp), lambda q: q.where(Message.extraction["opportunity_id"].astext == str(opp)))
        if g:
            return g
    if m.list_id:
        g = _join_or_start(db, m, "list", m.list_id.lower(), lambda q: q.where(func.lower(Message.list_id) == m.list_id.lower()))
        if g:
            return g
    if not (m.authenticated_domain and m.subject):
        return None  # unverified senders only group by thread, list or opportunity
    fp = m.fingerprint or fingerprint(m.authenticated_domain, m.subject)
    g = _join_or_start(db, m, "template", f"{sender}|{fp}",
                       lambda q: q.where(func.lower(Message.sender) == sender, Message.fingerprint == fp))
    if g:
        return g
    return _similar(db, m, domain)


def _similar(db: Session, m: Message, domain: str) -> MailGroup | None:
    subject = normalize_subject(m.subject)
    since = (m.received_at or datetime.now(UTC)) - GROUP_WINDOW
    groups = db.scalars(select(MailGroup).where(MailGroup.user_id == m.user_id, MailGroup.kind == "similar",
                                                MailGroup.key == domain, MailGroup.last_activity_at >= since))
    for g in groups:
        latest = db.scalar(select(Message.subject).join(GroupMember, GroupMember.message_id == Message.id)
                           .where(GroupMember.group_id == g.id).order_by(Message.received_at.desc()).limit(1))
        if latest and similarity(subject, normalize_subject(latest)) >= SIMILARITY:
            _add(db, g, m)
            return g
    for partner in db.scalars(_ungrouped(db, m).where(Message.authenticated_domain == domain).limit(50)):
        if partner.subject and similarity(subject, normalize_subject(partner.subject)) >= SIMILARITY:
            g = MailGroup(user_id=m.user_id, title=_title(m, "similar", db), kind="similar", key=domain)
            db.add(g)
            db.flush()
            _add(db, g, partner)
            _add(db, g, m)
            return g
    return None


def assign_if_enabled(db: Session, m: Message) -> MailGroup | None:
    """Pipeline hook. Never raises: grouping must not stand in the way of a notification."""
    if not enabled(db, m.user_id):
        return None  # no answer or "no": nothing is computed
    try:
        with db.begin_nested():
            return assign(db, m)
    except Exception:
        log.exception("grouping failed for message %s", m.id)
        return None


def backfill(db: Session, user_id: uuid.UUID) -> int:
    """Turning grouping on groups the last 30 days of stored mail, oldest first."""
    if not enabled(db, user_id):
        return 0
    since = datetime.now(UTC) - GROUP_WINDOW
    ids = list(db.scalars(select(Message.id).where(Message.user_id == user_id, Message.status.in_(GROUPABLE_STATUSES),
                                                   Message.received_at >= since).order_by(Message.received_at)))
    grouped = 0
    for mid in ids:
        if assign(db, db.get(Message, mid)) is not None:
            grouped += 1
    db.flush()
    return grouped


# ---- reading -------------------------------------------------------------------------------------

def _visible_members():
    return select(GroupMember.group_id, GroupMember.message_id).join(Message, Message.id == GroupMember.message_id).where(
        GroupMember.added_by != "removed", Message.status.in_(GROUPABLE_STATUSES))


def shown_group_ids(db: Session, user_id: uuid.UUID):
    """Subquery of groups big enough to show as a group."""
    vm = _visible_members().subquery()
    return (select(MailGroup.id).join(vm, vm.c.group_id == MailGroup.id).where(MailGroup.user_id == user_id)
            .group_by(MailGroup.id).having((func.count() >= MIN_GROUP_SIZE) | (MailGroup.kind == "custom")))  # custom: from one mail


def members(db: Session, group: MailGroup) -> list[Message]:
    return list(db.scalars(select(Message).join(GroupMember, GroupMember.message_id == Message.id)
                           .where(GroupMember.group_id == group.id, GroupMember.added_by != "removed",
                                  Message.status.in_(GROUPABLE_STATUSES))
                           .order_by(Message.received_at.desc().nulls_last())))


def group_json(g: MailGroup, rows: list[Message]) -> dict:
    latest = rows[0] if rows else None
    return {
        "type": "group", "id": str(g.id), "title": g.title, "kind": g.kind, "muted": g.muted, "collapsed": g.collapsed,
        "count": len(rows), "unread": sum("UNREAD" in (m.labels or []) for m in rows),
        "urgent": sum(m.priority == "urgent" for m in rows), "shown": len(rows) >= MIN_GROUP_SIZE or g.kind == "custom",
        "custom": g.kind == "custom", "query": g.query, "instruction": g.instruction,
        "latest_sender": (latest.sender_name or latest.sender) if latest else None,
        "latest_subject": latest.subject if latest else None,
        "received_at": latest.received_at.isoformat() if latest and latest.received_at else None,
        "account_ids": sorted({str(m.account_id) for m in rows}),
    }


def own(db: Session, user_id: uuid.UUID, group_id: uuid.UUID) -> MailGroup:
    g = db.get(MailGroup, group_id)
    if g is None or g.user_id != user_id:
        raise GroupError("group not found")
    return g


def is_muted(db: Session, m: Message) -> bool:
    return db.scalar(select(MailGroup.id).join(GroupMember, GroupMember.group_id == MailGroup.id)
                     .where(GroupMember.message_id == m.id, GroupMember.added_by != "removed", MailGroup.muted.is_(True))
                     .limit(1)) is not None


# ---- user control ------------------------------------------------------------------------------

def remove_member(db: Session, group: MailGroup, message_id: uuid.UUID) -> None:
    """Take one mail out; it stays out (never re-added automatically)."""
    gm = db.get(GroupMember, {"group_id": group.id, "message_id": message_id})
    if gm is None or gm.added_by == "removed":
        raise GroupError("that mail isn't in this group")
    gm.added_by = "removed"


def split(db: Session, group: MailGroup, message_ids: list[uuid.UUID], title: str | None = None) -> MailGroup:
    """Move the chosen mails into a new group of their own."""
    rows = [db.get(GroupMember, {"group_id": group.id, "message_id": mid}) for mid in set(message_ids)]
    if not rows or any(r is None or r.added_by == "removed" for r in rows):
        raise GroupError("pick mails from this group")
    if len(rows) >= len(members(db, group)):
        raise GroupError("leave at least one mail in the original group")
    new = MailGroup(user_id=group.user_id, title=(title or f"{group.title} (split)")[:200], kind=group.kind,
                    key=f"{group.key}#split-{uuid.uuid4().hex[:8]}"[:320], muted=group.muted)
    db.add(new)
    db.flush()
    for r in rows:
        m = db.get(Message, r.message_id)
        db.delete(r)
        db.flush()
        db.add(GroupMember(group_id=new.id, message_id=m.id, account_id=m.account_id, added_by="user"))
        if new.last_activity_at is None or (m.received_at and m.received_at > new.last_activity_at):
            new.last_activity_at = m.received_at
    db.flush()
    return new


def merge(db: Session, source: MailGroup, target: MailGroup) -> int:
    if source.id == target.id:
        raise GroupError("pick a different group to merge into")
    moved = 0
    for gm in list(db.scalars(select(GroupMember).where(GroupMember.group_id == source.id))):
        exists = db.get(GroupMember, {"group_id": target.id, "message_id": gm.message_id})
        if exists is None:
            db.add(GroupMember(group_id=target.id, message_id=gm.message_id, account_id=gm.account_id,
                               added_by="removed" if gm.added_by == "removed" else "user"))
            moved += gm.added_by != "removed"
    if source.last_activity_at and (target.last_activity_at is None or source.last_activity_at > target.last_activity_at):
        target.last_activity_at = source.last_activity_at
    db.delete(source)
    db.flush()
    return moved


def set_preference(db: Session, user_id: uuid.UUID, sender_or_domain: str, mode: str | None) -> None:
    key = sender_or_domain.strip().lower().lstrip("@")
    if not key or len(key) > 320:
        raise GroupError("give a sender address or a domain")
    pref = db.scalar(select(GroupPreference).where(GroupPreference.user_id == user_id, GroupPreference.sender_or_domain == key))
    if mode is None:
        if pref is not None:
            db.delete(pref)
        return
    if mode not in ("always", "never"):
        raise GroupError("mode must be always or never")
    if pref is None:
        db.add(GroupPreference(user_id=user_id, sender_or_domain=key, mode=mode))
    else:
        pref.mode = mode
    if mode == "never":
        # take the sender's mail out of open groups now (kept out from then on)
        for gm in db.scalars(select(GroupMember).join(Message, Message.id == GroupMember.message_id).join(MailGroup, MailGroup.id == GroupMember.group_id)
                             .where(MailGroup.user_id == user_id, GroupMember.added_by != "removed",
                                    (func.lower(Message.sender) == key) | (Message.authenticated_domain == key))):
            gm.added_by = "removed"


def feed_page(db: Session, user_id: uuid.UUID, base_query, before: datetime | None, limit: int):
    """Grouped feed: mail in shown groups is folded into one row per group, except urgent mail,
    which keeps its own row as well. Pages tile in time, so each group row appears on exactly
    one page (the one covering its latest mail).
    Returns (messages, groups-with-members, next_before, mail rows in all pages, group rows in all pages)."""
    shown = shown_group_ids(db, user_id).subquery()
    in_shown = select(GroupMember.message_id).where(GroupMember.group_id.in_(select(shown.c.id)), GroupMember.added_by != "removed")
    q = base_query.where(~Message.id.in_(in_shown) | (Message.priority == "urgent"))
    mail_total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    group_total = db.scalar(select(func.count()).select_from(shown)) or 0
    if before:
        q = q.where(Message.received_at < before)
    rows = list(db.scalars(q.order_by(Message.received_at.desc().nulls_last()).limit(limit)))
    full = len(rows) == limit and rows[-1].received_at is not None
    lower = rows[-1].received_at if full else None
    groups = []
    for g in db.scalars(select(MailGroup).where(MailGroup.id.in_(select(shown.c.id)))):
        ms = members(db, g)
        t = ms[0].received_at if ms else None
        if t is None or (before and t >= before) or (lower and t < lower):
            continue
        groups.append((g, ms))
    return rows, groups, (lower.isoformat() if lower else None), mail_total, group_total

"""Acting on many conversations at once (owner, 2026-10-31): one place for the selection bars on
web and phone and for Ask Sift, so all three behave the same.

What is picked:
- mail (`message_ids`), each standing for its whole conversation;
- groups (`group_ids`), expanded here to every mail in them;
- or "everything this list shows" (`match`: the feed / Silenced with its filters, a folder, a group).
At most LIMIT conversations per request.

Gmail changes (read, archive, trash, labels, ...) go through app.actions, conversation by
conversation, and only for conversations not already in that state. Small changes run at once;
bigger ones run in the worker as a BulkJob with progress (GET /bulk/jobs/{id}) at a pace well under
Gmail's per-user limit. Sift-only changes (pin, folders, groups, mute, timelines, snooze) are
database work and always run at once.

Every reversible change returns an undo: the opposite action over exactly the conversations that
changed. Nothing is ever deleted for good: trash is Gmail's trash (undo restores it).
"""
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app import actions as action_service
from app.models import BulkJob, FolderItem, GmailAccount, Message

log = logging.getLogger(__name__)

LIMIT = 1000  # conversations per request (owner, 2026-10-31)
INLINE_GMAIL = 30  # bigger Gmail changes run as a job with progress
PACE_SECONDS = 0.06  # between Gmail calls in a job: ~16 conversations/s, far under the per-user quota
CHUNK = 25  # progress is saved (and lists refresh) every CHUNK conversations

GMAIL_ACTIONS = {"read", "unread", "archive", "unarchive", "trash", "untrash", "spam", "notspam",
                 "star", "unstar", "important", "unimportant", "label", "unlabel"}
SIFT_ACTIONS = {"pin", "unpin", "file", "unfile", "group_add", "group_remove", "mute", "unmute",
                "timeline", "untimeline", "snooze"}
ACTIONS = GMAIL_ACTIONS | SIFT_ACTIONS
UNDO = {"read": "unread", "unread": "read", "archive": "unarchive", "unarchive": "archive", "trash": "untrash",
        "untrash": "trash", "spam": "notspam", "notspam": "spam", "star": "unstar", "unstar": "star",
        "important": "unimportant", "unimportant": "important", "label": "unlabel", "unlabel": "label", "pin": "unpin", "unpin": "pin",
        "file": "unfile", "unfile": "file", "group_add": "group_remove", "group_remove": "group_add",
        "mute": "unmute", "unmute": "mute", "timeline": "untimeline"}
# a conversation already in this state is skipped (no Gmail call, not part of the undo)
_STATE = {"read": ("UNREAD", False), "unread": ("UNREAD", True), "archive": ("INBOX", False), "unarchive": ("INBOX", True),
          "trash": ("TRASH", True), "untrash": ("TRASH", False), "spam": ("SPAM", True), "notspam": ("SPAM", False),
          "star": ("STARRED", True), "unstar": ("STARRED", False), "important": ("IMPORTANT", True), "unimportant": ("IMPORTANT", False)}
NEEDS_PARAM = {"label": "label", "unlabel": "label", "file": "folder_id", "unfile": "folder_id", "group_add": "group_id",
               "group_remove": "group_id", "timeline": "opportunity_id", "snooze": "until"}


class BulkError(ValueError):
    pass


@dataclass
class Outcome:
    action: str
    conversations: int = 0  # picked
    changed: list[uuid.UUID] = field(default_factory=list)  # one message per conversation that changed
    failed_accounts: list[str] = field(default_factory=list)
    sift_only: list[str] = field(default_factory=list)  # read/unread without write access: changed in Sift only
    job_id: uuid.UUID | None = None


def not_in_bin():
    """Mail in Gmail's Trash or Spam isn't shown in the feed, groups or folders (it's still searchable)."""
    return or_(Message.labels.is_(None), ~(Message.labels.contains(["TRASH"]) | Message.labels.contains(["SPAM"])))


# ---- picking -------------------------------------------------------------------------------

def resolve(db: Session, user_id: uuid.UUID, message_ids: list[uuid.UUID] | None = None,
            group_ids: list[uuid.UUID] | None = None, match: dict | None = None,
            opportunity_ids: list[uuid.UUID] | None = None,
            folder_ids: list[uuid.UUID] | None = None) -> tuple[list[Message], dict]:
    """The newest stored message of each picked conversation (newest first) and what was picked
    ({"mails", "groups", "group_mails", "urgent_in_groups", "conversations"}). Timelines
    (`opportunity_ids`) stand for the mail on them, folders (`folder_ids`) for the mail filed in
    them and their subfolders. Refuses others' mail."""
    from app import grouping
    from app.models import MailGroup

    picked: dict[uuid.UUID, Message] = {}
    info = {"mails": 0, "groups": 0, "group_mails": 0, "urgent_in_groups": 0}
    if message_ids:
        rows = list(db.scalars(select(Message).where(Message.user_id == user_id, Message.id.in_(set(message_ids)))))
        if len(rows) != len(set(message_ids)):
            raise BulkError("some of that mail isn't yours or is gone")
        picked.update({m.id: m for m in rows})
        info["mails"] = len(rows)
    for gid in dict.fromkeys(group_ids or []):
        g = db.get(MailGroup, gid)
        if g is None or g.user_id != user_id:
            raise BulkError("group not found")
        ms = grouping.members(db, g)
        info["groups"] += 1
        info["group_mails"] += len(ms)
        info["urgent_in_groups"] += sum(m.priority == "urgent" for m in ms)
        picked.update({m.id: m for m in ms})
    if opportunity_ids:
        from app.models import Opportunity, OpportunityEvent
        owned = set(db.scalars(select(Opportunity.id).where(Opportunity.user_id == user_id, Opportunity.id.in_(set(opportunity_ids)))))
        if len(owned) != len(set(opportunity_ids)):
            raise BulkError("timeline not found")
        for m in db.scalars(select(Message).join(OpportunityEvent, OpportunityEvent.message_id == Message.id)
                            .where(OpportunityEvent.opportunity_id.in_(owned), Message.user_id == user_id)):
            picked[m.id] = m
    for fid in dict.fromkeys(folder_ids or []):
        for m in _matching(db, user_id, {"folder_id": fid, "include_subfolders": True}):
            picked[m.id] = m
    if match:
        for m in _matching(db, user_id, match):
            picked[m.id] = m
    # one per conversation: its newest stored message stands for it
    latest: dict[tuple, Message] = {}
    for m in picked.values():
        k = (m.account_id, m.thread_id)
        if k not in latest or _when(m) > _when(latest[k]):
            latest[k] = m
    out = sorted(latest.values(), key=_when, reverse=True)
    if len(out) > LIMIT:
        raise BulkError(f"that's {len(out)} conversations; do at most {LIMIT} at once")
    info["conversations"] = len(out)
    return out, info


def _folder(db: Session, user_id: uuid.UUID, folder_id):
    from app import folders
    try:
        return folders.own(db, user_id, folder_id)
    except folders.FolderError as exc:
        raise BulkError("folder not found") from exc


def _when(m: Message) -> datetime:
    return m.received_at or datetime.min.replace(tzinfo=UTC)


def _matching(db: Session, user_id: uuid.UUID, match: dict) -> list[Message]:
    """Everything a list shows, with its filters (for "Select all N")."""
    from app import folders, grouping, snooze as snooze_service
    from app.models import MailGroup

    cap = LIMIT * 3  # messages; conversations are capped after merging
    if match.get("group_id"):
        g = db.get(MailGroup, uuid.UUID(str(match["group_id"])))
        if g is None or g.user_id != user_id:
            raise BulkError("group not found")
        return grouping.members(db, g)[:cap]
    if match.get("folder_id"):
        f = _folder(db, user_id, match["folder_id"])
        ids = folders.load_tree(db, user_id).subtree(f.id) if match.get("include_subfolders") else [f.id]
        filed = select(FolderItem.account_id, FolderItem.thread_id).where(FolderItem.folder_id.in_(ids)).distinct().subquery()
        q = (select(Message).join(filed, and_(Message.account_id == filed.c.account_id, Message.thread_id == filed.c.thread_id))
             .where(Message.user_id == user_id, Message.status.in_(folders.VIEW_STATUSES), not_in_bin()))
        return list(db.scalars(q.order_by(Message.received_at.desc().nulls_last()).limit(cap)))
    view = match.get("view", "feed")
    q = select(Message).where(Message.user_id == user_id)
    if view == "feed":
        q = q.where(Message.status == "processed", ~snooze_service.active_condition(), not_in_bin())
    elif view == "silenced":
        q = q.where(Message.status.in_(("silenced", "ignored")))
    else:
        raise BulkError("unknown list")
    if match.get("priority"):
        q = q.where(Message.priority == match["priority"])
    if match.get("account_id"):
        q = q.where(Message.account_id == uuid.UUID(str(match["account_id"])))
    return list(db.scalars(q.order_by(Message.received_at.desc().nulls_last()).limit(cap)))


# ---- doing ---------------------------------------------------------------------------------

def check(action: str, params: dict) -> None:
    if action not in ACTIONS:
        raise BulkError(f"unknown action {action}")
    need = NEEDS_PARAM.get(action)
    if need and not params.get(need):
        raise BulkError(f"{action} needs {need}")


def _pending(db: Session, rows: list[Message], action: str) -> list[Message]:
    """Conversations not already in the action's state (checked on every stored message of each)."""
    if action not in _STATE:
        return rows
    label, want = _STATE[action]
    keys = {(m.account_id, m.thread_id) for m in rows}
    labels: dict[tuple, list[list]] = {}
    for a, t, ls in db.execute(select(Message.account_id, Message.thread_id, Message.labels).where(
            Message.account_id.in_({a for a, _ in keys}), Message.thread_id.in_({t for _, t in keys}))):
        if (a, t) in keys:
            labels.setdefault((a, t), []).append(ls or [])
    out = []
    for m in rows:
        have = labels.get((m.account_id, m.thread_id), [])
        if not all((label in ls) == want for ls in have):
            out.append(m)
    return out


def run(db: Session, user_id: uuid.UUID, rows: list[Message], action: str, params: dict | None = None,
        background: bool = True) -> Outcome:
    """Does `action` to the conversations of `rows` (from resolve). Raises
    action_service.NeedsWriteAccess (nothing changed) when a Gmail change lacks write access."""
    params = params or {}
    check(action, params)
    out = Outcome(action, conversations=len(rows))
    if action in GMAIL_ACTIONS:
        todo = _pending(db, rows, action)
        if action in ("read", "unread"):
            return _read_state(db, user_id, todo, action, out)
        accounts = {a.id: a for a in db.scalars(select(GmailAccount).where(GmailAccount.id.in_({m.account_id for m in todo})))}
        from app import accounts as account_service
        missing = [a for a in accounts.values() if not account_service.can_modify(a)]
        if missing:
            raise action_service.NeedsWriteAccess(missing)
        if len(todo) > INLINE_GMAIL and background:
            job = BulkJob(user_id=user_id, action=action, params=_jsonable(params), message_ids=[str(m.id) for m in todo], total=len(todo))
            db.add(job)
            db.flush()
            out.job_id = job.id
            return out
        _gmail(db, user_id, todo, action, params, out)
        return out
    _sift(db, user_id, rows, action, params, out)
    return out


def _jsonable(params: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, datetime) else str(v) if isinstance(v, uuid.UUID) else v) for k, v in params.items()}


def _gmail(db: Session, user_id: uuid.UUID, todo: list[Message], action: str, params: dict, out: Outcome,
           on_progress=None, pace: float = 0.0) -> None:
    emails = dict(db.execute(select(GmailAccount.id, GmailAccount.email).where(GmailAccount.id.in_({m.account_id for m in todo}))).all())
    for i in range(0, len(todo), CHUNK):
        part = todo[i:i + CHUNK]
        res = action_service.apply(db, user_id, [(m.account_id, m.thread_id) for m in part], action, params.get("label"))
        failed = set(res.failed)  # an account that failed changed none of its part (others still did)
        out.changed += [m.id for m in part if emails.get(m.account_id) not in failed]
        out.failed_accounts = sorted(set(out.failed_accounts) | failed)
        if pace:
            time.sleep(pace * len(part))
        if on_progress:
            on_progress(min(i + CHUNK, len(todo)))


def _read_state(db: Session, user_id: uuid.UUID, todo: list[Message], action: str, out: Outcome) -> Outcome:
    """Read/unread never asks for permission: without write access only Sift's copy changes."""
    from app import accounts as account_service
    from app.mail.base import AuthRevoked
    from app.mail.gmail import GmailError

    add, remove = (["UNREAD"], []) if action == "unread" else ([], ["UNREAD"])
    accounts = {a.id: a for a in db.scalars(select(GmailAccount).where(GmailAccount.id.in_({m.account_id for m in todo})))}
    for m in todo:
        account = accounts[m.account_id]
        if account_service.can_modify(account) and account.status == "active":
            try:
                account_service.provider_for(account).modify_thread(m.thread_id, add, remove)
            except AuthRevoked as exc:
                account_service.mark_auth_failure(account, exc)
                out.sift_only.append(account.email)
            except GmailError as exc:
                if exc.status == 403:
                    account.scopes = [s for s in (account.scopes or []) if s != account_service.google_oauth.MODIFY_SCOPE]
                out.sift_only.append(account.email)
        else:
            out.sift_only.append(account.email)
        action_service._apply_local(db, m.account_id, m.thread_id, add, remove)
        out.changed.append(m.id)
    out.sift_only = sorted(set(out.sift_only))
    return out


def _sift(db: Session, user_id: uuid.UUID, rows: list[Message], action: str, params: dict, out: Outcome) -> None:
    from app import folders, grouping, places, snooze as snooze_service, vip
    from app import opportunities as opp_service
    from app.models import GroupMember, MailGroup, Opportunity, OpportunityEvent

    if action in ("pin", "unpin"):
        for m in rows:
            if m.pinned != (action == "pin"):
                m.pinned = action == "pin"
                out.changed.append(m.id)
    elif action in ("file", "unfile"):
        f = _folder(db, user_id, params["folder_id"])
        for m in rows:
            did = folders.file_thread(db, user_id, f, m.account_id, m.thread_id) if action == "file" else folders.unfile_thread(db, f, m.account_id, m.thread_id)
            if did:
                out.changed.append(m.id)
    elif action in ("group_add", "group_remove"):
        g = db.get(MailGroup, uuid.UUID(str(params["group_id"])))
        if g is None or g.user_id != user_id:
            raise BulkError("group not found")
        for m in rows:
            if action == "group_add":
                gm = db.get(GroupMember, {"group_id": g.id, "message_id": m.id})
                if gm is not None and gm.added_by == "removed":
                    gm.added_by = "user"
                    out.changed.append(m.id)
                elif places.add(db, "group", g.id, m, by="user"):
                    out.changed.append(m.id)
            else:
                try:
                    grouping.remove_member(db, g, m.id)
                    out.changed.append(m.id)
                except grouping.GroupError:
                    pass  # not in this group
    elif action in ("mute", "unmute"):
        for m in rows:
            muted = vip.is_thread_muted(db, user_id, m.thread_id)
            if action == "mute" and not muted:
                vip.mute_thread(db, user_id, m.thread_id)
                out.changed.append(m.id)
            elif action == "unmute" and muted:
                vip.unmute_thread(db, user_id, m.thread_id)
                out.changed.append(m.id)
    elif action in ("timeline", "untimeline"):
        opp = None
        if action == "timeline":
            opp = db.get(Opportunity, uuid.UUID(str(params["opportunity_id"])))
            if opp is None or opp.user_id != user_id:
                raise BulkError("timeline not found")
        for m in rows:
            ext = dict(m.extraction or {})
            if action == "untimeline":
                if not ext.get("opportunity_id"):
                    continue
                db.execute(OpportunityEvent.__table__.delete().where(OpportunityEvent.message_id == m.id))
                ext.pop("opportunity_id", None)
                ext.pop("matched_by", None)
                m.extraction = ext
            else:
                if ext.get("opportunity_id") == str(opp.id):
                    continue
                opp_service.assign(db, opp, m)  # moves it from any other timeline
            out.changed.append(m.id)
    elif action == "snooze":
        until = params["until"]
        until = datetime.fromisoformat(until) if isinstance(until, str) else until
        try:
            done = snooze_service.snooze(db, user_id, [(m.account_id, m.thread_id, m.id) for m in rows], until)
        except snooze_service.SnoozeError as exc:
            raise BulkError(str(exc)) from exc
        out.changed = [s.message_id for s in done if s.message_id]
    db.flush()


def undo_of(out: Outcome, params: dict) -> dict | None:
    """What Undo sends back to /bulk: the opposite action over exactly what changed."""
    inverse = UNDO.get(out.action)
    if not inverse or not out.changed:
        return None
    keep = {k: v for k, v in _jsonable(params).items() if k in ("label", "folder_id", "group_id", "opportunity_id")}
    return {"action": inverse, "params": keep, "message_ids": [str(i) for i in out.changed]}


# ---- background jobs -----------------------------------------------------------------------

def run_job(job_id: uuid.UUID) -> None:
    """Worker side of a big Gmail change: saves progress every CHUNK conversations and tells open
    apps to refresh as it goes."""
    from app import events
    from app.db import get_sessionmaker

    with get_sessionmaker()() as db:
        job = db.get(BulkJob, job_id)
        if job is None or job.status not in ("queued", "running"):
            return
        job.status = "running"
        db.commit()
        ids = [uuid.UUID(i) for i in job.message_ids][job.done:]  # a restarted job carries on
        rows = list(db.scalars(select(Message).where(Message.user_id == job.user_id, Message.id.in_(ids))))
        order = {mid: i for i, mid in enumerate(ids)}
        rows.sort(key=lambda m: order[m.id])
        out = Outcome(job.action, conversations=len(rows))
        start = job.done

        def progress(n: int) -> None:
            job.done = start + n
            job.changed = list(dict.fromkeys([*job.changed, *(str(i) for i in out.changed)]))
            job.failed_accounts = sorted(set(job.failed_accounts) | set(out.failed_accounts))
            events.publish(db, job.user_id, "mail", ids=[])
            db.commit()

        try:
            _gmail(db, job.user_id, rows, job.action, job.params, out, on_progress=progress, pace=PACE_SECONDS)
            job.status, job.done = "done", job.total
        except Exception:
            log.exception("bulk job %s failed", job.id)
            db.rollback()
            job = db.get(BulkJob, job_id)
            job.status = "failed"
        job.finished_at = datetime.now(UTC)
        events.publish(db, job.user_id, "mail", ids=[])
        db.commit()


def job_json(job: BulkJob) -> dict:
    changed = Outcome(job.action, changed=[uuid.UUID(i) for i in job.changed])
    return {"id": str(job.id), "action": job.action, "status": job.status, "total": job.total, "done": job.done,
            "changed": len(job.changed), "failed_accounts": job.failed_accounts,
            "undo": undo_of(changed, job.params) if job.status in ("done", "failed") else None}

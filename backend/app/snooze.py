"""Snooze (Phase 3c): hide a conversation until a time, then bring it back and notify.

- With write access to the account, the conversation is also archived in Gmail and put back in
  the inbox (marked unread) when it wakes, like Gmail's own snooze. Without it, it is hidden in
  Sift only: Gmail is not touched, and nothing asks for write access just to snooze.
- A new reply in a snoozed conversation wakes it early (as Gmail does).
- Waking is idempotent: the scheduler claims each due snooze once.
"""
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app import accounts as account_service
from app import notify
from app.mail.base import AuthRevoked
from app.models import GmailAccount, Message, Snooze

log = logging.getLogger(__name__)
MAX_AHEAD = timedelta(days=366)


class SnoozeError(ValueError):
    pass


def active_condition():
    """SQL: this message's conversation is snoozed right now (feed hides it)."""
    return exists().where(Snooze.account_id == Message.account_id, Snooze.thread_id == Message.thread_id, Snooze.done.is_(False))


def snooze(db: Session, user_id: uuid.UUID, threads: list[tuple[uuid.UUID, str, uuid.UUID | None]], until: datetime) -> list[Snooze]:
    """threads: (account id, thread id, the message the user snoozed from, if stored)."""
    now = datetime.now(UTC)
    if until.tzinfo is None:
        raise SnoozeError("give the time with a time zone")
    if until <= now + timedelta(minutes=1):
        raise SnoozeError("pick a time in the future")
    if until > now + MAX_AHEAD:
        raise SnoozeError("snooze for a year at most")
    out = []
    for a_id, t_id, m_id in threads:
        account = db.get(GmailAccount, a_id)
        if account is None or account.user_id != user_id:
            raise SnoozeError("account not found")
        s = db.scalar(select(Snooze).where(Snooze.account_id == a_id, Snooze.thread_id == t_id, Snooze.done.is_(False)))
        if s is None:
            s = Snooze(user_id=user_id, account_id=a_id, thread_id=t_id, message_id=m_id, until=until)
            db.add(s)
        else:
            s.until = until  # snoozing again moves the time
        if account_service.can_modify(account) and not s.archived_in_gmail and account.status == "active":
            try:
                account_service.provider_for(account).modify_thread(t_id, [], ["INBOX"])
                s.archived_in_gmail = True
            except AuthRevoked as exc:
                account_service.mark_auth_failure(account, exc)
            except Exception:
                log.warning("snooze: could not archive thread in account %s; hidden in Sift only", account.id)
        out.append(s)
    db.flush()
    return out


def _restore(db: Session, s: Snooze, mark_unread: bool) -> None:
    if not s.archived_in_gmail:
        return
    account = db.get(GmailAccount, s.account_id)
    if account is None or account.status != "active":
        return
    try:
        account_service.provider_for(account).modify_thread(s.thread_id, ["INBOX", *(["UNREAD"] if mark_unread else [])], [])
        for m in db.scalars(select(Message).where(Message.account_id == s.account_id, Message.thread_id == s.thread_id)):
            labels = list(m.labels or [])
            m.labels = labels + [x for x in ["INBOX", *(["UNREAD"] if mark_unread else [])] if x not in labels]
    except AuthRevoked as exc:
        account_service.mark_auth_failure(account, exc)
    except Exception:
        log.warning("snooze: could not put thread back in the inbox for account %s", account.id)


def cancel(db: Session, s: Snooze) -> None:
    _restore(db, s, mark_unread=False)
    s.done, s.woke_reason = True, "cancelled"


def wake_due(db: Session, now: datetime | None = None) -> int:
    """Scheduler (every minute): bring back due snoozes and notify. Returns how many woke."""
    now = now or datetime.now(UTC)
    due = list(db.scalars(select(Snooze).where(Snooze.done.is_(False), Snooze.until <= now)
                          .order_by(Snooze.until).limit(200).with_for_update(skip_locked=True)))
    for s in due:
        s.done, s.woke_reason = True, "time"
        _restore(db, s, mark_unread=True)
        msg = db.get(Message, s.message_id) if s.message_id else db.scalar(
            select(Message).where(Message.account_id == s.account_id, Message.thread_id == s.thread_id).order_by(Message.received_at.desc()).limit(1))
        title = (msg.sender_name or msg.sender) if msg else "Snoozed mail"
        notify.send_reminder(db, s.user_id, {
            "type": "snooze", "priority": "normal", "title": f"Back from snooze · {title}"[:120],
            "body": (msg.subject if msg else "") or "(no subject)", "message_id": str(msg.id) if msg else "",
            "sent_at_ms": int(now.timestamp() * 1000),
        })
    db.commit()
    return len(due)


def on_new_mail(db: Session, msg: Message) -> None:
    """A new message in a snoozed conversation wakes it now (it's already in the inbox)."""
    for s in db.scalars(select(Snooze).where(Snooze.account_id == msg.account_id, Snooze.thread_id == msg.thread_id, Snooze.done.is_(False))):
        s.done, s.woke_reason = True, "reply"


def snooze_json(s: Snooze, msg: Message | None) -> dict:
    return {"id": str(s.id), "account_id": str(s.account_id), "thread_id": s.thread_id, "until": s.until.isoformat(),
            "in_gmail": s.archived_in_gmail, "message_id": str(msg.id) if msg else None,
            "subject": msg.subject if msg else None, "sender_name": (msg.sender_name or msg.sender) if msg else None}

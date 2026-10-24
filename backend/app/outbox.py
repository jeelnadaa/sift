"""Sending (Phase 4): undo send, send later and follow-up reminders.

Send never goes straight to Gmail. The mail is a Gmail draft; "Send" puts it in the outbox with
send_at = now + the undo window (Settings, default 10 s), "Send later" with the chosen time. The
scheduler queues `send_outbox` as soon as something is due and the worker sends it with
drafts.send. Until then it can be cancelled (it stays a draft) or sent at once.

Exactly once: a row is claimed with FOR UPDATE SKIP LOCKED and marked "sending" (committed)
before Gmail is called. A worker that dies after Gmail sent but before recording it leaves the
row "sending"; after STUCK_AFTER it is checked: if the draft is gone from Gmail it was sent
(drafts.send consumes the draft), otherwise it goes back to "scheduled". Network errors and
Gmail 5xx/429 retry with backoff, up to MAX_ATTEMPTS; anything else fails at once and the user
is notified. Follow-ups: "remind me if there's no reply in N days" creates a FollowUp after the
mail is sent; mail from someone else in that conversation resolves it, otherwise one
notification when it is due.
"""
import logging
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import accounts as account_service
from app import notify
from app.db import get_sessionmaker
from app.mail.base import AuthRevoked
from app.mail.gmail import GmailError
from app.models import FollowUp, GmailAccount, Message, Outbox

log = logging.getLogger(__name__)
STUCK_AFTER = timedelta(minutes=5)
MAX_ATTEMPTS = 6
DAILY_LIMIT = 300  # per user; Gmail's own limit is 500 a day for a personal account
LATER_MAX = timedelta(days=366)


class OutboxError(ValueError):
    pass


def schedule(db: Session, account: GmailAccount, draft_id: str, *, thread_id: str | None, subject: str,
             recipients: str, send_at: datetime, later: bool, follow_up_days: int | None) -> Outbox:
    now = datetime.now(UTC)
    if later and not (now + timedelta(seconds=30) <= send_at <= now + LATER_MAX):
        raise OutboxError("Pick a time from a minute from now up to a year ahead")
    sent_today = db.scalar(select(func.count()).select_from(Outbox).where(
        Outbox.user_id == account.user_id, Outbox.created_at >= now - timedelta(days=1),
        Outbox.status.in_(("scheduled", "sending", "sent"))))
    if sent_today >= DAILY_LIMIT:
        raise OutboxError(f"Sending limit reached ({DAILY_LIMIT} mails a day)")
    existing = db.scalar(select(Outbox).where(Outbox.account_id == account.id, Outbox.draft_id == draft_id,
                                              Outbox.status.in_(("scheduled", "sending"))))
    if existing is not None:
        if existing.status == "sending":
            raise OutboxError("This mail is being sent")
        row = existing  # rescheduling the same draft
    else:
        row = Outbox(user_id=account.user_id, account_id=account.id, draft_id=draft_id)
        db.add(row)
    row.thread_id, row.subject, row.recipients = thread_id, subject[:500], recipients[:1000]
    row.send_at, row.later, row.follow_up_days, row.error, row.attempts = send_at, later, follow_up_days, None, 0
    db.flush()
    return row


def _own(db: Session, user_id: uuid.UUID, outbox_id: uuid.UUID) -> Outbox:
    row = db.get(Outbox, outbox_id)
    if row is None or row.user_id != user_id:
        raise LookupError("not found")
    return row


def cancel(db: Session, user_id: uuid.UUID, outbox_id: uuid.UUID) -> Outbox:
    """Undo / unschedule: the mail stays a Gmail draft."""
    row = db.scalar(select(Outbox).where(Outbox.id == outbox_id, Outbox.user_id == user_id).with_for_update())
    if row is None:
        raise LookupError("not found")
    if row.status != "scheduled":
        raise OutboxError("Already sent" if row.status in ("sending", "sent") else "Not scheduled")
    row.status = "cancelled"
    db.flush()
    return row


def send_now(db: Session, user_id: uuid.UUID, outbox_id: uuid.UUID) -> Outbox:
    row = _own(db, user_id, outbox_id)
    if row.status != "scheduled":
        raise OutboxError("Not scheduled")
    row.send_at = datetime.now(UTC)
    db.flush()
    return row


def reschedule(db: Session, user_id: uuid.UUID, outbox_id: uuid.UUID, send_at: datetime) -> Outbox:
    row = _own(db, user_id, outbox_id)
    if row.status != "scheduled":
        raise OutboxError("Not scheduled")
    now = datetime.now(UTC)
    if not (now + timedelta(seconds=30) <= send_at <= now + LATER_MAX):
        raise OutboxError("Pick a time from a minute from now up to a year ahead")
    row.send_at, row.later = send_at, True
    db.flush()
    return row


def any_due(db: Session, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    return db.scalar(select(func.count()).select_from(Outbox).where(
        ((Outbox.status == "scheduled") & (Outbox.send_at <= now))
        | ((Outbox.status == "sending") & (Outbox.sending_since <= now - STUCK_AFTER)))) > 0


def _claim(outbox_id: uuid.UUID) -> bool:
    with get_sessionmaker()() as db:
        row = db.scalar(select(Outbox).where(Outbox.id == outbox_id, Outbox.status == "scheduled",
                                             Outbox.send_at <= datetime.now(UTC)).with_for_update(skip_locked=True))
        if row is None:
            return False
        row.status, row.sending_since, row.attempts = "sending", datetime.now(UTC), row.attempts + 1
        db.commit()
        return True


def _failed(db: Session, row: Outbox, reason: str) -> None:
    row.status, row.error = "failed", reason[:300]
    notify.send_system(db, row.user_id, "Couldn't send your mail",
                       f"“{row.subject or '(no subject)'}” wasn't sent: {reason} It's still in your Gmail drafts.")


def send_one(outbox_id: uuid.UUID) -> str:
    """Send one due row. Returns its new status (or "skipped" when not claimable)."""
    if not _claim(outbox_id):
        return "skipped"
    with get_sessionmaker()() as db:
        row = db.get(Outbox, outbox_id)
        account = db.get(GmailAccount, row.account_id)
        try:
            if account is None or account.status != "active":
                raise AuthRevoked("account not active")
            sent = account_service.provider_for(account).send_draft(row.draft_id)
        except AuthRevoked as exc:
            if account is not None and account.status == "active":
                account_service.mark_auth_failure(account, exc)
            _failed(db, row, "Gmail sign-in for this account expired; reconnect it in Accounts.")
        except GmailError as exc:
            if exc.status == 404:
                _failed(db, row, "The draft was deleted before it was sent.")
            elif exc.status in (429, 500, 502, 503, 504) and row.attempts < MAX_ATTEMPTS:
                row.status, row.error = "scheduled", f"Gmail {exc.status}; retrying"
                row.send_at = datetime.now(UTC) + timedelta(seconds=30 * 2 ** row.attempts)
            elif exc.status == 403:
                _failed(db, row, "Sift no longer has permission to send from this account (Accounts → Allow changes).")
            else:
                log.warning("send failed for outbox %s: %s", row.id, exc.status)
                _failed(db, row, f"Gmail refused it ({exc.status}).")
        except httpx.HTTPError:
            if row.attempts < MAX_ATTEMPTS:
                row.status, row.error = "scheduled", "Network error; retrying"
                row.send_at = datetime.now(UTC) + timedelta(seconds=30 * 2 ** row.attempts)
            else:
                _failed(db, row, "Gmail couldn't be reached.")
        else:
            row.status, row.sent_at, row.error = "sent", datetime.now(UTC), None
            row.sent_gmail_id = sent.get("id")
            row.thread_id = sent.get("threadId") or row.thread_id
            if row.follow_up_days:
                db.add(FollowUp(user_id=row.user_id, account_id=row.account_id, thread_id=row.thread_id or "",
                                sent_gmail_id=row.sent_gmail_id, subject=row.subject, recipients=row.recipients,
                                sent_at=row.sent_at, due_at=row.sent_at + timedelta(days=row.follow_up_days)))
        db.commit()
        return row.status


def _recover_stuck(db: Session) -> int:
    """Rows left "sending" by a worker that stopped mid-send: sent if Gmail no longer has the draft."""
    n = 0
    for row in db.scalars(select(Outbox).where(Outbox.status == "sending",
                                               Outbox.sending_since <= datetime.now(UTC) - STUCK_AFTER).with_for_update(skip_locked=True)):
        account = db.get(GmailAccount, row.account_id)
        try:
            account_service.provider_for(account).get_draft_meta(row.draft_id)
            row.status = "scheduled"  # still a draft: it was not sent; try again
        except GmailError as exc:
            if exc.status != 404:
                continue
            row.status, row.sent_at, row.error = "sent", datetime.now(UTC), None  # drafts.send consumed it
        except (AuthRevoked, httpx.HTTPError):
            continue
        n += 1
    db.commit()
    return n


def send_due() -> int:
    """Worker job: send everything due now."""
    with get_sessionmaker()() as db:
        _recover_stuck(db)
        ids = list(db.scalars(select(Outbox.id).where(Outbox.status == "scheduled", Outbox.send_at <= datetime.now(UTC))
                              .order_by(Outbox.send_at).limit(100)))
    return sum(1 for i in ids if send_one(i) == "sent")


# ---- follow-ups --------------------------------------------------------------------------------

def _replied(db: Session, f: FollowUp, me: str) -> bool:
    return db.scalar(select(func.count()).select_from(Message).where(
        Message.account_id == f.account_id, Message.thread_id == f.thread_id,
        Message.received_at > f.sent_at, func.lower(func.coalesce(Message.sender, "")) != me)) > 0


def on_new_mail(db: Session, msg: Message, account: GmailAccount) -> None:
    """A message from someone else in a followed-up conversation resolves the follow-up."""
    if (msg.sender or "").lower() == account.email.lower():
        return
    for f in db.scalars(select(FollowUp).where(FollowUp.account_id == msg.account_id, FollowUp.thread_id == msg.thread_id,
                                               FollowUp.status == "waiting")):
        f.status = "replied"


def remind_due(db: Session, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    sent = 0
    for f in db.scalars(select(FollowUp).where(FollowUp.status == "waiting", FollowUp.due_at <= now).with_for_update(skip_locked=True)):
        account = db.get(GmailAccount, f.account_id)
        if account is None or _replied(db, f, account.email.lower()):
            f.status = "replied"
            continue
        days = max(1, round((now - f.sent_at).total_seconds() / 86400))
        notify.send_system(db, f.user_id, "No reply yet",
                           f"“{f.subject or '(no subject)'}” to {f.recipients or 'them'}, sent {days} day{'s' if days != 1 else ''} ago.")
        f.status = "reminded"
        sent += 1
    db.commit()
    return sent


def outbox_json(row: Outbox) -> dict:
    return {"id": str(row.id), "account_id": str(row.account_id), "draft_id": row.draft_id, "thread_id": row.thread_id,
            "subject": row.subject, "recipients": row.recipients, "send_at": row.send_at.isoformat(), "later": row.later,
            "follow_up_days": row.follow_up_days, "status": row.status, "error": row.error,
            "sent_at": row.sent_at.isoformat() if row.sent_at else None}


def follow_up_json(f: FollowUp) -> dict:
    return {"id": str(f.id), "account_id": str(f.account_id), "thread_id": f.thread_id, "subject": f.subject,
            "recipients": f.recipients, "sent_at": f.sent_at.isoformat(), "due_at": f.due_at.isoformat(), "status": f.status}

"""Notification records and FCM delivery, acknowledgements and re-sends (brief section 11).

One Notification row per message (unique), so a message can never notify twice. The app
acknowledges on receipt; unacknowledged urgent notifications are re-sent.
"""
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import fcm, folders, grouping, user_settings
from app.models import Device, GmailAccount, Message, Notification

log = logging.getLogger(__name__)
NOTIFY_PRIORITIES = ("urgent", "normal", "digest")


def _devices(db: Session, user_id: uuid.UUID) -> list[str]:
    return list(db.scalars(select(Device.fcm_token).where(Device.user_id == user_id)))


def _send_all(db: Session, user_id: uuid.UUID, data: dict) -> int:
    tokens = _devices(db, user_id)
    if not tokens:
        return 0
    sent, stale = 0, []
    for token in tokens:
        try:
            r = fcm.send(token, data)
        except fcm.FcmNotConfigured:
            log.warning("FCM not configured; notification stored but not sent")
            return 0
        except Exception:
            log.exception("fcm send error")
            continue
        sent += r.ok
        if r.token_invalid:
            stale.append(token)
    if stale:
        db.execute(delete(Device).where(Device.fcm_token.in_(stale)))
    return sent


def send_data(db: Session, user_id: uuid.UUID, data: dict) -> int:
    """A data-only message to every phone of the user (nothing is shown), e.g. a live sync."""
    return _send_all(db, user_id, data)


def payload(n: Notification, msg: Message, account: GmailAccount, last_folder: str = "") -> dict:
    ext = msg.extraction or {}
    links = ext.get("links") or []
    return {
        "type": "mail",
        "notification_id": str(n.id),
        "message_id": str(msg.id),
        "priority": n.priority,
        "title": msg.sender_name or msg.sender or "New mail",
        "body": ext.get("summary") or msg.subject or "(no subject)",
        "subject": msg.subject or "",
        "category": msg.category or "other",
        "company": ext.get("company") or "",
        "account": account.label or account.email,
        "account_color": account.color or "",
        "link": links[0]["url"] if links else "",
        "link_label": links[0]["label"] if links else "",
        "deadline": ext.get("deadline") or "",
        "todo_id": ext.get("todo_id") or "",
        # "which company?" buttons: up to 3 "id|name" pairs, separated by newlines (FCM data is strings only)
        "company_choices": "\n".join(f"{c['id']}|{c['name']}" for c in (ext.get("company_question") or [])[:3]),
        "last_folder": last_folder,  # for the "File in <folder>" button
        "sent_at_ms": int(time.time() * 1000),
    }


def notify_message(db: Session, msg: Message, account: GmailAccount) -> Notification | None:
    if msg.priority not in NOTIFY_PRIORITIES:
        return None
    # Per-folder setting (brief section 18) and muted groups (section 21). Mute never holds back
    # urgent mail; a folder set to "always" raises digest mail to a normal (sounding) notification.
    mode = folders.notify_mode_for(db, msg)
    if msg.priority != "urgent" and mode != "always" and (mode == "mute" or grouping.is_muted(db, msg)):
        return None
    priority = "normal" if mode == "always" and msg.priority == "digest" else msg.priority
    stmt = insert(Notification).values(
        user_id=msg.user_id, message_id=msg.id, priority=priority, mail_received_at=msg.received_at,
    ).on_conflict_do_nothing(index_elements=["message_id"]).returning(Notification.id)
    notification_id = db.execute(stmt).scalar()
    if notification_id is None:
        return None  # already notified
    n = db.get(Notification, notification_id)
    last = folders.last_used(db, msg.user_id)
    if _send_all(db, msg.user_id, payload(n, msg, account, last.name if last else "")):
        n.sent_at = datetime.now(UTC)
    db.flush()
    return n


def notify_match(db: Session, msg: Message, account: GmailAccount, search_name: str) -> Notification | None:
    """A new mail matched a saved search set to notify (even mail a rule quieted: the user asked
    for these). Normal priority; one notification per message, like every other."""
    stmt = insert(Notification).values(
        user_id=msg.user_id, message_id=msg.id, priority="normal", mail_received_at=msg.received_at,
    ).on_conflict_do_nothing(index_elements=["message_id"]).returning(Notification.id)
    notification_id = db.execute(stmt).scalar()
    if notification_id is None:
        return None
    n = db.get(Notification, notification_id)
    data = payload(n, msg, account)
    data["title"] = f"{search_name} · {data['title']}"[:120]
    data["saved_search"] = search_name
    if _send_all(db, msg.user_id, data):
        n.sent_at = datetime.now(UTC)
    db.flush()
    return n


def send_reminder(db: Session, user_id: uuid.UUID, data: dict) -> int:
    return _send_all(db, user_id, data)


def send_system(db: Session, user_id: uuid.UUID, title: str, body: str) -> None:
    _send_all(db, user_id, {"type": "system", "priority": "normal", "title": title, "body": body, "sent_at_ms": int(time.time() * 1000)})


def acknowledge(db: Session, user_id: uuid.UUID, notification_id: uuid.UUID) -> bool:
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user_id:
        return False
    if n.acknowledged_at is None:
        n.acknowledged_at = datetime.now(UTC)
    return True


def resend_unacknowledged(db: Session) -> int:
    """Re-send urgent notifications that the phone has not acknowledged in time."""
    resent = 0
    pending = db.scalars(
        select(Notification).where(Notification.priority == "urgent", Notification.acknowledged_at.is_(None), Notification.message_id.is_not(None))
    )
    now = datetime.now(UTC)
    for n in pending:
        s = user_settings.get(db, n.user_id)
        if not s["resend_urgent"] or n.resend_count >= int(s["resend_limit"]):
            continue
        last = n.sent_at or n.created_at
        if now - last < timedelta(minutes=int(s["resend_after_minutes"])):
            continue
        msg = db.get(Message, n.message_id)
        account = db.get(GmailAccount, msg.account_id)
        n.resend_count += 1
        if _send_all(db, n.user_id, {**payload(n, msg, account), "resend": n.resend_count}):
            n.sent_at = now
        resent += 1
    db.commit()
    return resent

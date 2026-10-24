import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import accounts as account_service
from app.db import get_db
from app.mail.base import AuthRevoked
from app.mail.message import extract_body
from app.models import GmailAccount, Message, Notification, User
from app.security import current_user

router = APIRouter(prefix="/api/v1/messages")
FEED_STATUSES = ("processed",)
SILENCED_STATUSES = ("silenced", "ignored")


def message_json(m: Message, account: GmailAccount | None = None, notification: Notification | None = None) -> dict:
    ext = m.extraction or {}
    return {
        "id": str(m.id), "account_id": str(m.account_id),
        "account": (account.label or account.email) if account else None,
        "account_color": account.color if account else None,
        "thread_id": m.thread_id, "sender": m.sender, "sender_name": m.sender_name,
        "subject": m.subject, "snippet": m.snippet,
        "received_at": m.received_at.isoformat() if m.received_at else None,
        "priority": m.priority, "category": m.category, "status": m.status,
        "has_attachment": m.has_attachment, "unread": "UNREAD" in (m.labels or []),
        "matched_rule_id": str(m.matched_rule_id) if m.matched_rule_id else None,
        "summary": ext.get("summary"), "company": ext.get("company"), "platform": ext.get("platform"),
        "deadline": ext.get("deadline"), "links": ext.get("links") or [], "action_needed": ext.get("action_needed", False),
        "decided_by": ext.get("source") or ("rule" if m.matched_rule_id else ext.get("heuristic") and "heuristic"),
        "notified_at": notification.sent_at.isoformat() if notification and notification.sent_at else None,
        "delivered_at": notification.acknowledged_at.isoformat() if notification and notification.acknowledged_at else None,
    }


@router.get("")
def list_messages(
    priority: str | None = Query(default=None, pattern="^(urgent|normal|digest|silent)$"),
    account_id: uuid.UUID | None = None,
    view: str = Query(default="feed", pattern="^(feed|silenced|all)$"),
    before: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    q = select(Message).where(Message.user_id == user.id)
    if view == "feed":
        q = q.where(Message.status.in_(FEED_STATUSES))
    elif view == "silenced":
        q = q.where(Message.status.in_(SILENCED_STATUSES))
    if priority:
        q = q.where(Message.priority == priority)
    if account_id:
        q = q.where(Message.account_id == account_id)
    if before:
        q = q.where(Message.received_at < before)
    rows = list(db.scalars(q.order_by(Message.received_at.desc().nulls_last()).limit(limit)))
    accounts = {a.id: a for a in db.scalars(select(GmailAccount).where(GmailAccount.user_id == user.id))}
    items = [message_json(m, accounts.get(m.account_id)) for m in rows]
    return {"items": items, "next_before": rows[-1].received_at.isoformat() if len(rows) == limit and rows[-1].received_at else None}


def _own(db: Session, user: User, message_id: uuid.UUID) -> Message:
    m = db.get(Message, message_id)
    if m is None or m.user_id != user.id:
        raise HTTPException(404, "message not found")
    return m


@router.get("/{message_id}")
def get_message(message_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    m = _own(db, user, message_id)
    n = db.scalar(select(Notification).where(Notification.message_id == m.id))
    return message_json(m, db.get(GmailAccount, m.account_id), n)


@router.get("/{message_id}/body")
def get_body(message_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Plain-text body fetched live from Gmail for reading. Not stored, not logged.
    (The sandboxed HTML reader arrives in Phase 3.)"""
    m = _own(db, user, message_id)
    account = db.get(GmailAccount, m.account_id)
    if account.status != "active":
        raise HTTPException(409, f"account is {account.status}")
    try:
        full = account_service.provider_for(account).get_full(m.gmail_id)
    except AuthRevoked as exc:
        account_service.mark_auth_failure(account, exc)
        db.commit()
        raise HTTPException(409, f"account is {account.status}") from exc
    text, files = extract_body(full.get("payload", {}))
    return {"text": text.strip()[:100_000], "attachments": files}

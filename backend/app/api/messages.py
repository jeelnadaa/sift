import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import accounts as account_service
from app import grouping, reader, rule_tools
from app import snooze as snooze_service
from app.db import get_db
from app.mail.base import AuthRevoked
from app.mail.gmail import GmailError
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
        "starred": "STARRED" in (m.labels or []), "in_inbox": "INBOX" in (m.labels or []),
        "matched_rule_id": str(m.matched_rule_id) if m.matched_rule_id else None,
        "summary": ext.get("summary"), "company": ext.get("company"), "platform": ext.get("platform"),
        "deadline": ext.get("deadline"), "links": ext.get("links") or [], "action_needed": ext.get("action_needed", False),
        "opportunity_id": ext.get("opportunity_id"), "todo_id": ext.get("todo_id"),
        "company_question": ext.get("company_question"),
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
    grouped: bool = False,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """`grouped=true` folds mail in groups into group rows when the user turned grouping on
    (brief section 21); urgent mail keeps its own row too. Items then carry "type".
    Pages are cursor based (`before` = the previous page's `next_before`); `total` counts the
    rows in all pages and `pages` how many pages of `limit` mails that makes, for "Page 2 of 7"."""
    q = select(Message).where(Message.user_id == user.id)
    if view == "feed":
        q = q.where(Message.status.in_(FEED_STATUSES), ~snooze_service.active_condition())  # snoozed: back when it wakes
    elif view == "silenced":
        q = q.where(Message.status.in_(SILENCED_STATUSES))
    if priority:
        q = q.where(Message.priority == priority)
    if account_id:
        q = q.where(Message.account_id == account_id)
    accounts = {a.id: a for a in db.scalars(select(GmailAccount).where(GmailAccount.user_id == user.id))}
    if grouped and view == "feed" and grouping.enabled(db, user.id):
        rows, groups, next_before, mail_total, group_total = grouping.feed_page(db, user.id, q, before, limit)
        items = [{"type": "mail", **message_json(m, accounts.get(m.account_id))} for m in rows]
        items += [grouping.group_json(g, ms) for g, ms in groups]
        items.sort(key=lambda i: i["received_at"] or "", reverse=True)
        return {"items": items, "next_before": next_before, "grouped": True,
                "total": mail_total + group_total, "pages": page_count(mail_total, limit)}
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    if before:
        q = q.where(Message.received_at < before)
    rows = list(db.scalars(q.order_by(Message.received_at.desc().nulls_last()).limit(limit)))
    items = [message_json(m, accounts.get(m.account_id)) for m in rows]
    return {"items": items, "next_before": rows[-1].received_at.isoformat() if len(rows) == limit and rows[-1].received_at else None,
            "total": total, "pages": page_count(total, limit)}


def page_count(total: int, limit: int) -> int:
    return max(1, -(-total // limit))


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


@router.get("/{message_id}/thread")
def get_thread(message_id: uuid.UUID, images: bool | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """The whole conversation, fetched live from Gmail: sanitized HTML (remote images blocked
    unless `images`, and then only through the image proxy), plain text, and attachments as
    signed links. Not stored, not logged."""
    m = _own(db, user, message_id)
    return thread_json(db, user, db.get(GmailAccount, m.account_id), m.thread_id, images, m.subject)


def thread_json(db: Session, user: User, account: GmailAccount, thread_id: str, images: bool | None, fallback_subject: str | None = None) -> dict:
    if images is None:  # the user's setting (default: load, through the image proxy)
        from app import user_settings
        images = bool(user_settings.get(db, user.id)["load_remote_images"])
    if account.status != "active":
        raise HTTPException(409, f"account is {account.status}")
    try:
        thread = account_service.provider_for(account).get_thread(thread_id)
    except AuthRevoked as exc:
        account_service.mark_auth_failure(account, exc)
        db.commit()
        raise HTTPException(409, f"account is {account.status}") from exc
    except GmailError as exc:
        raise HTTPException(404 if exc.status == 404 else 502, "conversation not available") from exc
    msgs = reader.render_thread(thread, user_id=str(user.id), account_id=str(account.id), base="", images=images)
    stored = dict(db.execute(select(Message.gmail_id, Message.id).where(
        Message.account_id == account.id, Message.gmail_id.in_([x["gmail_id"] for x in msgs]))).all())
    for x in msgs:
        x["id"] = str(stored[x["gmail_id"]]) if x["gmail_id"] in stored else None
        x.pop("html")  # clients load the sandboxed document from html_url instead
    return {"thread_id": thread_id, "account": account.label or account.email, "account_id": str(account.id),
            "subject": (msgs[0]["subject"] if msgs else fallback_subject) or "", "images": images, "messages": msgs}


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


class LikeThisIn(BaseModel):
    action: str = Field(default="silent", pattern="^(silent|digest|ignore)$")
    save: bool = True  # False returns the draft + preview without saving (for review)


@router.post("/{message_id}/like-this")
def like_this(message_id: uuid.UUID, body: LikeThisIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """One-tap "ignore mails like this": same verified sender + same subject template."""
    m = _own(db, user, message_id)
    try:
        draft = rule_tools.like_this(m, body.action)
    except rule_tools.RuleToolError as exc:
        raise HTTPException(422, str(exc)) from exc
    result = {"draft": draft, "preview": rule_tools.preview(db, user.id, draft["conditions"])}
    if body.save:
        rule = rule_tools.save_rule(db, user.id, draft, origin="one_tap")
        if body.action in ("silent", "ignore"):
            rule_tools.remember_template(db, m, body.action)
            m.status, m.priority = ("silenced" if body.action == "silent" else "ignored"), "silent"
        db.commit()
        result["rule_id"] = str(rule.id)
    return result


@router.post("/{message_id}/unsilence")
def unsilence(message_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """"Not like this" from the Silenced view."""
    m = _own(db, user, message_id)
    if m.status not in SILENCED_STATUSES:
        raise HTTPException(409, "mail is not silenced")
    result = rule_tools.unsilence(db, m)
    db.commit()
    return result

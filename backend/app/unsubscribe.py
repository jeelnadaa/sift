"""One-Tap Unsubscribe Hub and Execution (Phase C Item 3, RFC 8058)."""
import re
import uuid
from datetime import datetime

import httpx
from sqlalchemy import String, cast, desc, func, or_, select
from sqlalchemy.orm import Session

from app.models import GmailAccount, Message, Rule, User


def parse_unsubscribe_headers(unsub_header: str | None, unsub_post_header: str | None = None) -> tuple[str | None, str | None, bool]:
    """Extract http url, mailto link, and RFC 8058 one-click capability from List-Unsubscribe headers."""
    if not unsub_header:
        return None, None, False

    urls = re.findall(r"<(https?://[^>]+)>", unsub_header)
    mailtos = re.findall(r"<(mailto:[^>]+)>", unsub_header)

    unsub_url = urls[0].strip() if urls else None
    unsub_mailto = mailtos[0].strip() if mailtos else None
    is_post = bool(unsub_url and unsub_post_header and "one-click" in unsub_post_header.lower())

    return unsub_url, unsub_mailto, is_post


def execute_unsubscribe(db: Session, user: User, message_id: uuid.UUID) -> dict:
    """Execute one-tap unsubscribe via RFC 8058 HTTP POST or provide unsubscribe target,
    and automatically create a rule silencing future emails from the sender."""
    msg = db.get(Message, message_id)
    if not msg or msg.user_id != user.id:
        raise ValueError("message not found")

    unsub_url = msg.unsubscribe_url
    unsub_mailto = msg.unsubscribe_mailto
    is_post = msg.unsubscribe_post

    # If headers weren't stored on the row, try extracting from full message if available
    if not (unsub_url or unsub_mailto):
        account = db.get(GmailAccount, msg.account_id)
        if account:
            try:
                from app import accounts as account_service
                full = account_service.provider_for(account).get_full(msg.gmail_id)
                headers = {h.get("name", "").lower(): h.get("value", "") for h in full.get("payload", {}).get("headers", [])}
                unsub_url, unsub_mailto, is_post = parse_unsubscribe_headers(
                    headers.get("list-unsubscribe"),
                    headers.get("list-unsubscribe-post"),
                )
                msg.unsubscribe_url = unsub_url
                msg.unsubscribe_mailto = unsub_mailto
                msg.unsubscribe_post = is_post
            except Exception:
                pass

    if not (unsub_url or unsub_mailto):
        raise ValueError("This email does not support one-tap unsubscribe.")

    status = "ready"
    error = None

    # If RFC 8058 one-click is supported, send HTTP POST directly
    if is_post and unsub_url:
        try:
            res = httpx.post(
                unsub_url,
                data={"List-Unsubscribe": "One-Click"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10.0,
                follow_redirects=True,
            )
            if res.status_code in (200, 202, 204):
                status = "one_click_posted"
            else:
                status = "http_error"
                error = f"Server returned status {res.status_code}"
        except Exception as exc:
            status = "request_failed"
            error = str(exc)
    elif unsub_url:
        status = "url_available"
    elif unsub_mailto:
        status = "mailto_available"

    # Always create a silent rule for this sender so future mail won't notify
    rule_created = False
    if msg.sender:
        existing_rule = db.scalar(
            select(Rule.id).where(
                Rule.user_id == user.id,
                Rule.conditions == {"field": "sender", "op": "equals", "value": msg.sender},
            )
        )
        if not existing_rule:
            rule = Rule(
                user_id=user.id,
                name=f"Unsubscribed: {msg.sender_name or msg.sender}",
                position=1,
                enabled=True,
                conditions={"field": "sender", "op": "equals", "value": msg.sender},
                action={"type": "silence"},
            )
            db.add(rule)
            rule_created = True

    db.commit()

    return {
        "status": status,
        "sender": msg.sender,
        "sender_name": msg.sender_name,
        "unsubscribe_url": unsub_url,
        "unsubscribe_mailto": unsub_mailto,
        "is_one_click": is_post,
        "rule_created": rule_created,
        "error": error,
    }


def list_newsletters(db: Session, user_id: uuid.UUID, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
    """List newsletters and subscriptions with unsubscribe capability."""
    stmt = (
        select(
            Message.sender,
            func.max(Message.sender_name).label("sender_name"),
            func.max(Message.authenticated_domain).label("domain"),
            func.max(Message.list_id).label("list_id"),
            func.max(Message.unsubscribe_url).label("unsubscribe_url"),
            func.max(Message.unsubscribe_mailto).label("unsubscribe_mailto"),
            func.bool_or(Message.unsubscribe_post).label("unsubscribe_post"),
            func.count(Message.id).label("total_count"),
            func.max(Message.received_at).label("last_received_at"),
            func.max(cast(Message.id, String)).label("latest_message_id"),
        )
        .where(
            Message.user_id == user_id,
            Message.sender.is_not(None),
            or_(
                Message.unsubscribe_url.is_not(None),
                Message.unsubscribe_mailto.is_not(None),
                Message.list_id.is_not(None),
            ),
        )
        .group_by(Message.sender)
        .order_by(desc("total_count"), desc("last_received_at"))
    )

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = stmt.offset(max(0, offset)).limit(max(1, min(limit, 100)))
    rows = db.execute(stmt).all()

    items = []
    for r in rows:
        email = r.sender
        derived_dom = r.domain or (email.split("@")[-1] if "@" in email else None)
        items.append({
            "email": email,
            "name": r.sender_name,
            "domain": derived_dom,
            "list_id": r.list_id,
            "can_unsubscribe": bool(r.unsubscribe_url or r.unsubscribe_mailto),
            "unsubscribe_url": r.unsubscribe_url,
            "unsubscribe_mailto": r.unsubscribe_mailto,
            "is_one_click": bool(r.unsubscribe_post),
            "total_count": int(r.total_count),
            "last_received_at": r.last_received_at.isoformat() if r.last_received_at else None,
            "latest_message_id": str(r.latest_message_id),
        })

    return items, total

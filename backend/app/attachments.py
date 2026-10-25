"""Attachments Hub: indexing, query filtering, and stats (Phase C Item 1)."""
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import reader, signing
from app.config import get_settings
from app.models import GmailAccount, Message, MessageAttachment

TYPE_FILTERS = {
    "pdf": [MessageAttachment.mime == "application/pdf", MessageAttachment.filename.ilike("%.pdf")],
    "image": [MessageAttachment.mime.startswith("image/"), MessageAttachment.filename.ilike("%.png"), MessageAttachment.filename.ilike("%.jpg"), MessageAttachment.filename.ilike("%.jpeg"), MessageAttachment.filename.ilike("%.gif")],
    "sheet": [MessageAttachment.mime.ilike("%excel%"), MessageAttachment.mime.ilike("%spreadsheet%"), MessageAttachment.filename.ilike("%.xlsx"), MessageAttachment.filename.ilike("%.xls"), MessageAttachment.filename.ilike("%.csv")],
    "doc": [MessageAttachment.mime.ilike("%word%"), MessageAttachment.mime.ilike("%document%"), MessageAttachment.filename.ilike("%.docx"), MessageAttachment.filename.ilike("%.doc"), MessageAttachment.filename.ilike("%.txt")],
    "archive": [MessageAttachment.mime.ilike("%zip%"), MessageAttachment.mime.ilike("%tar%"), MessageAttachment.mime.ilike("%compressed%"), MessageAttachment.filename.ilike("%.zip"), MessageAttachment.filename.ilike("%.tar%"), MessageAttachment.filename.ilike("%.gz"), MessageAttachment.filename.ilike("%.rar")],
}


def index_attachments(db: Session, msg: Message, account: GmailAccount, payload: dict) -> list[MessageAttachment]:
    """Extract and record attachments from message payload into message_attachments table."""
    parts = reader.walk(payload)
    if not parts.attachments:
        return []

    created = []
    for a in parts.attachments:
        # Check if already indexed
        exists = db.scalar(
            select(MessageAttachment.id).where(
                MessageAttachment.message_id == msg.id,
                MessageAttachment.attachment_id == a.attachment_id,
            )
        )
        if exists:
            continue
        att = MessageAttachment(
            user_id=msg.user_id,
            account_id=account.id,
            message_id=msg.id,
            gmail_id=msg.gmail_id,
            attachment_id=a.attachment_id,
            filename=a.filename or "attachment",
            mime=a.mime or "application/octet-stream",
            size=int(a.size or 0),
            content_id=a.content_id,
            sender=msg.sender,
            sender_name=msg.sender_name,
            subject=msg.subject,
            received_at=msg.received_at,
        )
        db.add(att)
        created.append(att)
    db.flush()
    return created


def download_url(att: MessageAttachment, base: str = "") -> str:
    """Generate signed download URL for the attachment."""
    token = signing.make(
        "file",
        {
            "u": str(att.user_id),
            "a": str(att.account_id),
            "m": att.gmail_id,
            "x": att.attachment_id,
            "n": att.filename[:200],
            "t": att.mime,
            "i": False,
        },
        reader.FILE_TTL,
    )
    base_url = base or get_settings().public_base_url.rstrip("/")
    return f"{base_url}/api/v1/files/{token}"


def attachment_json(att: MessageAttachment, base: str = "") -> dict:
    return {
        "id": str(att.id),
        "message_id": str(att.message_id),
        "account_id": str(att.account_id),
        "filename": att.filename,
        "mime": att.mime,
        "size": att.size,
        "sender": att.sender,
        "sender_name": att.sender_name,
        "subject": att.subject,
        "received_at": att.received_at.isoformat() if att.received_at else None,
        "download_url": download_url(att, base),
    }


def list_attachments(
    db: Session,
    user_id: uuid.UUID,
    q: str | None = None,
    type_filter: str | None = None,
    min_size: int | None = None,
    max_size: int | None = None,
    account_id: uuid.UUID | None = None,
    before: datetime | None = None,
    limit: int = 30,
    base: str = "",
) -> tuple[list[dict], datetime | None, int]:
    stmt = select(MessageAttachment).where(MessageAttachment.user_id == user_id)

    if account_id:
        stmt = stmt.where(MessageAttachment.account_id == account_id)
    if q and q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(
            (MessageAttachment.filename.ilike(term))
            | (MessageAttachment.sender.ilike(term))
            | (MessageAttachment.sender_name.ilike(term))
            | (MessageAttachment.subject.ilike(term))
        )
    if type_filter and type_filter in TYPE_FILTERS:
        from sqlalchemy import or_
        stmt = stmt.where(or_(*TYPE_FILTERS[type_filter]))
    elif type_filter and type_filter.strip():
        stmt = stmt.where(MessageAttachment.mime.ilike(f"%{type_filter.strip()}%"))

    if min_size is not None and min_size > 0:
        stmt = stmt.where(MessageAttachment.size >= min_size)
    if max_size is not None and max_size > 0:
        stmt = stmt.where(MessageAttachment.size <= max_size)

    # Count total matching query before cursor
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    if before:
        stmt = stmt.where(MessageAttachment.received_at < before)

    stmt = stmt.order_by(MessageAttachment.received_at.desc().nulls_last()).limit(max(1, min(limit, 100)))
    rows = list(db.scalars(stmt))

    next_before = rows[-1].received_at if (len(rows) == limit and rows[-1].received_at) else None
    return [attachment_json(r, base) for r in rows], next_before, total


def get_stats(db: Session, user_id: uuid.UUID) -> dict:
    """Aggregated attachment metrics for the user."""
    total_count = db.scalar(select(func.count(MessageAttachment.id)).where(MessageAttachment.user_id == user_id)) or 0
    total_size = db.scalar(select(func.coalesce(func.sum(MessageAttachment.size), 0)).where(MessageAttachment.user_id == user_id)) or 0

    by_type = {}
    from sqlalchemy import or_
    for k, conds in TYPE_FILTERS.items():
        cnt = db.scalar(select(func.count(MessageAttachment.id)).where(MessageAttachment.user_id == user_id, or_(*conds))) or 0
        sz = db.scalar(select(func.coalesce(func.sum(MessageAttachment.size), 0)).where(MessageAttachment.user_id == user_id, or_(*conds))) or 0
        by_type[k] = {"count": int(cnt), "size": int(sz)}

    return {
        "total_count": int(total_count),
        "total_size": int(total_size),
        "by_type": by_type,
    }

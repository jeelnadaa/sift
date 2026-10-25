"""Attachments API (Phase C Item 1)."""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app import accounts as account_service, attachments
from app.db import get_db
from app.models import GmailAccount, Message, User
from app.security import current_user

router = APIRouter(prefix="/api/v1/attachments", tags=["attachments"])


@router.get("")
def get_attachments(
    request: Request,
    q: str | None = Query(default=None),
    type: str | None = Query(default=None),
    min_size: int | None = Query(default=None),
    max_size: int | None = Query(default=None),
    account_id: uuid.UUID | None = Query(default=None),
    before: datetime | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    base = str(request.base_url).rstrip("/")
    items, next_before, total = attachments.list_attachments(
        db=db,
        user_id=user.id,
        q=q,
        type_filter=type,
        min_size=min_size,
        max_size=max_size,
        account_id=account_id,
        before=before,
        limit=limit,
        base=base,
    )
    return {
        "items": items,
        "next_before": next_before.isoformat() if next_before else None,
        "total": total,
    }


@router.get("/stats")
def get_attachment_stats(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return attachments.get_stats(db, user.id)


@router.post("/index/{message_id}")
def index_message_attachments(
    message_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    msg = db.get(Message, message_id)
    if not msg or msg.user_id != user.id:
        raise HTTPException(404, "message not found")
    account = db.get(GmailAccount, msg.account_id)
    if not account:
        raise HTTPException(404, "account not found")

    provider = account_service.provider_for(account)
    try:
        full = provider.get_full(msg.gmail_id)
    except Exception as exc:
        raise HTTPException(502, f"failed to fetch message: {exc}") from exc

    created = attachments.index_attachments(db, msg, account, full.get("payload", {}))
    db.commit()
    return {"indexed": len(created), "message_id": str(msg.id)}

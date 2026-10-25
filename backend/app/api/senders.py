"""Senders API (Phase C Item 2)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import senders, vip
from app.db import get_db
from app.models import User
from app.security import current_user

router = APIRouter(prefix="/api/v1/senders", tags=["senders"])


@router.get("")
def get_senders(
    q: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    min_count: int = Query(default=1, ge=1),
    sort_by: str = Query(default="count"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    items, total = senders.list_senders(
        db=db,
        user_id=user.id,
        q=q,
        domain=domain,
        min_count=min_count,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
    )
    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/{sender_email:path}")
def get_sender(
    sender_email: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    detail = senders.get_sender_detail(db, user.id, sender_email)
    if not detail:
        raise HTTPException(404, "sender not found")
    return detail


@router.post("/{sender_email:path}/vip")
def set_sender_vip(
    sender_email: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    row = vip.add_vip(db, user.id, sender_email)
    db.commit()
    return {"email": row.email, "is_vip": True}


@router.delete("/{sender_email:path}/vip")
def unset_sender_vip(
    sender_email: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    removed = vip.remove_vip(db, user.id, sender_email)
    db.commit()
    return {"email": sender_email.strip().lower(), "is_vip": False, "removed": removed}

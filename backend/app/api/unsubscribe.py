"""Unsubscribe API (Phase C Item 3)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import unsubscribe
from app.db import get_db
from app.models import User
from app.security import current_user

router = APIRouter(tags=["unsubscribe"])


@router.post("/api/v1/messages/{id}/unsubscribe")
def unsubscribe_message(
    id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return unsubscribe.execute_unsubscribe(db, user, id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/v1/newsletters")
def get_newsletters(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    items, total = unsubscribe.list_newsletters(db, user.id, limit=limit, offset=offset)
    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
    }

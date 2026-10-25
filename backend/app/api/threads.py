"""Threads API: muting and thread-level preferences (Phase D Item 4)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import vip
from app.db import get_db
from app.models import User
from app.security import current_user

router = APIRouter(prefix="/api/v1/threads", tags=["threads"])


@router.post("/{thread_id}/mute")
def mute_thread(thread_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    vip.mute_thread(db, user.id, thread_id)
    db.commit()
    return {"thread_id": thread_id, "is_muted": True}


@router.delete("/{thread_id}/mute")
def unmute_thread(thread_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    removed = vip.unmute_thread(db, user.id, thread_id)
    db.commit()
    return {"thread_id": thread_id, "is_muted": False, "removed": removed}


@router.get("/{thread_id}/muted")
def check_thread_muted(thread_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    muted = vip.is_thread_muted(db, user.id, thread_id)
    return {"thread_id": thread_id, "is_muted": muted}

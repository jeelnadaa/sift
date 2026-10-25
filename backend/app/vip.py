"""VIP Senders and Muted Threads service (Phase D Item 4)."""
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import MutedThread, VipSender


def is_vip(db: Session, user_id: uuid.UUID, sender_email: str | None) -> bool:
    if not sender_email or not sender_email.strip():
        return False
    clean = sender_email.strip().lower()
    stmt = select(VipSender.id).where(VipSender.user_id == user_id, VipSender.email == clean)
    return db.scalar(stmt) is not None


def get_vip_emails(db: Session, user_id: uuid.UUID) -> set[str]:
    stmt = select(VipSender.email).where(VipSender.user_id == user_id)
    return set(db.scalars(stmt))


def add_vip(db: Session, user_id: uuid.UUID, email: str, sender_name: str | None = None) -> VipSender:
    clean = email.strip().lower()
    existing = db.scalar(select(VipSender).where(VipSender.user_id == user_id, VipSender.email == clean))
    if existing:
        if sender_name and not existing.sender_name:
            existing.sender_name = sender_name
        return existing
    row = VipSender(user_id=user_id, email=clean, sender_name=sender_name)
    db.add(row)
    db.flush()
    return row


def remove_vip(db: Session, user_id: uuid.UUID, email: str) -> bool:
    clean = email.strip().lower()
    stmt = delete(VipSender).where(VipSender.user_id == user_id, VipSender.email == clean)
    result = db.execute(stmt)
    return (result.rowcount or 0) > 0


def is_thread_muted(db: Session, user_id: uuid.UUID, thread_id: str | None) -> bool:
    if not thread_id:
        return False
    stmt = select(MutedThread.id).where(MutedThread.user_id == user_id, MutedThread.thread_id == thread_id)
    return db.scalar(stmt) is not None


def get_muted_thread_ids(db: Session, user_id: uuid.UUID) -> set[str]:
    stmt = select(MutedThread.thread_id).where(MutedThread.user_id == user_id)
    return set(db.scalars(stmt))


def mute_thread(db: Session, user_id: uuid.UUID, thread_id: str) -> MutedThread:
    clean = thread_id.strip()
    existing = db.scalar(select(MutedThread).where(MutedThread.user_id == user_id, MutedThread.thread_id == clean))
    if existing:
        return existing
    row = MutedThread(user_id=user_id, thread_id=clean)
    db.add(row)
    db.flush()
    return row


def unmute_thread(db: Session, user_id: uuid.UUID, thread_id: str) -> bool:
    clean = thread_id.strip()
    stmt = delete(MutedThread).where(MutedThread.user_id == user_id, MutedThread.thread_id == clean)
    result = db.execute(stmt)
    return (result.rowcount or 0) > 0

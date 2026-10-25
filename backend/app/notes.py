"""Private notes on any mail (brief section 14).

Notes are private annotations attached to an email in Sift. They are never sent
to Gmail or the recipient. Each message can have multiple notes.
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import events
from app.models import MailNote, Message

MAX_NOTE_LENGTH = 10_000


class NoteError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def list_for_message(db: Session, user_id: uuid.UUID, message_id: uuid.UUID) -> list[MailNote]:
    q = (
        select(MailNote)
        .where(MailNote.user_id == user_id, MailNote.message_id == message_id)
        .order_by(MailNote.created_at.asc())
    )
    return list(db.scalars(q))


def get_note(db: Session, user_id: uuid.UUID, note_id: uuid.UUID) -> MailNote | None:
    return db.scalar(
        select(MailNote).where(MailNote.id == note_id, MailNote.user_id == user_id)
    )


def add_note(db: Session, user_id: uuid.UUID, message_id: uuid.UUID, body: str) -> MailNote:
    body = (body or "").strip()
    if not body:
        raise NoteError("Note content cannot be empty", 422)
    if len(body) > MAX_NOTE_LENGTH:
        raise NoteError(f"Note exceeds maximum length of {MAX_NOTE_LENGTH} characters", 422)

    msg = db.scalar(select(Message).where(Message.id == message_id, Message.user_id == user_id))
    if msg is None:
        raise NoteError("Message not found", 404)

    note = MailNote(
        user_id=user_id,
        message_id=message_id,
        body=body,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    events.mail_changed(db, user_id, [message_id])
    return note


def update_note(db: Session, user_id: uuid.UUID, message_id: uuid.UUID, note_id: uuid.UUID, body: str) -> MailNote:
    body = (body or "").strip()
    if not body:
        raise NoteError("Note content cannot be empty", 422)
    if len(body) > MAX_NOTE_LENGTH:
        raise NoteError(f"Note exceeds maximum length of {MAX_NOTE_LENGTH} characters", 422)

    note = get_note(db, user_id, note_id)
    if note is None or note.message_id != message_id:
        raise NoteError("Note not found", 404)

    note.body = body
    note.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(note)
    events.mail_changed(db, user_id, [note.message_id])
    return note


def delete_note(db: Session, user_id: uuid.UUID, message_id: uuid.UUID, note_id: uuid.UUID) -> bool:
    note = get_note(db, user_id, note_id)
    if note is None or note.message_id != message_id:
        raise NoteError("Note not found", 404)

    db.delete(note)
    db.commit()
    events.mail_changed(db, user_id, [message_id])
    return True


def note_json(note: MailNote) -> dict:
    return {
        "id": str(note.id),
        "message_id": str(note.message_id),
        "body": note.body,
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "updated_at": note.updated_at.isoformat() if note.updated_at else None,
    }

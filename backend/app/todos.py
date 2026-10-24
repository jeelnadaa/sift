"""To-dos and deadline reminders (brief sections 10, 11, 20).

Reminders fire 24 h and 2 h before a deadline. Each has a dedupe key, so re-processing a mail
or editing a to-do never schedules the same reminder twice. A reminder for a finished to-do,
or one missed by more than STALE (laptop asleep), is dropped instead of firing late.
"""
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import notify
from app.models import Reminder, Todo

log = logging.getLogger(__name__)
OFFSETS = (("deadline_24h", timedelta(hours=24)), ("deadline_2h", timedelta(hours=2)))
STALE = timedelta(hours=1)


def schedule_deadline(db: Session, user_id: uuid.UUID, key: str, title: str, due: datetime, *,
                      message_id=None, opportunity_id=None, todo_id=None) -> int:
    """Create the 24 h / 2 h reminders for a deadline that are still in the future."""
    now = datetime.now(UTC)
    created = 0
    for kind, before in OFFSETS:
        at = due - before
        if at <= now:
            continue
        stmt = insert(Reminder).values(
            user_id=user_id, message_id=message_id, opportunity_id=opportunity_id, todo_id=todo_id,
            kind=kind, title=title[:300], due_at=due, remind_at=at, dedupe_key=f"{key}:{kind}",
        ).on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"])
        created += db.execute(stmt).rowcount
    return created


def clear_pending(db: Session, todo_id: uuid.UUID) -> None:
    db.execute(delete(Reminder).where(Reminder.todo_id == todo_id, Reminder.sent_at.is_(None)))


def ai_todo(db: Session, user_id: uuid.UUID, message_id: uuid.UUID, title: str, due: datetime | None, opportunity_id=None) -> Todo:
    """One AI-created to-do per message (re-processing reuses it)."""
    todo = db.scalar(select(Todo).where(Todo.message_id == message_id, Todo.source == "ai"))
    if todo is None:
        todo = Todo(user_id=user_id, message_id=message_id, opportunity_id=opportunity_id, title=title[:300], due_at=due, source="ai")
        db.add(todo)
        db.flush()
    return todo


def send_due(db: Session) -> int:
    """Send reminders whose time has come (scheduler, every minute)."""
    now = datetime.now(UTC)
    sent = 0
    for r in db.scalars(select(Reminder).where(Reminder.sent_at.is_(None), Reminder.done.is_(False), Reminder.remind_at <= now).order_by(Reminder.remind_at)):
        todo = db.get(Todo, r.todo_id) if r.todo_id else None
        if (todo is not None and todo.done) or now - r.remind_at > STALE or (r.due_at and r.due_at <= now):
            r.done = True  # finished, missed while offline, or already past due: drop silently
            continue
        left = r.due_at - now if r.due_at else None
        when = "in 2 hours" if r.kind == "deadline_2h" else "tomorrow" if r.kind == "deadline_24h" else "soon"
        if left is not None and left < timedelta(hours=3):
            when = f"in {max(1, int(left.total_seconds() // 60))} min" if left < timedelta(hours=1) else "in 2 hours"
        notify.send_reminder(db, r.user_id, {
            "type": "reminder",
            "priority": "urgent" if r.kind == "deadline_2h" else "normal",
            "title": f"Due {when}",
            "body": r.title,
            "reminder_id": str(r.id),
            "message_id": str(r.message_id) if r.message_id else "",
            "todo_id": str(r.todo_id) if r.todo_id else "",
            "deadline": r.due_at.isoformat() if r.due_at else "",
            "sent_at_ms": int(time.time() * 1000),
        })
        r.sent_at = now
        sent += 1
    db.commit()
    return sent

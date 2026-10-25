import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import todos as todo_service
from app.db import get_db
from app.models import Message, Opportunity, Todo, User
from app.security import current_user

router = APIRouter(prefix="/api/v1/todos")


class TodoIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    notes: str | None = Field(default=None, max_length=4000)
    due_at: datetime | None = None
    message_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None


class TodoPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    notes: str | None = Field(default=None, max_length=4000)
    due_at: datetime | None = None
    clear_due: bool = False
    done: bool | None = None


def todo_json(t: Todo, msg: Message | None = None, opp: Opportunity | None = None) -> dict:
    return {
        "id": str(t.id), "title": t.title, "notes": t.notes,
        "due_at": t.due_at.isoformat() if t.due_at else None,
        "done": t.done, "done_at": t.done_at.isoformat() if t.done_at else None, "source": t.source,
        "message_id": str(t.message_id) if t.message_id else None,
        "subject": msg.subject if msg else None, "sender_name": (msg.sender_name or msg.sender) if msg else None,
        "opportunity_id": str(t.opportunity_id) if t.opportunity_id else None, "company": opp.company if opp else None,
        "created_at": t.created_at.isoformat(),
    }


def _own(db: Session, user: User, todo_id: uuid.UUID) -> Todo:
    t = db.get(Todo, todo_id)
    if t is None or t.user_id != user.id:
        raise HTTPException(404, "to-do not found")
    return t


def _check_refs(db: Session, user: User, message_id, opportunity_id) -> None:
    if message_id and ((m := db.get(Message, message_id)) is None or m.user_id != user.id):
        raise HTTPException(404, "message not found")
    if opportunity_id and ((o := db.get(Opportunity, opportunity_id)) is None or o.user_id != user.id):
        raise HTTPException(404, "opportunity not found")


def _reschedule(db: Session, t: Todo) -> None:
    todo_service.clear_pending(db, t.id)
    if t.due_at and not t.done:
        todo_service.schedule_deadline(db, t.user_id, f"todo:{t.id}:{t.due_at.isoformat()}", t.title, t.due_at,
                                       message_id=t.message_id, opportunity_id=t.opportunity_id, todo_id=t.id)


@router.get("")
def list_todos(state: str = Query(default="open", pattern="^(open|done|all)$"), user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    q = select(Todo, Message, Opportunity).outerjoin(Message, Message.id == Todo.message_id).outerjoin(Opportunity, Opportunity.id == Todo.opportunity_id).where(Todo.user_id == user.id)
    if state != "all":
        q = q.where(Todo.done.is_(state == "done"))
    q = q.order_by(Todo.done, Todo.due_at.asc().nulls_last(), Todo.created_at.desc()) if state != "done" else q.order_by(Todo.done_at.desc())
    return [todo_json(t, m, o) for t, m, o in db.execute(q.limit(500))]


@router.post("", status_code=201)
def create_todo(body: TodoIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    _check_refs(db, user, body.message_id, body.opportunity_id)
    t = Todo(user_id=user.id, title=body.title.strip(), notes=body.notes, due_at=body.due_at,
             message_id=body.message_id, opportunity_id=body.opportunity_id, source="manual")
    db.add(t)
    db.flush()
    if body.message_id:
        m = db.get(Message, body.message_id)
        if m:
            ext = dict(m.extraction or {})
            ext["todo_id"] = str(t.id)
            m.extraction = ext
            from app import events
            events.publish(db, user.id, "mail", ids=[m.id])
    _reschedule(db, t)
    db.commit()
    return todo_json(t)


@router.patch("/{todo_id}")
def update_todo(todo_id: uuid.UUID, body: TodoPatch, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    t = _own(db, user, todo_id)
    if body.title is not None:
        t.title = body.title.strip()
    if body.notes is not None:
        t.notes = body.notes
    if body.clear_due:
        t.due_at = None
    elif body.due_at is not None:
        t.due_at = body.due_at
    if body.done is not None and body.done != t.done:
        t.done, t.done_at = body.done, datetime.now(UTC) if body.done else None
        if t.message_id:
            from app import events
            events.publish(db, user.id, "mail", ids=[t.message_id])
    _reschedule(db, t)
    db.commit()
    return todo_json(t)


@router.delete("/{todo_id}", status_code=204)
def delete_todo(todo_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    t = _own(db, user, todo_id)
    todo_str = str(t.id)
    affected_ids = []
    if t.message_id:
        m = db.get(Message, t.message_id)
        if m and m.extraction and m.extraction.get("todo_id") == todo_str:
            ext = dict(m.extraction)
            ext.pop("todo_id", None)
            m.extraction = ext
            affected_ids.append(m.id)

    msgs = list(db.scalars(
        select(Message).where(
            Message.user_id == user.id,
            Message.extraction["todo_id"].astext == todo_str
        )
    ))
    for m in msgs:
        if m.id not in affected_ids and m.extraction:
            ext = dict(m.extraction)
            ext.pop("todo_id", None)
            m.extraction = ext
            affected_ids.append(m.id)

    db.delete(t)
    if affected_ids:
        from app import events
        events.publish(db, user.id, "mail", ids=affected_ids)
    db.commit()

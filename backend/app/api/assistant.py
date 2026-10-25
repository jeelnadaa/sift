"""Ask Sift (app/assistant.py): plan a request, run a plan the user approved, history."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import assistant
from app.db import get_db
from app.models import AssistantRun, User
from app.security import current_user

router = APIRouter(prefix="/api/v1/assistant")


class AskIn(BaseModel):
    text: str = Field(min_length=1, max_length=600)


def _own(db: Session, user: User, run_id: uuid.UUID, lock: bool = False) -> AssistantRun:
    q = select(AssistantRun).where(AssistantRun.id == run_id, AssistantRun.user_id == user.id)
    run = db.scalar(q.with_for_update() if lock else q)  # the lock makes a double "Run" run once
    if run is None:
        raise HTTPException(404, "not found")
    return run


@router.post("")
def ask(body: AskIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """One AI call turns the words into a plan. Read-only plans come back already run; a plan
    that changes anything comes back with needs_confirm and runs on POST /{id}/run."""
    try:
        run = assistant.plan(db, user.id, body.text)
    except assistant.AssistantError as exc:
        db.commit()  # keep token use and key status
        raise HTTPException(422, str(exc)) from exc
    return assistant.run_json(run)


@router.post("/{run_id}/run")
def run(run_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    r = _own(db, user, run_id, lock=True)
    try:
        assistant.run_steps(db, r)
    except assistant.AssistantError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return assistant.run_json(db.get(AssistantRun, run_id))


@router.post("/{run_id}/cancel")
def cancel(run_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    r = _own(db, user, run_id, lock=True)
    if r.status == "planned":
        r.status = "cancelled"
        db.commit()
    return assistant.run_json(r)


@router.get("/runs")
def runs(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(AssistantRun).where(AssistantRun.user_id == user.id).order_by(AssistantRun.created_at.desc()).limit(20))
    return [assistant.run_json(r) for r in rows]

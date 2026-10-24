"""Mail actions and snooze API (Phase 3c)."""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import accounts as account_service
from app import actions as action_service
from app import snooze as snooze_service
from app.db import get_db
from app.mail.base import AuthRevoked
from app.mail.gmail import GmailError
from app.models import GmailAccount, Message, Snooze, User
from app.security import current_user

router = APIRouter(prefix="/api/v1")


class ThreadRef(BaseModel):
    account_id: uuid.UUID
    thread_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9]+$")


class Targets(BaseModel):
    message_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)  # each acts on its conversation
    threads: list[ThreadRef] = Field(default_factory=list, max_length=500)  # conversations Sift never stored

    @model_validator(mode="after")
    def _some(self):
        if not self.message_ids and not self.threads:
            raise ValueError("pick at least one mail")
        return self


def _resolve(db: Session, user: User, t: Targets) -> list[tuple[uuid.UUID, str, uuid.UUID | None]]:
    rows = list(db.scalars(select(Message).where(Message.user_id == user.id, Message.id.in_(t.message_ids)))) if t.message_ids else []
    if len(rows) != len(set(t.message_ids)):
        raise HTTPException(404, "message not found")
    order = {mid: i for i, mid in enumerate(t.message_ids)}
    out = [(m.account_id, m.thread_id, m.id) for m in sorted(rows, key=lambda m: order[m.id])]  # in the order picked
    out += [(r.account_id, r.thread_id, None) for r in t.threads]
    return out


def _needs_access(exc: action_service.NeedsWriteAccess) -> HTTPException:
    return HTTPException(403, {"code": "needs_write_access",
                               "message": "Sift needs your permission to change mail in " + ", ".join(a.email for a in exc.accounts),
                               "accounts": [{"id": str(a.id), "email": a.email} for a in exc.accounts]})


class ActionIn(Targets):
    action: str = Field(pattern="^(" + "|".join(action_service.ACTIONS) + ")$")
    label: str | None = Field(default=None, max_length=225)


@router.post("/mail/actions")
def act(body: ActionIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Archive, read/unread, star, label, trash or spam whole conversations in Gmail. Needs write
    access for each account involved: otherwise 403 code=needs_write_access lists them."""
    threads = [(a, t) for a, t, _ in _resolve(db, user, body)]
    try:
        res = action_service.apply(db, user.id, threads, body.action, body.label)
    except action_service.NeedsWriteAccess as exc:
        raise _needs_access(exc) from exc
    except action_service.ActionError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    return {"done": res.done, "failed_accounts": res.failed}


@router.get("/accounts/{account_id}/labels")
def labels(account_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    """The account's own Gmail labels (for the label picker). Works with read-only access."""
    a = db.get(GmailAccount, account_id)
    if a is None or a.user_id != user.id:
        raise HTTPException(404, "account not found")
    try:
        items = account_service.provider_for(a).list_labels()
    except AuthRevoked as exc:
        account_service.mark_auth_failure(a, exc)
        db.commit()
        raise HTTPException(409, f"account is {a.status}") from exc
    except (GmailError, AttributeError, KeyError) as exc:
        raise HTTPException(502, "labels not available") from exc
    return sorted(({"id": x["id"], "name": x["name"]} for x in items if x.get("type") == "user"), key=lambda x: x["name"].lower())


class SnoozeIn(Targets):
    until: datetime


@router.post("/snoozes", status_code=201)
def snooze(body: SnoozeIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    """Hide the conversations until `until` (with a time zone). With write access they're also
    archived in Gmail and come back to the inbox on time; without, they're hidden in Sift only."""
    try:
        rows = snooze_service.snooze(db, user.id, _resolve(db, user, body), body.until)
    except snooze_service.SnoozeError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    return [snooze_service.snooze_json(s, db.get(Message, s.message_id) if s.message_id else None) for s in rows]


@router.get("/snoozes")
def list_snoozes(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Snooze).where(Snooze.user_id == user.id, Snooze.done.is_(False)).order_by(Snooze.until))
    return [snooze_service.snooze_json(s, db.get(Message, s.message_id) if s.message_id else None) for s in rows]


@router.delete("/snoozes/{snooze_id}", status_code=204)
def unsnooze(snooze_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    """Bring it back now (back to the Gmail inbox too, if it was archived there)."""
    s = db.get(Snooze, snooze_id)
    if s is None or s.user_id != user.id or s.done:
        raise HTTPException(404, "snooze not found")
    snooze_service.cancel(db, s)
    db.commit()

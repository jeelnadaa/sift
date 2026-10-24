import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import folders, rule_tools
from app import rules as engine
from app.llm import service as llm
from app.llm.base import LlmError
from app.db import get_db
from app.models import Rule, User
from app.security import current_user

router = APIRouter(prefix="/api/v1/rules")


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    origin: str = Field(default="editor", pattern="^(editor|english|one_tap|suggestion|scan)$")
    enabled: bool = True
    conditions: dict
    action: dict
    exceptions: dict | None = None
    account_scope: list[str] | None = None


def rule_json(r: Rule) -> dict:
    return {
        "id": str(r.id), "name": r.name, "position": r.position, "enabled": r.enabled,
        "conditions": r.conditions, "action": r.action, "exceptions": r.exceptions,
        "account_scope": r.account_scope, "origin": r.origin, "hit_count": r.hit_count,
        "last_hit_at": r.last_hit_at.isoformat() if r.last_hit_at else None,
    }


def _validate(body: RuleIn, db: Session, user: User) -> None:
    try:
        engine.validate_condition(body.conditions)
        engine.validate_action(body.action)
        if body.exceptions:
            engine.validate_condition(body.exceptions)
        check_folder(db, user, body.action)
    except (engine.RuleError, folders.FolderError) as exc:
        raise HTTPException(422, str(exc)) from exc


def check_folder(db: Session, user: User, action: dict) -> None:
    """A "file in folder" action must point at one of the user's own, normal folders."""
    if action.get("folder_id"):
        f = folders.own(db, user.id, action["folder_id"])
        if f.saved_search_id is not None:
            raise folders.FolderError("rules can't file mail into a smart folder")


def _own(db: Session, user: User, rule_id: uuid.UUID) -> Rule:
    r = db.get(Rule, rule_id)
    if r is None or r.user_id != user.id:
        raise HTTPException(404, "rule not found")
    return r


@router.get("")
def list_rules(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [rule_json(r) for r in db.scalars(select(Rule).where(Rule.user_id == user.id).order_by(Rule.position))]


@router.post("", status_code=201)
def create_rule(body: RuleIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    _validate(body, db, user)
    last = db.scalar(select(func.max(Rule.position)).where(Rule.user_id == user.id))
    r = Rule(user_id=user.id, position=(last or 0) + 1, **body.model_dump())
    db.add(r)
    db.commit()
    return rule_json(r)


@router.put("/{rule_id}")
def update_rule(rule_id: uuid.UUID, body: RuleIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    _validate(body, db, user)
    r = _own(db, user, rule_id)
    for k, v in body.model_dump(exclude={"origin"}).items():
        setattr(r, k, v)
    db.commit()
    return rule_json(r)


@router.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    db.delete(_own(db, user, rule_id))
    db.commit()


class PreviewIn(BaseModel):
    conditions: dict
    exceptions: dict | None = None
    account_scope: list[str] | None = None


@router.post("/preview")
def preview(body: PreviewIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """How many of the last 500 stored mails this rule would match, with samples (brief section 8)."""
    try:
        return rule_tools.preview(db, user.id, body.conditions, body.exceptions, body.account_scope)
    except engine.RuleError as exc:
        raise HTTPException(422, str(exc)) from exc


class TextIn(BaseModel):
    text: str = Field(min_length=3, max_length=500)


@router.post("/from-text")
def from_text(body: TextIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Plain-English rule -> draft + preview. Not saved: the user reviews it and saves with POST /rules."""
    try:
        draft = llm.rule_from_text(db, user.id, body.text)
        engine.validate_condition(draft["conditions"])
        if draft["exceptions"]:
            engine.validate_condition(draft["exceptions"])
    except (LlmError, engine.RuleError) as exc:
        db.commit()  # keep token usage / key status changes
        raise HTTPException(422, str(exc)) from exc
    except ValueError as exc:  # unparseable model output
        db.commit()
        raise HTTPException(422, "The AI's answer could not be turned into a rule. Try rephrasing.") from exc
    db.commit()
    return {"draft": draft, "preview": rule_tools.preview(db, user.id, draft["conditions"], draft["exceptions"])}


@router.get("/suggestions")
def suggestions(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    return rule_tools.suggestions(db, user.id)


class AcceptIn(BaseModel):
    action: str = Field(default="silent", pattern="^(silent|digest)$")


@router.post("/suggestions/{fingerprint_id}/accept", status_code=201)
def accept(fingerprint_id: uuid.UUID, body: AcceptIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    try:
        rule = rule_tools.accept_suggestion(db, user.id, fingerprint_id, body.action)
    except rule_tools.RuleToolError as exc:
        raise HTTPException(404, str(exc)) from exc
    db.commit()
    return rule_json(rule)


@router.post("/suggestions/{fingerprint_id}/dismiss", status_code=204)
def dismiss(fingerprint_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    try:
        rule_tools.dismiss_suggestion(db, user.id, fingerprint_id)
    except rule_tools.RuleToolError as exc:
        raise HTTPException(404, str(exc)) from exc
    db.commit()


class OrderIn(BaseModel):
    ids: list[uuid.UUID]


@router.post("/reorder")
def reorder(body: OrderIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    rules = {r.id: r for r in db.scalars(select(Rule).where(Rule.user_id == user.id))}
    if set(body.ids) != set(rules):
        raise HTTPException(422, "ids must list every rule exactly once")
    for i, rid in enumerate(body.ids, start=1):
        rules[rid].position = i
    db.commit()
    return [rule_json(rules[rid]) for rid in body.ids]

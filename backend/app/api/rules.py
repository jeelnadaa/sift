import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import rules as engine
from app.db import get_db
from app.models import Rule, User
from app.security import current_user

router = APIRouter(prefix="/api/v1/rules")


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
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


def _validate(body: RuleIn) -> None:
    try:
        engine.validate_condition(body.conditions)
        engine.validate_action(body.action)
        if body.exceptions:
            engine.validate_condition(body.exceptions)
    except engine.RuleError as exc:
        raise HTTPException(422, str(exc)) from exc


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
    _validate(body)
    last = db.scalar(select(func.max(Rule.position)).where(Rule.user_id == user.id))
    r = Rule(user_id=user.id, position=(last or 0) + 1, origin="editor", **body.model_dump())
    db.add(r)
    db.commit()
    return rule_json(r)


@router.put("/{rule_id}")
def update_rule(rule_id: uuid.UUID, body: RuleIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    _validate(body)
    r = _own(db, user, rule_id)
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    db.commit()
    return rule_json(r)


@router.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    db.delete(_own(db, user, rule_id))
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

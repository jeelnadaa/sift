import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import jobs, scan as scan_service
from app.api.rules import rule_json
from app.db import get_db
from app.models import GmailAccount, OnboardingScan, User
from app.security import current_user

router = APIRouter(prefix="/api/v1")


def scan_json(s: OnboardingScan | None) -> dict | None:
    if s is None:
        return None
    return {"id": str(s.id), "account_id": str(s.account_id), "status": s.status, "scanned": s.scanned,
            "senders": s.senders or [], "error": s.error, "applied_at": s.applied_at.isoformat() if s.applied_at else None,
            "created_at": s.created_at.isoformat(), "finished_at": s.finished_at.isoformat() if s.finished_at else None}


def _own_account(db: Session, user: User, account_id: uuid.UUID) -> GmailAccount:
    a = db.get(GmailAccount, account_id)
    if a is None or a.user_id != user.id:
        raise HTTPException(404, "account not found")
    return a


@router.get("/accounts/{account_id}/scan")
def latest_scan(account_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict | None:
    _own_account(db, user, account_id)
    return scan_json(db.scalar(select(OnboardingScan).where(OnboardingScan.account_id == account_id).order_by(OnboardingScan.created_at.desc()).limit(1)))


@router.post("/accounts/{account_id}/scan", status_code=202)
def start_scan(account_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    account = _own_account(db, user, account_id)
    if account.status != "active" or not account.encrypted_refresh_token:
        raise HTTPException(409, f"account is {account.status}")
    s = scan_service.start(db, account)
    db.commit()
    jobs.enqueue_sync("onboarding_scan", {"scan_id": str(s.id)}, dedupe_key=f"scan:{s.id}")
    return scan_json(s)


class ApplyIn(BaseModel):
    assignments: dict[str, str]  # sender key -> silent | digest | notify_normal | notify_urgent | keep


@router.post("/scans/{scan_id}/apply")
def apply_scan(scan_id: uuid.UUID, body: ApplyIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    s = db.get(OnboardingScan, scan_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "scan not found")
    if s.status != "done":
        raise HTTPException(409, "scan has not finished")
    try:
        rules = scan_service.apply(db, s, body.assignments)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    return {"rules": [rule_json(r) for r in rules]}

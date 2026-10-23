"""Phase 0 test endpoints, guarded by X-Admin-Token."""
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import fcm
from app.api.deps import require_admin
from app.db import get_db
from app.models import Device

router = APIRouter(prefix="/api/v1/dev", dependencies=[Depends(require_admin)])


class TestPushIn(BaseModel):
    token: str | None = None  # send to this token; otherwise to every registered device
    priority: str = "urgent"
    title: str = "Sift test push"
    body: str = "If you can read this, FCM works."


@router.post("/test-push")
def test_push(body: TestPushIn, db: Session = Depends(get_db)) -> dict:
    tokens = [body.token] if body.token else list(db.scalars(select(Device.fcm_token)))
    if not tokens:
        raise HTTPException(400, "no token given and no devices registered")
    data = {"type": "test", "priority": body.priority, "title": body.title, "body": body.body, "sent_at_ms": int(time.time() * 1000)}
    try:
        results = [fcm.send(t, data) for t in tokens]
    except fcm.FcmNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    stale = [t for t, r in zip(tokens, results) if r.token_invalid]
    if stale:
        db.execute(delete(Device).where(Device.fcm_token.in_(stale)))
        db.commit()
    return {"sent": sum(r.ok for r in results), "failed": [r.error for r in results if not r.ok], "removed_invalid": len(stale)}

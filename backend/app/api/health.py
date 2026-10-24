from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import intake
from app.config import get_settings
from app.db import get_db

router = APIRouter()


@router.get("/health")
def health(response: Response, db: Session = Depends(get_db)) -> dict:
    checks = {"database": "ok"}
    try:
        db.execute(text("SELECT 1"))
        # public endpoint: only a count, never which accounts (uptime monitors can watch this)
        stalled = len(intake.stalled(db))
        # reported, not a 503: the server itself is fine (Docker's healthcheck must not flag it)
        checks["mail_checks"] = "ok" if stalled == 0 else f"stalled ({stalled})"
    except Exception:
        checks["database"] = "error"
        response.status_code = 503
    return {"status": "ok" if response.status_code != 503 else "degraded", "queue": get_settings().queue_backend, **checks}

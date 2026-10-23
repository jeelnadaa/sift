from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db

router = APIRouter()


@router.get("/health")
def health(response: Response, db: Session = Depends(get_db)) -> dict:
    checks = {"database": "ok"}
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        checks["database"] = "error"
        response.status_code = 503
    return {"status": "ok" if response.status_code != 503 else "degraded", "queue": get_settings().queue_backend, **checks}

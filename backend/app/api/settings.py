from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import folder_ai
from app import backup, jobs, user_settings
from app.config import get_settings
from app.db import get_db
from app.llm import service as llm
from app.llm.base import LlmError
from app.models import AiTask, TokenUsage, User
from app.security import current_user

router = APIRouter(prefix="/api/v1")


@router.get("/settings")
def get_user_settings(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return user_settings.get(db, user.id)


@router.patch("/settings")
def patch_settings(changes: dict, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    try:
        result = user_settings.update(db, user.id, changes)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    return result


@router.get("/backup")
def export_backup(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Folders, rules, tags, categories, grouping preferences and settings as one JSON file.
    No mail, tokens or keys."""
    return backup.export(db, user.id)


@router.post("/backup")
def import_backup(data: dict, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Adds what the file holds (never deletes). All or nothing."""
    try:
        report = backup.import_(db, user.id, data)
    except backup.BackupError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    return report


# ---- AI (bring your own key) ---------------------------------------------------------

@router.get("/ai")
def ai_status(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    s = get_settings()
    return {**llm.status(db, user.id), "providers": list(llm.PROVIDERS), "suggested_model": s.llm_default_model}


class KeyIn(BaseModel):
    provider: str = "gemini"
    model: str
    api_key: str


@router.put("/ai/key")
def save_key(body: KeyIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Stores the key encrypted and validates it with one minimal call. The key is never returned."""
    try:
        llm.save_key(db, user.id, body.provider, body.model, body.api_key)
    except LlmError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    if llm.ai_enabled(db, user.id):
        # a working key: build the semantic index of the last 90 days in the background (owner's choice)
        jobs.enqueue_sync("semantic_backfill", {"user_id": str(user.id)}, dedupe_key=f"semantic:{user.id}")
    return llm.status(db, user.id)


@router.post("/ai/test")
def test_key(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    cred = llm.credential(db, user.id)
    if cred is None:
        raise HTTPException(404, "no API key saved")
    llm.validate(db, cred)
    db.commit()
    return llm.status(db, user.id)


@router.delete("/ai/key", status_code=204)
def remove_key(user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    llm.remove_key(db, user.id)
    db.commit()


@router.get("/usage")
def usage(days: int = 30, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    since = llm._today(db, user.id) - timedelta(days=max(1, min(days, 90)) - 1)
    rows = db.execute(
        select(TokenUsage.day, func.count(), func.sum(TokenUsage.input_tokens), func.sum(TokenUsage.output_tokens))
        .where(TokenUsage.user_id == user.id, TokenUsage.day >= since).group_by(TokenUsage.day).order_by(TokenUsage.day)
    )
    # everyday work (every new mail, searches, rules…) as one line per kind; explicit AI tasks one by one
    auto = db.execute(
        select(TokenUsage.purpose, func.count(), func.sum(TokenUsage.input_tokens + TokenUsage.output_tokens))
        .where(TokenUsage.user_id == user.id, TokenUsage.day >= since, TokenUsage.task_id.is_(None))
        .group_by(TokenUsage.purpose).order_by(func.sum(TokenUsage.input_tokens + TokenUsage.output_tokens).desc()))
    tasks = db.scalars(select(AiTask).where(AiTask.user_id == user.id).order_by(AiTask.created_at.desc()).limit(30))
    return {"days": [{"day": d.isoformat(), "calls": c, "input_tokens": int(i or 0), "output_tokens": int(o or 0)} for d, c, i, o in rows],
            "tokens_today": llm.tokens_today(db, user.id), "daily_token_cap": user_settings.get(db, user.id)["daily_token_cap"],
            "automatic": [{"purpose": p, "label": PURPOSE_LABELS.get(p, p.replace("_", " ").capitalize()), "calls": c, "tokens": int(t or 0)} for p, c, t in auto],
            "tasks": [folder_ai.task_json(db, t) for t in tasks]}


PURPOSE_LABELS = {
    "extract": "Reading each new mail", "embed": "Search by meaning (index)", "search": "Plain-English search",
    "rule": "Plain-English rules", "reply": "AI reply drafts", "sort": "Sorting new mail into subfolders",
    "validate": "Checking your key", "categories": "Custom categories",
}


@router.get("/ai-tasks")
def ai_tasks(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return {"tasks": [folder_ai.task_json(db, t) for t in db.scalars(
        select(AiTask).where(AiTask.user_id == user.id).order_by(AiTask.created_at.desc()).limit(30))]}

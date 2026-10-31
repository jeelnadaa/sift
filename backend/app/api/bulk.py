"""Acting on many conversations at once: POST /api/v1/bulk (see app/bulk.py)."""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app import actions as action_service
from app import bulk
from app.api.mail_actions import _needs_access
from app.db import get_db
from app.models import BulkJob, User
from app.security import current_user

router = APIRouter(prefix="/api/v1")


class MatchIn(BaseModel):
    """Everything a list shows ("Select all N"): the feed or Silenced with its filters, a folder or a group."""
    view: str | None = Field(default=None, pattern="^(feed|silenced)$")
    priority: str | None = Field(default=None, pattern="^(urgent|normal|digest|silent)$")
    account_id: uuid.UUID | None = None
    folder_id: uuid.UUID | None = None
    include_subfolders: bool = False
    group_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _one_list(self):
        if sum(x is not None for x in (self.view, self.folder_id, self.group_id)) != 1:
            raise ValueError("pick one list: view, folder_id or group_id")
        return self


class BulkIn(BaseModel):
    message_ids: list[uuid.UUID] = Field(default_factory=list, max_length=bulk.LIMIT)
    group_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    opportunity_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)  # timelines: the mail on them
    folder_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)  # folders: the mail filed in them
    match: MatchIn | None = None
    action: str = Field(pattern="^(" + "|".join(sorted(bulk.ACTIONS)) + ")$")
    label: str | None = Field(default=None, max_length=225)
    folder_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    until: datetime | None = None
    preview: bool = False  # counts only, for the confirm dialog; nothing changes

    @model_validator(mode="after")
    def _some(self):
        if not (self.message_ids or self.group_ids or self.opportunity_ids or self.folder_ids) and self.match is None:
            raise ValueError("pick at least one mail or group")
        return self

    def params(self) -> dict:
        return {k: v for k, v in {"label": self.label, "folder_id": self.folder_id, "group_id": self.group_id,
                                  "opportunity_id": self.opportunity_id, "until": self.until}.items() if v is not None}


@router.post("/bulk")
def run_bulk(body: BulkIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """One action on many conversations. Gmail changes need write access for every account
    involved (403 code=needs_write_access lists them; nothing changes). Big Gmail changes return a
    job to follow (GET /bulk/jobs/{id}); everything else is done when this returns. `undo` is the
    request that reverses it."""
    from app import events, jobs

    try:
        rows, picked = bulk.resolve(db, user.id, body.message_ids, body.group_ids,
                                    body.match.model_dump(exclude_none=True) if body.match else None, body.opportunity_ids,
                                    body.folder_ids)
        bulk.check(body.action, body.params())
    except bulk.BulkError as exc:
        raise HTTPException(422, str(exc)) from exc
    if body.preview:
        return {"action": body.action, "picked": picked, "conversations": len(rows)}
    try:
        out = bulk.run(db, user.id, rows, body.action, body.params())
    except action_service.NeedsWriteAccess as exc:
        db.rollback()
        raise HTTPException(403, _needs_access(exc).detail) from exc
    except (bulk.BulkError, action_service.ActionError) as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    job = None
    if out.job_id:
        job = db.get(BulkJob, out.job_id)
    events.mail_changed(db, user.id, out.changed)
    if body.action in ("file", "unfile"):
        events.publish(db, user.id, "folders")
    db.commit()
    if job is not None:
        jobs.enqueue_sync("bulk", {"job_id": str(job.id)}, dedupe_key=f"bulk:{job.id}")
    return {"action": body.action, "picked": picked, "conversations": out.conversations, "changed": len(out.changed),
            "failed_accounts": out.failed_accounts, "sift_only": out.sift_only,
            "job": bulk.job_json(job) if job else None, "undo": bulk.undo_of(out, body.params())}


@router.get("/bulk/jobs/{job_id}")
def bulk_job(job_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    job = db.get(BulkJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(404, "job not found")
    return bulk.job_json(job)

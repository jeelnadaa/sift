"""Reply templates (canned replies) API router."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import templates as template_service
from app.db import get_db
from app.models import User
from app.security import current_user

router = APIRouter(prefix="/api/v1/templates", tags=["templates"])


class TemplateIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    body: str = Field(..., min_length=1)
    shortcut: str | None = Field(default=None, max_length=32)


class TemplatePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    body: str | None = Field(default=None, min_length=1)
    shortcut: str | None = Field(default=None, max_length=32)


@router.get("")
def list_templates(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """List all reply templates belonging to the current user."""
    items = template_service.list_templates(db, user.id)
    return {
        "templates": [template_service.template_json(t) for t in items],
        "total": len(items),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_template(
    payload: TemplateIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Create a new reply template."""
    template = template_service.create_template(
        db=db,
        user_id=user.id,
        title=payload.title,
        body=payload.body,
        shortcut=payload.shortcut,
    )
    return template_service.template_json(template)


@router.get("/{template_id}")
def get_template(
    template_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Get a single reply template."""
    template = template_service.get_template(db, user.id, template_id)
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return template_service.template_json(template)


@router.patch("/{template_id}")
def update_template(
    template_id: uuid.UUID,
    payload: TemplatePatch,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Update a reply template."""
    template = template_service.update_template(
        db=db,
        user_id=user.id,
        template_id=template_id,
        title=payload.title,
        body=payload.body,
        shortcut=payload.shortcut,
    )
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return template_service.template_json(template)


@router.delete("/{template_id}")
def delete_template(
    template_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Delete a reply template."""
    deleted = template_service.delete_template(db, user.id, template_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return {"ok": True}

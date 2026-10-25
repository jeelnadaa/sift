"""Reply templates (canned replies) service layer."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ReplyTemplate


def list_templates(db: Session, user_id: uuid.UUID) -> list[ReplyTemplate]:
    """List all reply templates for the user, ordered by title."""
    return list(
        db.scalars(
            select(ReplyTemplate)
            .where(ReplyTemplate.user_id == user_id)
            .order_by(ReplyTemplate.title.asc())
        ).all()
    )


def get_template(db: Session, user_id: uuid.UUID, template_id: uuid.UUID) -> ReplyTemplate | None:
    """Fetch a single template by ID ensuring user ownership."""
    return db.scalar(
        select(ReplyTemplate).where(
            ReplyTemplate.id == template_id,
            ReplyTemplate.user_id == user_id,
        )
    )


def create_template(
    db: Session,
    user_id: uuid.UUID,
    title: str,
    body: str,
    shortcut: str | None = None,
) -> ReplyTemplate:
    """Create a new reply template for the user."""
    clean_title = title.strip()
    clean_body = body.strip()
    clean_shortcut = shortcut.strip().lower() if shortcut and shortcut.strip() else None
    if clean_shortcut and not clean_shortcut.startswith("/"):
        clean_shortcut = f"/{clean_shortcut}"

    template = ReplyTemplate(
        user_id=user_id,
        title=clean_title,
        body=clean_body,
        shortcut=clean_shortcut,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def update_template(
    db: Session,
    user_id: uuid.UUID,
    template_id: uuid.UUID,
    title: str | None = None,
    body: str | None = None,
    shortcut: str | None = None,
) -> ReplyTemplate | None:
    """Update an existing template ensuring user ownership."""
    template = get_template(db, user_id, template_id)
    if not template:
        return None

    if title is not None:
        template.title = title.strip()
    if body is not None:
        template.body = body.strip()
    if shortcut is not None:
        clean_shortcut = shortcut.strip().lower() if shortcut.strip() else None
        if clean_shortcut and not clean_shortcut.startswith("/"):
            clean_shortcut = f"/{clean_shortcut}"
        template.shortcut = clean_shortcut

    db.commit()
    db.refresh(template)
    return template


def delete_template(db: Session, user_id: uuid.UUID, template_id: uuid.UUID) -> bool:
    """Delete a template ensuring user ownership."""
    template = get_template(db, user_id, template_id)
    if not template:
        return False
    db.delete(template)
    db.commit()
    return True


def template_json(t: ReplyTemplate) -> dict[str, Any]:
    """Serialize a reply template to a JSON dict."""
    return {
        "id": str(t.id),
        "title": t.title,
        "body": t.body,
        "shortcut": t.shortcut,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }

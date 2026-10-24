"""Per-user settings (and per-account overrides) stored as JSON in `settings`, with defaults."""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Setting

DEFAULTS: dict = {
    "timezone": "Asia/Kolkata",
    "daily_token_cap": 50000,
    "resend_urgent": True,
    "resend_after_minutes": 5,
    "resend_limit": 3,
    "grouping_enabled": "not_asked",  # brief section 21
}
EDITABLE = {
    "timezone": str,
    "daily_token_cap": int,
    "resend_urgent": bool,
    "resend_after_minutes": int,
    "resend_limit": int,
}


def _row(db: Session, user_id: uuid.UUID, account_id: uuid.UUID | None = None) -> Setting | None:
    q = select(Setting).where(Setting.user_id == user_id)
    q = q.where(Setting.account_id == account_id) if account_id else q.where(Setting.account_id.is_(None))
    return db.scalar(q)


def get(db: Session, user_id: uuid.UUID, account_id: uuid.UUID | None = None) -> dict:
    """User settings, overlaid with the account's overrides when account_id is given."""
    data = dict(DEFAULTS)
    row = _row(db, user_id)
    if row:
        data.update(row.data)
    if account_id:
        acc = _row(db, user_id, account_id)
        if acc:
            data.update(acc.data)
    return data


def update(db: Session, user_id: uuid.UUID, changes: dict, account_id: uuid.UUID | None = None) -> dict:
    clean = {}
    for k, v in changes.items():
        if k not in EDITABLE:
            raise ValueError(f"unknown setting {k}")
        clean[k] = EDITABLE[k](v)
    row = _row(db, user_id, account_id)
    if row is None:
        row = Setting(user_id=user_id, account_id=account_id, data={})
        db.add(row)
    row.data = {**row.data, **clean}
    db.flush()
    return get(db, user_id, account_id)

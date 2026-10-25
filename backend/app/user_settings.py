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
    # Remote images in mail load automatically, always through Sift's image proxy (owner, 2026-10-24).
    "load_remote_images": True,
    # Writing mail (Phase 4): the name shown to recipients, a signature added to new mail, and
    # how long "Undo" stays available after Send (0 sends at once).
    "sender_name": "",
    "signature": "",
    "undo_send_seconds": 10,
    # The AI provider's limits per key (Gemini free tier); Sift paces its calls under them.
    "ai_requests_per_minute": 15,
    "ai_requests_per_day": 500,
    "ai_tokens_per_minute": 250000,
}
EDITABLE = {
    "timezone": str,
    "daily_token_cap": int,
    "resend_urgent": bool,
    "resend_after_minutes": int,
    "resend_limit": int,
    "load_remote_images": bool,
    "sender_name": str,
    "signature": str,
    "undo_send_seconds": int,
    "ai_requests_per_minute": int,
    "ai_requests_per_day": int,
    "ai_tokens_per_minute": int,
}
MAX_LENGTH = {"sender_name": 100, "signature": 2000, "timezone": 64}

# Allowed ranges for numbers (a phone or browser can send anything).
RANGES = {
    "daily_token_cap": (0, 10_000_000),
    "resend_after_minutes": (1, 60),
    "resend_limit": (0, 10),
    "undo_send_seconds": (0, 30),
    "ai_requests_per_minute": (1, 2000),
    "ai_requests_per_day": (1, 100_000),
    "ai_tokens_per_minute": (1000, 10_000_000),
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
        if EDITABLE[k] is bool and not isinstance(v, bool):
            raise ValueError(f"{k} must be true or false")
        clean[k] = EDITABLE[k](v)
        if EDITABLE[k] is str:
            if not isinstance(v, str):
                raise ValueError(f"{k} must be text")
            clean[k] = v.strip() if k != "signature" else v.replace("\r\n", "\n").strip("\n")
            if k == "sender_name" and any(c in clean[k] for c in "\r\n<>\""):
                raise ValueError("sender_name can't contain line breaks, quotes or < >")
            if len(clean[k]) > MAX_LENGTH.get(k, 500):
                raise ValueError(f"{k} is too long")
        if k in RANGES and not RANGES[k][0] <= clean[k] <= RANGES[k][1]:
            lo, hi = RANGES[k]
            raise ValueError(f"{k} must be between {lo:,} and {hi:,}")
    row = _row(db, user_id, account_id)
    if row is None:
        row = Setting(user_id=user_id, account_id=account_id, data={})
        db.add(row)
    row.data = {**row.data, **clean}
    db.flush()
    return get(db, user_id, account_id)

"""Per-user settings (and per-account overrides) stored as JSON in `settings`, with defaults."""
import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

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
    "quiet_hours_enabled": False,
    "quiet_hours_start": "22:00",
    "quiet_hours_end": "07:00",
    "muted_categories": [],
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
    "quiet_hours_enabled": bool,
    "quiet_hours_start": str,
    "quiet_hours_end": str,
    "muted_categories": list,
}
MAX_LENGTH = {
    "sender_name": 100,
    "signature": 2000,
    "timezone": 64,
    "quiet_hours_start": 5,
    "quiet_hours_end": 5,
}

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
        if EDITABLE[k] is bool:
            if not isinstance(v, bool):
                raise ValueError(f"{k} must be true or false")
            clean[k] = bool(v)
            continue
        if EDITABLE[k] is list:
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                raise ValueError(f"{k} must be a list of strings")
            clean[k] = [x.strip() for x in v if x.strip()]
            continue
        if EDITABLE[k] is int and (isinstance(v, bool) or not isinstance(v, (int, float))):
            raise ValueError(f"{k} must be a number")
        clean[k] = EDITABLE[k](v)
        if EDITABLE[k] is str:
            if not isinstance(v, str):
                raise ValueError(f"{k} must be text")
            clean[k] = v.strip() if k != "signature" else v.replace("\r\n", "\n").strip("\n")
            if k in ("quiet_hours_start", "quiet_hours_end"):
                parts = clean[k].split(":")
                if len(parts) != 2 or not all(p.isdigit() for p in parts):
                    raise ValueError(f"{k} must be HH:MM")
                h, m = int(parts[0]), int(parts[1])
                if not (0 <= h <= 23 and 0 <= m <= 59):
                    raise ValueError(f"{k} must be valid time (00:00 to 23:59)")
                clean[k] = f"{h:02d}:{m:02d}"
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


def is_in_quiet_hours(settings: dict, now_utc: datetime | None = None) -> bool:
    """True if current time in user's timezone falls within enabled quiet hours."""
    if not settings.get("quiet_hours_enabled"):
        return False
    start_str = settings.get("quiet_hours_start", "22:00")
    end_str = settings.get("quiet_hours_end", "07:00")
    if start_str == end_str:
        return False
    try:
        sh, sm = map(int, start_str.split(":"))
        eh, em = map(int, end_str.split(":"))
    except (ValueError, TypeError):
        return False

    tz_name = settings.get("timezone", "Asia/Kolkata")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")

    now = (now_utc or datetime.now(UTC)).astimezone(tz)
    cur_mins = now.hour * 60 + now.minute
    start_mins = sh * 60 + sm
    end_mins = eh * 60 + em

    if start_mins < end_mins:
        return start_mins <= cur_mins < end_mins
    else:
        return cur_mins >= start_mins or cur_mins < end_mins

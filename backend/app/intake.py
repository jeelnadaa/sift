"""Mail-check health (after the 2026-10-24 incident, when every check failed for ~5 hours and
nothing said so).

- Every check records its outcome on the account: `last_check_ok_at` on success;
  `check_failing_since` + a short reason (error type and HTTP status only) on failure.
- The scheduler runs `watch()` itself every minute (not as a queued job, so it still works when
  the worker is down): an account whose checks have failed, or that hasn't been checked at all,
  for STALL_AFTER gets one alert notification; when checks succeed again the user is told it
  recovered (mail that arrived meanwhile is caught up automatically).
- `stalled()` feeds the app's warning banner and /health.
"""
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import notify
from app.db import get_sessionmaker
from app.models import GmailAccount

log = logging.getLogger(__name__)
STALL_AFTER = timedelta(minutes=15)


def _reason(exc: BaseException) -> str:
    status = getattr(exc, "status", None)
    return f"{type(exc).__name__}{f' {status}' if status else ''}"[:200]


def record_ok(db: Session, account: GmailAccount) -> None:
    """Called inside a successful check (same transaction)."""
    recovered = account.intake_alerted_at is not None
    account.last_check_ok_at = datetime.now(UTC)
    account.check_failing_since = None
    account.last_check_error = None
    if recovered:
        account.intake_alerted_at = None
        notify.send_system(db, account.user_id, "Sift is checking mail again",
                           f"{account.email} is back. Mail that arrived meanwhile has been caught up.")


def record_failure(account_id: uuid.UUID | str, exc: BaseException) -> None:
    """Called when a check failed, in its own session (the check's may be unusable)."""
    try:
        with get_sessionmaker()() as db:
            a = db.get(GmailAccount, uuid.UUID(str(account_id)))
            if a is None:
                return
            a.check_failing_since = a.check_failing_since or datetime.now(UTC)
            a.last_check_error = _reason(exc)
            db.commit()
    except Exception:
        log.exception("could not record a failed check")


def _watched(db: Session):
    return select(GmailAccount).where(GmailAccount.status == "active", GmailAccount.encrypted_refresh_token.is_not(None))


def stalled(db: Session, user_id: uuid.UUID | None = None, now: datetime | None = None) -> list[GmailAccount]:
    now = now or datetime.now(UTC)
    limit = now - STALL_AFTER
    q = _watched(db).where(or_(GmailAccount.check_failing_since <= limit,
                               GmailAccount.last_check_ok_at <= limit,
                               GmailAccount.last_check_ok_at.is_(None) & (GmailAccount.created_at <= limit)))
    if user_id is not None:
        q = q.where(GmailAccount.user_id == user_id)
    return list(db.scalars(q))


def watch(now: datetime | None = None) -> int:
    """Alert once per stall. Returns how many alerts were sent."""
    sent = 0
    with get_sessionmaker()() as db:
        for a in stalled(db, now=now):
            if a.intake_alerted_at is not None:
                continue
            since = a.check_failing_since or a.last_check_ok_at
            when = since.astimezone().strftime("%H:%M") if since else "a while"
            notify.send_system(db, a.user_id, "Sift can't check your mail",
                               f"{a.email} hasn't been checked since {when}. Sift keeps retrying and will catch up on its own.")
            a.intake_alerted_at = now or datetime.now(UTC)
            sent += 1
            log.warning("mail checks stalled for account %s (%s)", a.id, a.last_check_error or "no check ran")
        db.commit()
    return sent


def health_json(a: GmailAccount, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    stalled_now = a.status == "active" and a.encrypted_refresh_token is not None and (
        (a.check_failing_since is not None and a.check_failing_since <= now - STALL_AFTER)
        or (a.last_check_ok_at is not None and a.last_check_ok_at <= now - STALL_AFTER))
    return {"last_check_ok_at": a.last_check_ok_at.isoformat() if a.last_check_ok_at else None,
            "check_failing_since": a.check_failing_since.isoformat() if a.check_failing_since else None,
            "last_check_error": a.last_check_error, "stalled": bool(stalled_now)}

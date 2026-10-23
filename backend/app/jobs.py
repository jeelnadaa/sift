"""Background job handlers and the queue that feeds them.

Two queue backends, chosen by QUEUE_BACKEND:
- redis: arq (default host with Redis).
- postgres: the `jobs` table polled with FOR UPDATE SKIP LOCKED (1 GB fallback host).

Handlers are plain functions taking (payload: dict) so both backends share them.
"""
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_sessionmaker
from app.models import GmailAccount, Job

log = logging.getLogger(__name__)


# ---- handlers ---------------------------------------------------------------

def handle_gmail_push(payload: dict) -> None:
    """Push mode: Pub/Sub says this mailbox changed. Route by address, then check it."""
    from app.accounts import check_account

    with get_sessionmaker()() as db:
        account_id = db.scalar(select(GmailAccount.id).where(GmailAccount.email == payload["email"]))
    if account_id is None:
        log.info("pubsub push for unknown account (history %s)", payload["history_id"])
        return
    log.info("pubsub push routed to account %s (history %s)", account_id, payload["history_id"])
    check_account(account_id)


def handle_check_account(payload: dict) -> None:
    from app.accounts import check_account

    check_account(payload["account_id"])


def handle_renew_watches(payload: dict) -> None:
    from app.accounts import renew_watches

    log.info("renewed %d gmail watch(es)", renew_watches())


HANDLERS = {
    "gmail_push": handle_gmail_push,
    "check_account": handle_check_account,
    "renew_watches": handle_renew_watches,
}


# ---- enqueue ---------------------------------------------------------------

async def enqueue(kind: str, payload: dict, dedupe_key: str | None = None) -> None:
    if get_settings().queue_backend == "redis":
        await _enqueue_redis(kind, payload, dedupe_key)
    else:
        with get_sessionmaker()() as db:
            enqueue_pg(db, kind, payload, dedupe_key)
            db.commit()


_redis_pool = None


async def _enqueue_redis(kind: str, payload: dict, dedupe_key: str | None) -> None:
    global _redis_pool
    from arq import create_pool
    from arq.connections import RedisSettings

    if _redis_pool is None:
        _redis_pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    # arq skips a job whose _job_id is queued or running (results are not kept, see worker.py).
    await _redis_pool.enqueue_job("run_job", kind, payload, _job_id=dedupe_key)


def enqueue_pg(db: Session, kind: str, payload: dict, dedupe_key: str | None = None) -> None:
    """A job with the same dedupe_key is skipped only while one is still queued or running."""
    stmt = insert(Job).values(kind=kind, payload=payload, dedupe_key=dedupe_key)
    db.execute(stmt.on_conflict_do_nothing(index_elements=["dedupe_key"], index_where=text("status IN ('queued', 'running')")))


# ---- postgres worker ---------------------------------------------------------

MAX_ATTEMPTS = 5


def claim_next(db: Session) -> Job | None:
    """Lock one ready job. Stale 'running' jobs (worker crashed) are reclaimed after 10 minutes."""
    stale = datetime.now(UTC) - timedelta(minutes=10)
    row = db.execute(
        text(
            """
            SELECT id FROM jobs
            WHERE (status = 'queued' AND run_at <= now())
               OR (status = 'running' AND locked_at < :stale)
            ORDER BY run_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        ),
        {"stale": stale},
    ).first()
    if row is None:
        return None
    db.execute(update(Job).where(Job.id == row.id).values(status="running", locked_at=datetime.now(UTC), attempts=Job.attempts + 1))
    db.commit()
    return db.get(Job, row.id)


def run_one(db: Session) -> bool:
    job = claim_next(db)
    if job is None:
        return False
    try:
        HANDLERS[job.kind](job.payload)
        job.status, job.last_error = "done", None
    except Exception as exc:
        log.exception("job %s (%s) failed", job.id, job.kind)
        job.last_error = f"{type(exc).__name__}: {exc}"[:500]
        if job.attempts >= MAX_ATTEMPTS:
            job.status = "failed"
        else:
            job.status = "queued"
            job.run_at = datetime.now(UTC) + timedelta(seconds=2 ** job.attempts * 5)
    db.commit()
    return True


def cleanup_finished(db: Session, older_than: timedelta = timedelta(days=1)) -> int:
    """Poll mode creates a job per account every few seconds; drop finished ones."""
    result = db.execute(text("DELETE FROM jobs WHERE status IN ('done', 'failed') AND created_at < :cut"), {"cut": datetime.now(UTC) - older_than})
    db.commit()
    return result.rowcount

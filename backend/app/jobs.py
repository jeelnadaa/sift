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
    """Phase 0: route the push to its account and record that it arrived.
    Phase 1 replaces the body with history.list + the processing pipeline."""
    email = payload["email"]
    with get_sessionmaker()() as db:
        account = db.scalar(select(GmailAccount).where(GmailAccount.email == email))
    if account is None:
        log.info("pubsub push for unknown account (history %s)", payload["history_id"])
        return
    log.info("pubsub push routed to account %s (history %s)", account.id, payload["history_id"])


HANDLERS = {"gmail_push": handle_gmail_push}


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
    # arq skips a job whose _job_id already exists, which dedupes Pub/Sub redeliveries.
    await _redis_pool.enqueue_job("run_job", kind, payload, _job_id=dedupe_key)


def enqueue_pg(db: Session, kind: str, payload: dict, dedupe_key: str | None = None) -> None:
    stmt = insert(Job).values(kind=kind, payload=payload, dedupe_key=dedupe_key)
    db.execute(stmt.on_conflict_do_nothing(index_elements=["dedupe_key"]))


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

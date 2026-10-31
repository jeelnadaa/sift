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
    check_account(account_id, "push")


def handle_check_account(payload: dict) -> None:
    from app.accounts import check_account

    check_account(payload["account_id"], payload.get("source", "poll"))


def handle_renew_watches(payload: dict) -> None:
    from app.accounts import renew_watches

    log.info("renewed %d gmail watch(es)", renew_watches())


def handle_resend_notifications(payload: dict) -> None:
    from app.notify import resend_unacknowledged

    with get_sessionmaker()() as db:
        n = resend_unacknowledged(db)
    if n:
        log.info("re-sent %d unacknowledged urgent notification(s)", n)


def handle_send_reminders(payload: dict) -> None:
    from app.todos import send_due

    with get_sessionmaker()() as db:
        n = send_due(db)
    if n:
        log.info("sent %d reminder(s)", n)


def handle_onboarding_scan(payload: dict) -> None:
    from app.scan import run

    run(payload["scan_id"])


def handle_grouping_backfill(payload: dict) -> None:
    import uuid

    from app.grouping import backfill

    with get_sessionmaker()() as db:
        n = backfill(db, uuid.UUID(payload["user_id"]))
        db.commit()
    log.info("grouping backfill grouped %d mail(s)", n)


def handle_semantic_backfill(payload: dict) -> None:
    import uuid

    from app.search.semantic import backfill

    with get_sessionmaker()() as db:
        n = backfill(db, uuid.UUID(payload["user_id"]))
    log.info("semantic index: %d mail(s) added", n)


def handle_wake_snoozes(payload: dict) -> None:
    from app.snooze import wake_due

    with get_sessionmaker()() as db:
        n = wake_due(db)
    if n:
        log.info("woke %d snoozed conversation(s)", n)


def handle_send_outbox(payload: dict) -> None:
    from app.outbox import send_due

    n = send_due()
    if n:
        log.info("sent %d mail(s) from the outbox", n)


def handle_follow_ups(payload: dict) -> None:
    from app.outbox import remind_due

    with get_sessionmaker()() as db:
        n = remind_due(db)
    if n:
        log.info("sent %d follow-up reminder(s)", n)


def handle_ai_task(payload: dict) -> None:
    import uuid

    from app.folder_ai import run_task

    run_task(uuid.UUID(payload["task_id"]))


def handle_bulk(payload: dict) -> None:
    import uuid

    from app.bulk import run_job

    run_job(uuid.UUID(payload["job_id"]))


def handle_catch_up(payload: dict) -> None:
    from datetime import datetime

    from app.accounts import catch_up

    catch_up(payload["account_id"], datetime.fromisoformat(payload["since"]), payload.get("mode", "live"))


HANDLERS = {
    "bulk": handle_bulk,
    "catch_up": handle_catch_up,
    "ai_task": handle_ai_task,
    "send_outbox": handle_send_outbox,
    "follow_ups": handle_follow_ups,
    "wake_snoozes": handle_wake_snoozes,
    "semantic_backfill": handle_semantic_backfill,
    "grouping_backfill": handle_grouping_backfill,
    "onboarding_scan": handle_onboarding_scan,
    "send_reminders": handle_send_reminders,
    "resend_notifications": handle_resend_notifications,
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


def enqueue_sync(kind: str, payload: dict, dedupe_key: str | None = None) -> None:
    """For synchronous callers (e.g. request handlers that are plain functions)."""
    import asyncio

    if get_settings().queue_backend == "redis":
        asyncio.run(_enqueue_redis(kind, payload, dedupe_key))
    else:
        with get_sessionmaker()() as db:
            enqueue_pg(db, kind, payload, dedupe_key)
            db.commit()


def enqueue_pg(db: Session, kind: str, payload: dict, dedupe_key: str | None = None) -> None:
    """A job with the same dedupe_key is skipped only while one is still queued or running."""
    stmt = insert(Job).values(kind=kind, payload=payload, dedupe_key=dedupe_key)
    db.execute(stmt.on_conflict_do_nothing(index_elements=["dedupe_key"], index_where=text("status IN ('queued', 'running')")))


# ---- postgres worker ---------------------------------------------------------

MAX_ATTEMPTS = 5
# Quick jobs: the worker keeps one lane for these only, so a long job (a scan, an AI task) can
# never hold up new mail, sending or reminders.
FAST_KINDS = ("check_account", "gmail_push", "send_outbox", "resend_notifications", "send_reminders",
              "wake_snoozes", "follow_ups", "renew_watches")
# Long jobs may run for many minutes; only after LONG_STALE are they taken to have crashed.
LONG_KINDS = ("catch_up", "onboarding_scan", "semantic_backfill", "grouping_backfill", "ai_task", "bulk")
STALE = timedelta(minutes=10)
LONG_STALE = timedelta(hours=2)


def claim_next(db: Session, kinds: tuple[str, ...] | None = None) -> Job | None:
    """Lock one ready job (of `kinds`, or any). A 'running' job whose worker crashed is reclaimed
    after STALE (LONG_STALE for long kinds)."""
    now = datetime.now(UTC)
    row = db.execute(
        text(
            """
            SELECT id FROM jobs
            WHERE ((status = 'queued' AND run_at <= now())
                OR (status = 'running' AND locked_at < :stale AND NOT (kind = ANY(:long)))
                OR (status = 'running' AND locked_at < :stale_long AND kind = ANY(:long)))
              AND (CAST(:any_kind AS boolean) OR kind = ANY(:kinds))
            ORDER BY run_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        ),
        {"stale": now - STALE, "stale_long": now - LONG_STALE, "long": list(LONG_KINDS),
         "any_kind": kinds is None, "kinds": list(kinds or ())},
    ).first()
    if row is None:
        return None
    db.execute(update(Job).where(Job.id == row.id).values(status="running", locked_at=datetime.now(UTC), attempts=Job.attempts + 1))
    db.commit()
    return db.get(Job, row.id)


def run_one(db: Session, kinds: tuple[str, ...] | None = None) -> bool:
    job = claim_next(db, kinds)
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

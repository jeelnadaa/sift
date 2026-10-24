"""Worker entrypoint: `python -m app.worker`. Uses the backend chosen by QUEUE_BACKEND."""
import asyncio
import logging
import threading
import time

from app.config import get_settings, setup_logging
from app.jobs import HANDLERS, run_one

log = logging.getLogger("app.worker")


async def run_job(ctx: dict, kind: str, payload: dict) -> None:
    # handlers are blocking; in a thread they don't stop arq from running other jobs meanwhile
    await asyncio.to_thread(HANDLERS[kind], payload)


class WorkerSettings:
    """arq settings (redis backend)."""
    functions = [run_job]
    max_tries = 5
    max_jobs = 4
    job_timeout = 2 * 3600  # onboarding scans and AI tasks can take a while
    keep_result = 0  # lets the same _job_id (check:<account>) be enqueued again right after it finishes
    redis_settings = None  # set in main() from REDIS_URL


GENERAL_LANES = 2


def _lane(name: str, kinds: tuple[str, ...] | None, poll_seconds: float) -> None:
    from app.db import get_sessionmaker

    while True:
        try:
            with get_sessionmaker()() as db:
                worked = run_one(db, kinds)
        except Exception:  # noqa: BLE001  (database restarting…): keep the lane alive
            log.exception("worker lane %s: claiming a job failed; retrying", name)
            worked = False
            time.sleep(5)
        if not worked:
            time.sleep(poll_seconds)


def run_postgres_worker(poll_seconds: float = 1.0) -> None:
    """One lane for quick jobs only (new mail, sending, reminders) and GENERAL_LANES for anything,
    so a long job never holds up new mail. Jobs are claimed with SKIP LOCKED, so lanes never take
    the same job; per-user work is serialized by app.locks."""
    from app.jobs import FAST_KINDS

    log.info("postgres worker started: 1 quick lane + %d general lanes", GENERAL_LANES)
    lanes = [threading.Thread(target=_lane, args=("quick", FAST_KINDS, poll_seconds), daemon=True, name="lane-quick")]
    lanes += [threading.Thread(target=_lane, args=(f"general-{i}", None, poll_seconds), daemon=True, name=f"lane-{i}") for i in range(GENERAL_LANES)]
    for t in lanes:
        t.start()
    while all(t.is_alive() for t in lanes):
        time.sleep(5)
    raise SystemExit("a worker lane stopped")  # the supervisor (or Docker) restarts the worker


def main() -> None:
    settings = get_settings()
    setup_logging()
    if settings.queue_backend == "redis":
        from arq.connections import RedisSettings
        from arq.worker import run_worker

        WorkerSettings.redis_settings = RedisSettings.from_dsn(settings.redis_url)
        run_worker(WorkerSettings)
    else:
        run_postgres_worker()


if __name__ == "__main__":
    main()

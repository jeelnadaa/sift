"""Scheduler: `python -m app.scheduler`. One instance per deployment.

- Poll mode: every POLL_INTERVAL_SECONDS, queue a check of each active account.
- Push mode: Pub/Sub triggers checks; we still queue a safety check every 5 minutes
  (covers a push that arrived mid-check, and downtime) and renew Gmail watches daily.
- Both: catch up all accounts at startup; prune finished jobs hourly (Postgres queue).
Checks are deduped per account, so a slow check never piles up duplicates.
"""
import asyncio
import logging
import time

from app import jobs
from app.accounts import active_account_ids
from app.config import get_settings
from app.db import get_sessionmaker

log = logging.getLogger("app.scheduler")
PUSH_SAFETY_INTERVAL = 300
HOUR = 3600


def check_interval() -> int:
    s = get_settings()
    return max(s.poll_interval_seconds, 2) if s.change_detection == "poll" else PUSH_SAFETY_INTERVAL


async def queue_checks() -> int:
    with get_sessionmaker()() as db:
        ids = active_account_ids(db)
    for account_id in ids:
        await jobs.enqueue("check_account", {"account_id": str(account_id)}, dedupe_key=f"check:{account_id}")
    return len(ids)


async def hourly() -> None:
    s = get_settings()
    if s.change_detection == "push":
        await jobs.enqueue("renew_watches", {}, dedupe_key="renew_watches")
    if s.queue_backend == "postgres":
        with get_sessionmaker()() as db:
            jobs.cleanup_finished(db)


async def run() -> None:
    s = get_settings()
    log.info("scheduler started: mode=%s interval=%ss queue=%s", s.change_detection, check_interval(), s.queue_backend)
    last_hourly = 0.0
    while True:
        started = time.monotonic()
        try:
            await queue_checks()
            if started - last_hourly >= HOUR or last_hourly == 0.0:
                await hourly()
                last_hourly = started
        except Exception:
            log.exception("scheduler tick failed")  # keep ticking; the next tick retries
        await asyncio.sleep(max(0.0, check_interval() - (time.monotonic() - started)))


def main() -> None:
    logging.basicConfig(level=get_settings().log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()

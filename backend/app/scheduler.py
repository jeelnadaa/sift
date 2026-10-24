"""Scheduler: `python -m app.scheduler`. One instance per deployment.

- Poll mode: every POLL_INTERVAL_SECONDS, queue a check of each active account.
- Push mode: Pub/Sub triggers checks. Each account with a working Gmail watch still gets a
  safety check every 5 minutes (covers a push lost in transit, and downtime). An account
  WITHOUT a working watch (never started, expired, or marked broken because a safety check
  found mail that push never announced) is polled every POLL_INTERVAL_SECONDS, so losing
  Pub/Sub (e.g. the Google Cloud free trial ending) degrades to poll speed, never worse.
  Watches are (re)started hourly when missing or due within a day.
- Both: catch up all accounts at startup; every minute re-send unacknowledged urgent notifications
  and send due deadline reminders; prune finished jobs hourly (Postgres queue).
Checks are deduped per account, so a slow check never piles up duplicates.
"""
import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app import jobs
from app.config import get_settings, setup_logging
from app.db import get_sessionmaker
from app.models import GmailAccount

log = logging.getLogger("app.scheduler")
PUSH_SAFETY_INTERVAL = 300
HOUR = 3600
MINUTE = 60

_last_safety: dict[uuid.UUID, float] = {}  # account id -> monotonic time of the last safety check


def tick_interval() -> int:
    return max(get_settings().poll_interval_seconds, 2)


def _accounts() -> list[tuple[uuid.UUID, datetime | None]]:
    with get_sessionmaker()() as db:
        rows = db.execute(
            select(GmailAccount.id, GmailAccount.watch_expires_at)
            .where(GmailAccount.status == "active", GmailAccount.encrypted_refresh_token.is_not(None))
        )
        return [(r.id, r.watch_expires_at) for r in rows]


def plan_checks(accounts: list[tuple[uuid.UUID, datetime | None]], push: bool, now_mono: float, now: datetime) -> list[tuple[uuid.UUID, str]]:
    """Which accounts to check this tick, and why ("poll" or "safety"). Pure, for tests."""
    due = []
    for account_id, watch_expires_at in accounts:
        if not push or watch_expires_at is None or watch_expires_at <= now:
            due.append((account_id, "poll"))
        elif now_mono - _last_safety.get(account_id, float("-inf")) >= PUSH_SAFETY_INTERVAL:
            due.append((account_id, "safety"))
    return due


async def queue_checks() -> int:
    push = get_settings().change_detection == "push"
    now_mono = time.monotonic()
    due = plan_checks(_accounts(), push, now_mono, datetime.now(UTC))
    for account_id, source in due:
        await jobs.enqueue("check_account", {"account_id": str(account_id), "source": source}, dedupe_key=f"check:{account_id}")
        if source == "safety":
            _last_safety[account_id] = now_mono
    return len(due)


async def hourly() -> None:
    s = get_settings()
    if s.change_detection == "push":
        await jobs.enqueue("renew_watches", {}, dedupe_key="renew_watches")
    if s.queue_backend == "postgres":
        with get_sessionmaker()() as db:
            jobs.cleanup_finished(db)


async def run() -> None:
    s = get_settings()
    log.info("scheduler started: mode=%s tick=%ss queue=%s", s.change_detection, tick_interval(), s.queue_backend)
    last_hourly = last_minute = 0.0
    while True:
        started = time.monotonic()
        try:
            await queue_checks()
            if started - last_minute >= MINUTE or last_minute == 0.0:
                await jobs.enqueue("resend_notifications", {}, dedupe_key="resend_notifications")
                await jobs.enqueue("send_reminders", {}, dedupe_key="send_reminders")
                last_minute = started
            if started - last_hourly >= HOUR or last_hourly == 0.0:
                await hourly()
                last_hourly = started
        except Exception:
            log.exception("scheduler tick failed")  # keep ticking; the next tick retries
        await asyncio.sleep(max(0.0, tick_interval() - (time.monotonic() - started)))


def main() -> None:
    setup_logging()
    asyncio.run(run())


if __name__ == "__main__":
    main()

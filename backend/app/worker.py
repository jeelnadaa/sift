"""Worker entrypoint: `python -m app.worker`. Uses the backend chosen by QUEUE_BACKEND."""
import logging
import time

from app.config import get_settings
from app.jobs import HANDLERS, run_one

log = logging.getLogger("app.worker")


async def run_job(ctx: dict, kind: str, payload: dict) -> None:
    HANDLERS[kind](payload)


class WorkerSettings:
    """arq settings (redis backend)."""
    functions = [run_job]
    max_tries = 5
    redis_settings = None  # set in main() from REDIS_URL


def run_postgres_worker(poll_seconds: float = 1.0) -> None:
    from app.db import get_sessionmaker

    log.info("postgres worker started")
    while True:
        with get_sessionmaker()() as db:
            worked = run_one(db)
        if not worked:
            time.sleep(poll_seconds)


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if settings.queue_backend == "redis":
        from arq.connections import RedisSettings
        from arq.worker import run_worker

        WorkerSettings.redis_settings = RedisSettings.from_dsn(settings.redis_url)
        run_worker(WorkerSettings)
    else:
        run_postgres_worker()


if __name__ == "__main__":
    main()

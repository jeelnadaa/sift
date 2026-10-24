"""Per-user serialization of mail processing.

The worker runs jobs side by side (see app.jobs lanes), so two accounts of one user, or a mail
check and an AI task, could otherwise process mail for the same user at the same moment and
race on what they create (a company timeline, a subfolder, a group). `user_lock` makes them
take turns, one mail at a time: it is held only while one mail is processed, so waits are short.

It is a Postgres session-level advisory lock on its own connection (not the caller's session,
whose connection may change between transactions). If the process dies, the connection closes
and Postgres releases the lock.
"""
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text

from app.db import get_engine


class LockBusy(RuntimeError):
    pass


@contextmanager
def user_lock(user_id: uuid.UUID | str, wait_seconds: float = 120.0) -> Iterator[None]:
    key = f"user-mail:{user_id}"
    with get_engine().connect() as conn:
        deadline = time.monotonic() + wait_seconds
        while not conn.execute(text("SELECT pg_try_advisory_lock(hashtext(:k))"), {"k": key}).scalar():
            conn.rollback()
            if time.monotonic() > deadline:
                raise LockBusy(f"mail processing for user {user_id} is busy")
            time.sleep(0.2)
        conn.commit()
        try:
            yield
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": key})
            conn.commit()

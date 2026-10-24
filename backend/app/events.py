"""Live updates: tell every open app of a user that something changed, so read state, new mail
and filing show up on the other devices without reloading.

- `publish(db, user_id, kind, **data)` queues an event on the session. It goes out only when
  that transaction commits (never for work that was rolled back), as:
  * a Postgres NOTIFY on CHANNEL, which each API process fans out to its open web streams
    (`/api/v1/events`, server-sent events); works across api/worker/scheduler processes;
  * a silent FCM data message `{"type": "sync"}` to the user's phones (no notification is
    shown; the app refreshes what's on screen). Sent at most once per SYNC_GAP per user and
    process, with one trailing message so the last change is never missed.
- Events carry ids and kinds only, never mail content.
"""
import json
import logging
import queue
import threading
import time
import uuid
from collections.abc import Iterable

from sqlalchemy import event, text
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)
CHANNEL = "sift_events"
SYNC_GAP = 2.0  # seconds between silent phone syncs for one user
_INFO_KEY = "sift_events"


def publish(db: Session, user_id: uuid.UUID | str, kind: str, **data) -> None:
    """kind: "mail" (read state, labels, filing… of `ids`), "new_mail", "drafts", "resync"."""
    payload = {"u": str(user_id), "type": kind, **data}
    if "ids" in payload:
        payload["ids"] = [str(i) for i in list(payload["ids"])[:200]]
    db.info.setdefault(_INFO_KEY, []).append(payload)


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    pending = session.info.pop(_INFO_KEY, None)
    if not pending:
        return
    try:
        # a fresh connection: the committed session can't run SQL inside this hook
        from app.db import get_engine

        with get_engine().connect() as conn:
            for p in pending:
                conn.execute(text("SELECT pg_notify(:c, :p)"), {"c": CHANNEL, "p": json.dumps(p)[:7900]})
            conn.commit()
    except Exception:  # noqa: BLE001  (live updates are best effort; the next load is still right)
        log.exception("could not publish live events")
    for user_id in {p["u"] for p in pending}:
        _phones.sync(user_id)


@event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session) -> None:
    session.info.pop(_INFO_KEY, None)


class _PhoneSync:
    """Silent "sync" pushes, coalesced per user, sent from a background thread so a slow FCM
    call never holds up the request or job that changed something."""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}
        self._waiting: set[str] = set()
        self._lock = threading.Lock()
        self._q: queue.Queue[str] = queue.Queue()
        self._thread: threading.Thread | None = None

    enabled_in_tests = False  # tests that check phone syncs turn this on

    def sync(self, user_id: str) -> None:
        from app.config import get_settings

        if get_settings().env == "test" and not self.enabled_in_tests:
            return
        with self._lock:
            if user_id in self._waiting:
                return  # a send is already due; it will carry this change
            self._waiting.add(user_id)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, daemon=True, name="phone-sync")
                self._thread.start()
        self._q.put(user_id)

    def _run(self) -> None:
        while True:
            user_id = self._q.get()
            wait = self._last.get(user_id, 0) + SYNC_GAP - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            with self._lock:
                self._waiting.discard(user_id)
                self._last[user_id] = time.monotonic()
            try:
                send_phone_sync(uuid.UUID(user_id))
            except Exception:  # noqa: BLE001
                log.exception("phone sync failed")


def send_phone_sync(user_id: uuid.UUID) -> int:
    from app import notify
    from app.db import get_sessionmaker

    with get_sessionmaker()() as db:
        n = notify.send_data(db, user_id, {"type": "sync"})
        db.commit()  # a stale device token may have been removed
        return n


_phones = _PhoneSync()


# ---- fan-out to open web streams (one listener per API process) -----------------------------------

class Hub:
    """One LISTEN connection per process, in a thread (portable: async Postgres drivers can't use
    Windows' default event loop), handing events to each open stream's asyncio queue."""

    def __init__(self) -> None:
        self._subs: dict[str, set[tuple[object, object]]] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def subscribe(self, user_id: str, loop, q) -> None:
        with self._lock:
            self._subs.setdefault(user_id, set()).add((loop, q))
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._listen, daemon=True, name="events-listen")
                self._thread.start()

    def unsubscribe(self, user_id: str, loop, q) -> None:
        with self._lock:
            subs = self._subs.get(user_id)
            if subs:
                subs.discard((loop, q))
                if not subs:
                    self._subs.pop(user_id, None)

    def count(self, user_id: str) -> int:
        with self._lock:
            return len(self._subs.get(user_id, ()))

    def _deliver(self, user_id: str | None, payload: dict) -> None:
        with self._lock:
            targets = [t for u, subs in self._subs.items() if user_id is None or u == user_id for t in subs]
        for loop, q in targets:
            try:
                loop.call_soon_threadsafe(q.put_nowait, payload)
            except Exception:  # noqa: BLE001  (loop closed: that stream is gone)
                pass

    def _listen(self) -> None:
        import psycopg

        from app.config import get_settings

        url = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
        while True:
            try:
                with psycopg.connect(url, autocommit=True) as conn:
                    conn.execute(f"LISTEN {CHANNEL}")
                    self._deliver(None, {"type": "resync"})  # anything missed while (re)connecting
                    for n in conn.notifies():
                        try:
                            payload = json.loads(n.payload)
                        except ValueError:
                            continue
                        self._deliver(payload.pop("u", None) or "-", payload)
            except Exception:  # noqa: BLE001
                log.exception("live events listener lost its connection; reconnecting")
                time.sleep(3)


hub = Hub()


def mail_changed(db: Session, user_id: uuid.UUID, ids: Iterable) -> None:
    publish(db, user_id, "mail", ids=list(ids))

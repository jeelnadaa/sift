import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app import accounts, crypto, jobs, scheduler
from app.mail import google_oauth
from app.mail.base import AuthRevoked, Changes, CursorExpired, Profile, Watch
from app.models import GmailAccount, Job, User


class FakeProvider:
    def __init__(self, email="me@gmail.com", cursor=500):
        self.email, self.cursor = email, cursor
        self.changes: Changes | Exception = Changes([], cursor)
        self.watches = []

    def profile(self):
        return Profile(self.email, self.cursor)

    def list_changes(self, since):
        self.since = since
        if isinstance(self.changes, Exception):
            raise self.changes
        return self.changes

    def start_watch(self, topic):
        self.watches.append(topic)
        return Watch(self.cursor, int((datetime.now(UTC) + timedelta(days=7)).timestamp() * 1000))

    def stop_watch(self):
        pass


@pytest.fixture
def fake(monkeypatch, override_settings):
    crypto._fernet.cache_clear()
    override_settings(encryption_keys=Fernet.generate_key().decode(), change_detection="poll", pubsub_topic="projects/p/topics/t")
    accounts._token_cache.clear()
    p = FakeProvider()
    monkeypatch.setattr(accounts, "provider_factory", lambda token: p)
    monkeypatch.setattr(google_oauth, "exchange_code", lambda code: {"access_token": "at", "refresh_token": "rt", "expires_in": 3600})
    monkeypatch.setattr(google_oauth, "refresh_access_token", lambda rt: ("at2", 3600))
    yield p
    crypto._fernet.cache_clear()


@pytest.fixture
def user(db):
    u = User(email="owner@gmail.com")
    db.add(u)
    db.commit()
    return u


def account(db) -> GmailAccount:
    db.expire_all()
    return db.scalar(select(GmailAccount))


# ---- connect -------------------------------------------------------------------

def test_connect_new_account_starts_from_now_and_encrypts_token(db, user, fake):
    a = accounts.connect_account(db, "owner@gmail.com", "code")
    assert db.scalar(select(Job.kind).where(Job.kind == "onboarding_scan"))  # first-run scan queued
    a = account(db)
    assert (a.email, a.status, a.history_id) == ("me@gmail.com", "active", 500)
    assert a.encrypted_refresh_token != "rt" and crypto.decrypt(a.encrypted_refresh_token) == "rt"
    assert fake.watches == []  # poll mode: no Pub/Sub watch


def test_reconnect_keeps_cursor_and_reactivates(db, user, fake):
    accounts.connect_account(db, "owner@gmail.com", "code")
    a = account(db)
    a.history_id, a.status = 300, "needs_reconnect"
    db.commit()
    fake.cursor = 900
    accounts.connect_account(db, "owner@gmail.com", "code")
    a = account(db)
    assert (a.history_id, a.status) == (300, "active")  # mail since 300 is still picked up


def test_address_owned_by_other_user_is_refused(db, user, fake):
    accounts.connect_account(db, "owner@gmail.com", "code")
    db.add(User(email="other@gmail.com"))
    db.commit()
    with pytest.raises(accounts.ConnectError):
        accounts.connect_account(db, "other@gmail.com", "code")


def test_push_mode_starts_watch_on_connect(db, user, fake, override_settings):
    override_settings(change_detection="push")
    accounts.connect_account(db, "owner@gmail.com", "code")
    assert fake.watches == ["projects/p/topics/t"]
    assert account(db).watch_expires_at is not None


# ---- check_account ----------------------------------------------------------------

@pytest.fixture
def connected(db, user, fake):
    accounts.connect_account(db, "owner@gmail.com", "code")
    accounts._token_cache.clear()  # force the refresh path
    return account(db)


def test_check_hands_new_mail_on_and_advances_cursor(db, connected, fake, monkeypatch):
    seen = []
    monkeypatch.setattr(accounts, "on_new_messages", lambda db, a, p, ids: seen.append(ids))
    fake.changes = Changes(["m1", "m2"], 520)
    assert accounts.check_account(connected.id) == 2
    assert fake.since == 500 and seen == [["m1", "m2"]]
    assert account(db).history_id == 520


def test_cursor_not_saved_when_processing_fails(db, connected, fake, monkeypatch):
    def boom(db, a, p, ids):
        raise RuntimeError("pipeline failed")
    monkeypatch.setattr(accounts, "on_new_messages", boom)
    fake.changes = Changes(["m1"], 520)
    with pytest.raises(RuntimeError):
        accounts.check_account(connected.id)
    assert account(db).history_id == 500  # retried from the same point next time


def test_expired_cursor_restarts_from_now(db, connected, fake):
    fake.changes, fake.cursor = CursorExpired("500"), 9000
    assert accounts.check_account(connected.id) == 0
    assert account(db).history_id == 9000


@pytest.mark.parametrize("blocked,status", [(False, "needs_reconnect"), (True, "blocked")])
def test_revoked_auth_pauses_only_that_account(db, connected, fake, monkeypatch, blocked, status):
    def revoked(rt):
        raise AuthRevoked("invalid_grant", blocked=blocked)
    monkeypatch.setattr(google_oauth, "refresh_access_token", revoked)
    assert accounts.check_account(connected.id) == 0
    assert account(db).status == status
    assert accounts.active_account_ids(db) == []


def test_unreadable_token_after_key_change_needs_reconnect(db, connected, fake, override_settings):
    crypto._fernet.cache_clear()
    override_settings(encryption_keys=Fernet.generate_key().decode())  # old key gone
    assert accounts.check_account(connected.id) == 0
    a = account(db)
    assert a.status == "needs_reconnect" and "ENCRYPTION_KEYS" in a.status_detail


def test_inactive_account_is_skipped(db, connected, fake):
    connected.status = "needs_reconnect"
    db.merge(connected)
    db.commit()
    fake.changes = Changes(["m1"], 999)
    assert accounts.check_account(connected.id) == 0
    assert account(db).history_id == 500


def test_renew_watches_only_when_expiring(db, connected, fake, override_settings):
    override_settings(change_detection="push")
    a = account(db)
    a.watch_expires_at = datetime.now(UTC) + timedelta(days=5)
    db.commit()
    assert accounts.renew_watches() == 0
    a.watch_expires_at = datetime.now(UTC) + timedelta(hours=3)
    db.commit()
    assert accounts.renew_watches() == 1
    assert account(db).watch_expires_at > datetime.now(UTC) + timedelta(days=6)


def test_push_routes_to_check(db, connected, fake, monkeypatch):
    checked = []
    monkeypatch.setattr(accounts, "check_account", lambda aid, source="poll": checked.append((aid, source)))
    jobs.handle_gmail_push({"email": "me@gmail.com", "history_id": 1})
    jobs.handle_gmail_push({"email": "nobody@x.com", "history_id": 1})
    assert checked == [(connected.id, "push")]


# ---- scheduler and queue ---------------------------------------------------------------

def test_scheduler_queues_one_check_per_active_account_without_piling_up(db, connected, override_settings):
    override_settings(change_detection="poll")
    asyncio.run(scheduler.queue_checks())
    asyncio.run(scheduler.queue_checks())  # previous check still queued: deduped
    rows = list(db.scalars(select(Job).where(Job.kind == "check_account")))
    assert [(j.kind, j.dedupe_key) for j in rows] == [("check_account", f"check:{connected.id}")]

    rows[0].status = "done"
    db.commit()
    asyncio.run(scheduler.queue_checks())  # finished: a new check may be queued
    assert len(list(db.scalars(select(Job).where(Job.kind == "check_account")))) == 2


def test_cleanup_removes_old_finished_jobs(db):
    db.add_all([
        Job(kind="x", payload={}, status="done", created_at=datetime.now(UTC) - timedelta(days=2)),
        Job(kind="x", payload={}, status="queued", created_at=datetime.now(UTC) - timedelta(days=2)),
        Job(kind="x", payload={}, status="done"),
    ])
    db.commit()
    assert jobs.cleanup_finished(db) == 1


def test_tick_interval_is_the_poll_interval(override_settings):
    override_settings(poll_interval_seconds=5)
    assert scheduler.tick_interval() == 5


def test_plan_checks_poll_mode_checks_every_account_every_tick():
    import uuid
    a, b = uuid.uuid4(), uuid.uuid4()
    now = datetime.now(UTC)
    assert scheduler.plan_checks([(a, None), (b, now + timedelta(days=3))], False, 0.0, now) == [(a, "poll"), (b, "poll")]


def test_plan_checks_push_mode_falls_back_to_polling_without_a_working_watch():
    import uuid
    scheduler._last_safety.clear()
    good, none, expired = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime.now(UTC)
    accounts = [(good, now + timedelta(days=3)), (none, None), (expired, now - timedelta(minutes=1))]
    first = scheduler.plan_checks(accounts, True, 1000.0, now)
    assert first == [(good, "safety"), (none, "poll"), (expired, "poll")]
    scheduler._last_safety[good] = 1000.0
    assert scheduler.plan_checks(accounts, True, 1100.0, now) == [(none, "poll"), (expired, "poll")]  # safety not due yet
    assert (good, "safety") in scheduler.plan_checks(accounts, True, 1000.0 + scheduler.PUSH_SAFETY_INTERVAL, now)


def test_safety_check_that_finds_old_unannounced_mail_marks_push_broken(db, connected, fake, monkeypatch, override_settings):
    override_settings(change_detection="push")
    a = account(db)
    a.watch_expires_at = datetime.now(UTC) + timedelta(days=5)
    db.commit()
    monkeypatch.setattr(accounts, "on_new_messages", lambda *args: None)
    monkeypatch.setattr(accounts, "_push_missed", lambda db, acc, ids: True)
    fake.changes = Changes(["m1"], 510)
    accounts.check_account(connected.id, "push")
    assert account(db).watch_expires_at is not None  # a push-triggered check never marks push broken
    fake.changes = Changes(["m2"], 520)
    accounts.check_account(connected.id, "safety")
    assert account(db).watch_expires_at is None  # now polled until the hourly renewal


def test_push_missed_only_for_mail_older_than_push_latency(db, connected):
    from app.models import Message
    now = datetime.now(UTC)
    db.add_all([
        Message(user_id=connected.user_id, account_id=connected.id, gmail_id="fresh", thread_id="t", received_at=now - timedelta(seconds=20), status="processed"),
        Message(user_id=connected.user_id, account_id=connected.id, gmail_id="old", thread_id="t", received_at=now - timedelta(minutes=4), status="processed"),
    ])
    db.commit()
    a = account(db)
    assert accounts._push_missed(db, a, ["fresh"]) is False  # its push may still be on the way
    assert accounts._push_missed(db, a, ["old"]) is True


# ---- OAuth callback page ----------------------------------------------------------------

def test_callback_rejects_bad_state(client, override_settings):
    override_settings(app_secret="s3cret")
    r = client.get("/api/v1/accounts/oauth/callback", params={"state": "nope", "code": "c"})
    assert r.status_code == 400 and "Link expired" in r.text


def test_callback_connects_account(client, db, user, fake, override_settings):
    override_settings(app_secret="s3cret")
    state = google_oauth.make_state("owner@gmail.com")
    r = client.get("/api/v1/accounts/oauth/callback", params={"state": state, "code": "c"})
    assert r.status_code == 200 and "me@gmail.com is connected" in r.text
    assert account(db).status == "active"


def test_callback_shows_admin_block(client, override_settings):
    override_settings(app_secret="s3cret")
    state = google_oauth.make_state("owner@gmail.com")
    r = client.get("/api/v1/accounts/oauth/callback", params={"state": state, "error": "admin_policy_enforced"})
    assert "blocked by its administrator" in r.text

"""Healing after the server was off: late mail, mail too old for the AI, a new account's import,
one summary push instead of a flood, and the catch-up job for an expired change cursor."""
import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app import accounts, demo, jobs
from app.mail.base import CursorExpired
from app.models import Device, GmailAccount, Job, Message, Notification, User
from app.pipeline import process_message
from app.llm import service as llm
from tests.test_pipeline import FakeLlm, with_key


class CatchUpProvider(demo.DemoProvider):
    """Demo mail with chosen ages, listable by search (newest first, like Gmail)."""

    def __init__(self, messages):
        super().__init__(messages)
        self.queries = []

    def list_message_ids(self, query, limit):
        self.queries.append((query, limit))
        ordered = sorted(self._by_id.values(), key=lambda m: -int(m["internalDate"]))
        return [m["id"] for m in ordered][:limit]


def aged(sample: dict, hours: float) -> dict:
    return {**sample, "internalDate": str(int((time.time() - hours * 3600) * 1000))}


@pytest.fixture
def fake_llm(monkeypatch):
    f = FakeLlm()
    monkeypatch.setattr(llm, "provider_factory", lambda provider, key, model=None, *args, **kwargs: f)
    return f


@pytest.fixture
def setup(db, keys, fcm_sends, monkeypatch):
    user = User(email="owner@gmail.com")
    db.add(user)
    db.flush()
    db.add(Device(user_id=user.id, fcm_token="phone-token-123"))
    demo.ensure_starter_rules(db, user)
    account = demo.demo_account(db, user)
    account.encrypted_refresh_token = "not-used"  # catch-up and checks skip accounts without one
    db.commit()
    samples = {m["id"].split("-")[1]: m for m in demo.samples()}
    return user, account, samples


def mail_pushes(sends):
    return [s for s in sends if s.get("type") not in ("system", "sync")]


def system_pushes(sends):
    return [s for s in sends if s.get("type") == "system"]


def run(db, account, provider, sample, mode="live"):
    return process_message(db, db.get(GmailAccount, account.id), provider, sample["id"], mode=mode)


def test_late_mail_gets_the_ai_but_only_urgent_mail_pushes_on_its_own(db, setup, fake_llm, fcm_sends):
    user, account, s = setup
    with_key(db, user)
    p = CatchUpProvider([aged(s["recruiter"], 5), aged(s["hirepro"], 5)])
    recruiter = run(db, account, p, aged(s["recruiter"], 5))
    hirepro = run(db, account, p, aged(s["hirepro"], 5))
    assert (recruiter.decided_by, recruiter.notified, recruiter.held) == ("llm", False, True)
    assert (hirepro.priority, hirepro.notified, hirepro.held) == ("urgent", True, False)
    assert len(fake_llm.calls) == 2
    assert [m["priority"] for m in mail_pushes(fcm_sends)] == ["urgent"]


def test_mail_older_than_the_ai_window_is_rules_only_and_never_hidden(db, setup, fake_llm, fcm_sends):
    user, account, s = setup
    with_key(db, user)
    old = aged(s["hirepro"], 24 * 4)
    bank = aged(s["bank"], 24 * 4)
    p = CatchUpProvider([old, bank])
    o = run(db, account, p, old)
    b = run(db, account, p, bank)
    assert fake_llm.calls == []  # never backfill old mail with the user's tokens
    assert (o.priority, o.decided_by, o.quiet, o.notified) == ("normal", "default", True, False)  # delivered, not hidden
    assert (b.priority, b.decided_by) == ("silent", "rule")  # rules still apply
    assert mail_pushes(fcm_sends) == []


def test_import_mode_is_silent_and_spends_nothing_even_for_fresh_mail(db, setup, fake_llm, fcm_sends):
    user, account, s = setup
    with_key(db, user)
    p = CatchUpProvider([s["hirepro"]])
    o = run(db, account, p, s["hirepro"], mode="import")
    assert (o.priority, o.quiet, o.notified) == ("normal", True, False)
    assert fake_llm.calls == [] and mail_pushes(fcm_sends) == []
    assert db.scalar(select(func.count()).select_from(Notification)) == 0


def test_after_downtime_one_summary_push_replaces_the_flood(db, setup, fake_llm, fcm_sends):
    user, account, s = setup
    late = [aged(s[k], 3) for k in ("placement", "recruiter", "fraud")] + [aged(s["bank"], 3)]
    p = CatchUpProvider(late)  # AI off: everything undecided is normal priority
    new = accounts.on_new_messages(db, db.get(GmailAccount, account.id), p, [m["id"] for m in late])
    assert new == 4
    assert mail_pushes(fcm_sends) == []
    summary = system_pushes(fcm_sends)
    assert len(summary) == 1 and summary[0]["body"].startswith("3 mails arrived")  # the silenced debit isn't counted
    assert db.scalar(select(func.count()).select_from(Message)) == 4  # nothing lost


def test_fresh_mail_after_a_restart_still_pushes_normally(db, setup, fake_llm, fcm_sends):
    user, account, s = setup
    p = CatchUpProvider([s["recruiter"]])
    accounts.on_new_messages(db, db.get(GmailAccount, account.id), p, [s["recruiter"]["id"]])
    assert len(mail_pushes(fcm_sends)) == 1 and system_pushes(fcm_sends) == []


def test_catch_up_lists_by_date_processes_oldest_first_and_is_idempotent(db, setup, fake_llm, fcm_sends, monkeypatch):
    user, account, s = setup
    mails = [aged(s["placement"], 30), aged(s["recruiter"], 20), aged(s["fraud"], 10)]
    p = CatchUpProvider(mails)
    monkeypatch.setattr(accounts, "provider_for", lambda a: p)
    order = []
    real = accounts.on_new_messages
    monkeypatch.setattr(accounts, "on_new_messages", lambda db, a, prov, ids, mode="live": order.extend(ids) or real(db, a, prov, ids, mode))

    since = datetime.now(UTC) - timedelta(days=90)  # longer than CATCH_UP_DAYS: clamped
    assert accounts.catch_up(account.id, since) == 3
    query, limit = p.queries[0]
    after = int(query.split()[0].removeprefix("after:"))
    assert abs(after - (datetime.now(UTC) - timedelta(days=accounts.CATCH_UP_DAYS)).timestamp()) < 60
    assert "-in:sent" in query and limit == accounts.CATCH_UP_MAX
    assert order == [m["id"] for m in mails]  # oldest first
    assert len(system_pushes(fcm_sends)) == 1  # one summary for the whole gap
    assert accounts.catch_up(account.id, since) == 0  # a retry costs nothing


def test_expired_cursor_restarts_from_now_and_queues_a_catch_up(db, setup, monkeypatch):
    user, account, s = setup
    a = db.get(GmailAccount, account.id)
    a.history_id = 100
    last_ok = datetime.now(UTC) - timedelta(days=9)
    a.last_check_ok_at = last_ok
    db.commit()

    class Expired:
        def list_changes(self, since):
            raise CursorExpired(str(since))

        def profile(self):
            from app.mail.base import Profile
            return Profile("demo@sift.test", 9000)

    monkeypatch.setattr(accounts, "provider_for", lambda acc: Expired())
    assert accounts.check_account(account.id) == 0
    db.expire_all()
    assert db.get(GmailAccount, account.id).history_id == 9000
    job = db.scalar(select(Job).where(Job.kind == "catch_up"))
    assert job.payload["mode"] == "live" and datetime.fromisoformat(job.payload["since"]) == last_ok
    assert "catch_up" in jobs.LONG_KINDS

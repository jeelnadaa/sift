"""Mail-check health: failures are recorded, alerted once after 15 minutes, recovery is announced."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import accounts, intake
from app.mail.base import Changes
from app.mail.gmail import GmailError
from app.models import Device, GmailAccount, User
from tests.test_accounts import FakeProvider, fake  # noqa: F401  (fixture)
from tests.test_rule_tools import H


@pytest.fixture
def acc(db, fake, fcm_sends, keys):
    u = User(email="owner@gmail.com")
    db.add(u)
    db.flush()
    db.add(Device(user_id=u.id, fcm_token="phone"))
    a = GmailAccount(user_id=u.id, email="me@gmail.com", status="active", encrypted_refresh_token=__import__("app.crypto", fromlist=["x"]).encrypt("rt"), history_id=100)
    db.add(a)
    db.commit()
    return u, a


def fresh(db, a):
    db.expire_all()
    return db.get(GmailAccount, a.id)


def test_a_failing_check_is_recorded_alerted_once_and_recovery_announced(client, db, acc, fake, fcm_sends):
    user, a = acc
    fake.changes = GmailError(500, "backend error")
    with pytest.raises(GmailError):
        accounts.check_account(a.id)
    a = fresh(db, a)
    assert a.check_failing_since is not None and a.last_check_error == "GmailError 500"
    assert intake.watch() == 0  # not 15 minutes yet

    later = datetime.now(UTC) + timedelta(minutes=16)
    assert intake.watch(now=later) == 1 and fcm_sends[-1]["title"] == "Sift can't check your mail"
    assert intake.watch(now=later + timedelta(minutes=5)) == 0  # once per stall
    acc_json = client.get("/api/v1/accounts", headers=H(user)).json()[0]
    assert acc_json["check_failing_since"] and acc_json["last_check_error"] == "GmailError 500"

    fake.changes = Changes([], 120)
    accounts.check_account(a.id)
    a = fresh(db, a)
    assert a.check_failing_since is None and a.last_check_ok_at is not None and a.intake_alerted_at is None
    assert fcm_sends[-1]["title"] == "Sift is checking mail again"


def test_an_account_nobody_checked_for_15_minutes_counts_as_stalled(client, db, acc):
    user, a = acc
    a = fresh(db, a)
    a.last_check_ok_at = datetime.now(UTC) - timedelta(minutes=20)
    db.commit()
    assert [x.id for x in intake.stalled(db)] == [a.id]
    assert client.get("/health").json()["mail_checks"] == "stalled (1)"
    assert client.get("/api/v1/accounts", headers=H(user)).json()[0]["stalled"] is True


def test_healthy_accounts_are_quiet(client, db, acc, fake, fcm_sends):
    user, a = acc
    fake.changes = Changes([], 101)
    accounts.check_account(a.id)
    assert intake.watch(now=datetime.now(UTC) + timedelta(minutes=5)) == 0 and fcm_sends == []
    assert client.get("/health").json()["mail_checks"] == "ok"

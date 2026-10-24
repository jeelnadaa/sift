"""Phase 3c: write access per account, mail actions, snooze, rule extras done in Gmail."""
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from app import accounts as account_service
from app import snooze as snooze_service
from app.mail import google_oauth
from app.mail.gmail import GmailError
from app.models import GmailAccount, Message, Rule, Snooze, User
from tests.test_rule_tools import H

MODIFY = google_oauth.MODIFY_SCOPE


class FakeGmail:
    def __init__(self):
        self.calls = []
        self.labels = [{"id": "Label_1", "name": "Receipts", "type": "user"}, {"id": "INBOX", "name": "INBOX", "type": "system"}]
        self.fail = None

    def _rec(self, *a):
        if self.fail:
            raise self.fail
        self.calls.append(a)

    def modify_thread(self, tid, add, remove):
        self._rec("modify_thread", tid, tuple(add), tuple(remove))

    def modify_message(self, mid, add, remove):
        self._rec("modify_message", mid, tuple(add), tuple(remove))

    def trash_thread(self, tid):
        self._rec("trash", tid)

    def untrash_thread(self, tid):
        self._rec("untrash", tid)

    def list_labels(self):
        return self.labels

    def create_label(self, name):
        self._rec("create_label", name)
        lbl = {"id": f"Label_{len(self.labels) + 1}", "name": name, "type": "user"}
        self.labels.append(lbl)
        return lbl


@pytest.fixture
def world(db, keys, monkeypatch, fcm_sends):
    user = User(email="owner@gmail.com")
    db.add(user)
    db.flush()
    from app.models import Device
    db.add(Device(user_id=user.id, fcm_token="phone"))
    acc = GmailAccount(user_id=user.id, email="me@gmail.com", status="active", encrypted_refresh_token="x", scopes=[google_oauth.READONLY_SCOPE])
    db.add(acc)
    db.flush()
    msgs = [Message(user_id=user.id, account_id=acc.id, gmail_id=f"g{i}", thread_id=f"t{i}", subject=f"Mail {i}", sender="a@shop.com",
                    status="processed", priority="normal", labels=["INBOX", "UNREAD"], received_at=datetime.now(UTC) - timedelta(hours=i))
            for i in range(3)]
    db.add_all(msgs)
    db.commit()
    g = FakeGmail()
    monkeypatch.setattr(account_service, "provider_for", lambda a: g)
    return user, acc, msgs, g


def grant(db, acc):
    acc.scopes = [google_oauth.READONLY_SCOPE, MODIFY]
    db.commit()


def act(client, user, msgs, action, **extra):
    return client.post("/api/v1/mail/actions", headers=H(user), json={"message_ids": [str(m.id) for m in msgs], "action": action, **extra})


# ---- write access ----------------------------------------------------------------------------

def test_actions_ask_for_write_access_first_and_change_nothing(client, db, world):
    user, acc, msgs, g = world
    r = act(client, user, msgs[:1], "archive")
    assert r.status_code == 403
    d = r.json()["detail"]
    assert d["code"] == "needs_write_access" and d["accounts"] == [{"id": str(acc.id), "email": "me@gmail.com"}]
    assert g.calls == [] and db.get(Message, msgs[0].id).labels == ["INBOX", "UNREAD"]


def test_write_access_url_asks_google_for_modify_for_that_account_only(client, db, world, override_settings):
    user, acc, msgs, g = world
    override_settings(google_client_id="cid", public_base_url="https://sift.example")
    url = client.get(f"/api/v1/accounts/{acc.id}/write-access-url", headers=H(user)).json()["auth_url"]
    q = parse_qs(urlparse(url).query)
    assert MODIFY in q["scope"][0] and q["login_hint"] == ["me@gmail.com"] and q["include_granted_scopes"] == ["true"]
    assert google_oauth.read_state_data(q["state"][0])["x"] == {"intent": "write", "account": "me@gmail.com"}
    assert client.get("/api/v1/accounts", headers=H(user)).json()[0]["can_modify"] is False


def test_granting_write_access_through_google_is_recorded(client, db, world, monkeypatch, override_settings):
    from tests.test_accounts import FakeProvider
    user, acc, msgs, g = world
    override_settings(change_detection="poll")
    monkeypatch.setattr(google_oauth, "exchange_code", lambda code: {"access_token": "at", "refresh_token": "rt2", "expires_in": 3600,
                                                                     "scope": f"{google_oauth.READONLY_SCOPE} {MODIFY}"})
    monkeypatch.setattr(account_service, "provider_factory", lambda token: FakeProvider("me@gmail.com"))
    state = google_oauth.make_state(user.email, {"intent": "write", "account": "me@gmail.com"})
    r = client.get("/api/v1/accounts/oauth/callback", params={"state": state, "code": "c"})
    assert "Write access granted" in r.text and "/app/accounts" in r.text
    db.expire_all()
    assert account_service.can_modify(db.get(GmailAccount, acc.id))


# ---- actions ------------------------------------------------------------------------------------

def test_archive_read_star_change_gmail_and_local_labels(client, db, world):
    user, acc, msgs, g = world
    grant(db, acc)
    assert act(client, user, msgs[:2], "archive").json() == {"done": 2, "failed_accounts": []}
    assert act(client, user, msgs[:1], "read").json()["done"] == 1
    assert act(client, user, msgs[:1], "star").json()["done"] == 1
    assert g.calls[:3] == [("modify_thread", "t0", (), ("INBOX",)), ("modify_thread", "t1", (), ("INBOX",)), ("modify_thread", "t0", (), ("UNREAD",))]
    db.expire_all()
    assert db.get(Message, msgs[0].id).labels == ["STARRED"] and db.get(Message, msgs[1].id).labels == ["UNREAD"]


def test_labels_are_found_or_created_by_name(client, db, world):
    user, acc, msgs, g = world
    grant(db, acc)
    act(client, user, msgs[:1], "label", label="receipts")
    assert g.calls[-1] == ("modify_thread", "t0", ("Label_1",), ())
    act(client, user, msgs[:1], "label", label="Job hunt")
    assert ("create_label", "Job hunt") in g.calls
    assert act(client, user, msgs[:1], "unlabel", label="Nope").status_code == 422
    assert act(client, user, msgs[:1], "label").status_code == 422


def test_trash_is_gmails_trash_and_can_be_undone(client, db, world):
    user, acc, msgs, g = world
    grant(db, acc)
    act(client, user, msgs[:1], "trash")
    act(client, user, msgs[:1], "untrash")
    assert [c[0] for c in g.calls] == ["trash", "untrash"]
    assert db.get(Message, msgs[0].id) is not None  # Sift never deletes mail


def test_revoked_write_access_is_noticed(client, db, world):
    user, acc, msgs, g = world
    grant(db, acc)
    g.fail = GmailError(403, "Insufficient Permission")
    r = act(client, user, msgs[:1], "archive").json()
    assert r["failed_accounts"] == ["me@gmail.com"]
    db.expire_all()
    assert not account_service.can_modify(db.get(GmailAccount, acc.id))


def test_others_mail_cannot_be_touched(client, db, world):
    user, acc, msgs, g = world
    other = User(email="x@gmail.com")
    db.add(other)
    db.commit()
    assert act(client, other, msgs[:1], "archive").status_code == 404
    r = client.post("/api/v1/mail/actions", headers=H(other), json={"threads": [{"account_id": str(acc.id), "thread_id": "t0"}], "action": "archive"})
    assert r.status_code == 422


# ---- snooze -------------------------------------------------------------------------------------

def test_snooze_without_write_access_hides_in_sift_only(client, db, world):
    user, acc, msgs, g = world
    until = (datetime.now(UTC) + timedelta(hours=3)).isoformat()
    r = client.post("/api/v1/snoozes", headers=H(user), json={"message_ids": [str(msgs[0].id)], "until": until})
    assert r.status_code == 201 and r.json()[0]["in_gmail"] is False and g.calls == []
    feed = [i["id"] for i in client.get("/api/v1/messages", headers=H(user)).json()["items"]]
    assert str(msgs[0].id) not in feed and len(feed) == 2
    assert [i["subject"] for i in client.get("/api/v1/search", headers=H(user), params={"q": "is:snoozed"}).json()["items"]] == ["Mail 0"]


def test_snooze_with_write_access_archives_and_wakes_back_to_the_inbox(client, db, world, fcm_sends):
    user, acc, msgs, g = world
    grant(db, acc)
    until = datetime.now(UTC) + timedelta(hours=1)
    client.post("/api/v1/snoozes", headers=H(user), json={"message_ids": [str(msgs[0].id)], "until": until.isoformat()})
    assert g.calls == [("modify_thread", "t0", (), ("INBOX",))]
    assert snooze_service.wake_due(db, now=until - timedelta(minutes=5)) == 0
    assert snooze_service.wake_due(db, now=until + timedelta(seconds=1)) == 1
    assert g.calls[-1] == ("modify_thread", "t0", ("INBOX", "UNREAD"), ())
    assert fcm_sends[-1]["type"] == "snooze" and fcm_sends[-1]["title"].startswith("Back from snooze")
    assert snooze_service.wake_due(db, now=until + timedelta(minutes=5)) == 0  # once only
    assert str(msgs[0].id) in [i["id"] for i in client.get("/api/v1/messages", headers=H(user)).json()["items"]]


def test_a_reply_wakes_a_snoozed_conversation_and_cancel_brings_it_back(client, db, world):
    user, acc, msgs, g = world
    grant(db, acc)
    until = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    s1 = client.post("/api/v1/snoozes", headers=H(user), json={"message_ids": [str(msgs[0].id)], "until": until}).json()[0]
    client.post("/api/v1/snoozes", headers=H(user), json={"message_ids": [str(msgs[1].id)], "until": until})
    reply = Message(user_id=user.id, account_id=acc.id, gmail_id="g-reply", thread_id="t1", subject="Re: Mail 1", status="processed", priority="normal")
    db.add(reply)
    db.flush()
    snooze_service.on_new_mail(db, reply)
    db.commit()
    assert db.scalar(select(Snooze).where(Snooze.thread_id == "t1")).woke_reason == "reply"
    assert client.delete(f"/api/v1/snoozes/{s1['id']}", headers=H(user)).status_code == 204
    assert g.calls[-1] == ("modify_thread", "t0", ("INBOX",), ())
    assert client.get("/api/v1/snoozes", headers=H(user)).json() == []


@pytest.mark.parametrize("delta", [timedelta(minutes=-5), timedelta(days=400)])
def test_snooze_times_are_checked(client, world, delta):
    user, acc, msgs, g = world
    r = client.post("/api/v1/snoozes", headers=H(user), json={"message_ids": [str(msgs[0].id)], "until": (datetime.now(UTC) + delta).isoformat()})
    assert r.status_code == 422


# ---- rule extras -------------------------------------------------------------------------------

def test_rule_mark_read_and_star_run_in_gmail_once_write_access_exists(db, keys, fcm_sends, monkeypatch):
    from app import demo
    from tests.test_pipeline import run
    user = User(email="o@gmail.com")
    db.add(user)
    db.flush()
    acc = demo.demo_account(db, user)
    db.add(Rule(user_id=user.id, position=0, name="r", origin="editor", conditions={"field": "subject", "op": "contains_any", "value": ["globex"]},
                action={"type": "notify_normal", "mark_read": True, "star": True}))
    db.commit()
    sample = next(m for m in demo.samples() if "Globex" in str(m))
    g = FakeGmail()

    class P(demo.DemoProvider):
        def modify_message(self, mid, add, remove):
            g.modify_message(mid, add, remove)

    out = run(db, acc, P([sample]), sample)
    assert db.get(Message, out.message_id).extraction["pending_gmail_actions"] == ["mark_read", "star"] and g.calls == []
    acc.scopes = [MODIFY]
    db.commit()
    s2 = dict(sample, id="other-id")
    out = run(db, acc, P([s2]), s2)
    m = db.get(Message, out.message_id)
    assert g.calls == [("modify_message", "other-id", ("STARRED",), ("UNREAD",))] and "pending_gmail_actions" not in (m.extraction or {})
    assert "UNREAD" not in m.labels and "STARRED" in m.labels

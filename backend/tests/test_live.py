"""Read state and live updates: opening a mail marks it read (in Gmail with write access, else in
Sift only), and every other open app of the user hears about changes without reloading."""
import asyncio
import json
import time
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from sqlalchemy import select

from app import accounts as account_service
from app import events, fcm
from app.config import get_settings
from app.db import get_sessionmaker
from app.mail import google_oauth
from app.models import Device, GmailAccount, Message, User
from tests.test_rule_tools import H


class Gmail:
    def __init__(self):
        self.calls = []

    def modify_thread(self, tid, add, remove):
        self.calls.append((tid, tuple(add), tuple(remove)))


@pytest.fixture
def world(db, keys, monkeypatch, fcm_sends):
    user = User(email="owner@gmail.com")
    db.add(user)
    db.flush()
    db.add(Device(user_id=user.id, fcm_token="phone"))
    rw = GmailAccount(user_id=user.id, email="rw@gmail.com", status="active", encrypted_refresh_token="x",
                      scopes=[google_oauth.READONLY_SCOPE, google_oauth.MODIFY_SCOPE])
    ro = GmailAccount(user_id=user.id, email="ro@gmail.com", status="active", encrypted_refresh_token="x", scopes=[google_oauth.READONLY_SCOPE])
    db.add_all([rw, ro])
    db.flush()
    now = datetime.now(UTC)
    msgs = {
        "rw": Message(user_id=user.id, account_id=rw.id, gmail_id="g1", thread_id="t1", subject="A", status="processed", labels=["INBOX", "UNREAD"], received_at=now),
        "rw2": Message(user_id=user.id, account_id=rw.id, gmail_id="g2", thread_id="t1", subject="A again", status="processed", labels=["INBOX", "UNREAD"], received_at=now),
        "ro": Message(user_id=user.id, account_id=ro.id, gmail_id="g3", thread_id="t3", subject="B", status="processed", labels=["INBOX", "UNREAD"], received_at=now - timedelta(hours=1)),
    }
    db.add_all(msgs.values())
    db.commit()
    g = Gmail()
    monkeypatch.setattr(account_service, "provider_for", lambda a: g)
    return user, msgs, g


def labels(db, m):
    db.expire_all()
    return db.get(Message, m.id).labels


def test_opening_a_mail_marks_the_whole_conversation_read_in_gmail(client, db, world):
    user, msgs, g = world
    r = client.post("/api/v1/messages/read-state", headers=H(user), json={"message_ids": [str(msgs["rw"].id)], "unread": False}).json()
    assert r["in_gmail"] == 1 and r["sift_only"] == []
    assert g.calls == [("t1", (), ("UNREAD",))]
    assert "UNREAD" not in labels(db, msgs["rw"]) and "UNREAD" not in labels(db, msgs["rw2"])
    # opening it again costs nothing
    client.post("/api/v1/messages/read-state", headers=H(user), json={"message_ids": [str(msgs["rw"].id)], "unread": False})
    assert len(g.calls) == 1
    # and it can be marked unread again
    client.post("/api/v1/messages/read-state", headers=H(user), json={"message_ids": [str(msgs["rw"].id)], "unread": True})
    assert g.calls[-1] == ("t1", ("UNREAD",), ()) and "UNREAD" in labels(db, msgs["rw"])


def test_read_only_account_is_read_in_sift_without_asking(client, db, world):
    user, msgs, g = world
    r = client.post("/api/v1/messages/read-state", headers=H(user), json={"message_ids": [str(msgs["ro"].id)], "unread": False})
    assert r.status_code == 200 and r.json()["sift_only"] == ["ro@gmail.com"] and g.calls == []
    assert "UNREAD" not in labels(db, msgs["ro"])
    feed = client.get("/api/v1/messages", headers=H(user)).json()["items"]
    assert next(m for m in feed if m["id"] == str(msgs["ro"].id))["unread"] is False


def test_other_users_mail_is_refused(client, db, world):
    user, msgs, g = world
    other = User(email="x@gmail.com")
    db.add(other)
    db.commit()
    assert client.post("/api/v1/messages/read-state", headers=H(other), json={"message_ids": [str(msgs["rw"].id)], "unread": False}).status_code == 404


# ---- live events ------------------------------------------------------------------------------

def listen():
    url = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
    conn = psycopg.connect(url, autocommit=True)
    conn.execute(f"LISTEN {events.CHANNEL}")
    return conn


def heard(conn, wait=2.0):
    return [json.loads(n.payload) for n in conn.notifies(timeout=wait, stop_after=None)]


def test_events_go_out_only_when_the_change_commits(db, world):
    user, msgs, g = world
    conn = listen()
    try:
        with get_sessionmaker()() as s:
            events.mail_changed(s, user.id, [msgs["rw"].id])
            s.rollback()
        assert heard(conn, 0.5) == []
        with get_sessionmaker()() as s:
            events.mail_changed(s, user.id, [msgs["rw"].id])
            s.commit()
        got = heard(conn, 1.0)
        assert got and got[0]["type"] == "mail" and got[0]["u"] == str(user.id) and got[0]["ids"] == [str(msgs["rw"].id)]
    finally:
        conn.close()


def test_reading_on_one_device_reaches_the_other_devices_stream(client, db, world):
    """Device A reads a mail; device B's open stream gets the change (the hub routes per user)."""
    user, msgs, g = world
    loop = asyncio.new_event_loop()
    q: asyncio.Queue = asyncio.Queue()
    events.hub.subscribe(str(user.id), loop, q)
    try:
        time.sleep(0.5)  # the listener connects
        client.post("/api/v1/messages/read-state", headers=H(user), json={"message_ids": [str(msgs["rw"].id)], "unread": False})

        async def next_mail_event():
            while True:
                e = await asyncio.wait_for(q.get(), timeout=5)
                if e.get("type") == "mail":
                    return e
        e = loop.run_until_complete(next_mail_event())
        assert str(msgs["rw"].id) in e["ids"] and "u" not in e  # the user id isn't sent to the page
    finally:
        events.hub.unsubscribe(str(user.id), loop, q)
        loop.close()


def test_changes_made_in_gmail_itself_are_announced(db, world):
    user, msgs, g = world
    conn = listen()
    try:
        with get_sessionmaker()() as s:
            acc = s.get(GmailAccount, msgs["rw"].account_id)
            account_service.apply_label_changes(s, acc, [("g1", [], ["UNREAD"]), ("unknown", [], ["UNREAD"])])
            s.commit()
        got = heard(conn, 1.0)
        assert got and got[0]["ids"] == [str(msgs["rw"].id)]
        with get_sessionmaker()() as s:  # a change to what Sift already had is not news
            acc = s.get(GmailAccount, msgs["rw"].account_id)
            account_service.apply_label_changes(s, acc, [("g1", [], ["UNREAD"])])
            s.commit()
        assert heard(conn, 0.5) == []
    finally:
        conn.close()


def test_phones_get_one_silent_sync_for_a_burst_of_changes(db, world, fcm_sends, monkeypatch):
    user, msgs, g = world
    monkeypatch.setattr(events._PhoneSync, "enabled_in_tests", True)
    monkeypatch.setattr(events, "SYNC_GAP", 0.6)
    for _ in range(5):
        with get_sessionmaker()() as s:
            events.mail_changed(s, user.id, [msgs["rw"].id])
            s.commit()
    time.sleep(1.8)
    syncs = [m for m in fcm_sends if m.get("type") == "sync"]
    assert 1 <= len(syncs) <= 2, syncs


def test_sync_messages_are_silent_and_collapse():
    msg = fcm.build_message("tok", {"type": "sync"})["message"]
    assert msg["android"] == {"priority": "normal", "collapse_key": "sync"} and msg["data"] == {"type": "sync"}
    assert fcm.build_message("tok", {"type": "mail"})["message"]["android"]["priority"] == "high"


def test_live_stream_needs_a_sign_in(client):
    assert client.get("/api/v1/events").status_code == 401

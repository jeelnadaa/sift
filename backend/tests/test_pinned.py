"""Tests for Pinned Mails (pinned state, feed ordering, search filter, Ask Sift)."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import GmailAccount, Message, User
from app.security import create_token
from tests.test_pipeline import fake_llm, run, setup, with_key  # noqa: F401


def H(user: User) -> dict:
    return {"Authorization": f"Bearer {create_token(user)}"}


@pytest.fixture
def test_data(db, setup):
    user, account, provider, msgs = setup
    # Process messages: placement and recruiter are both feed messages (normal priority)
    out1 = run(db, account, provider, msgs["placement"])
    out2 = run(db, account, provider, msgs["recruiter"])
    m_old = db.get(Message, out1.message_id)
    m_new = db.get(Message, out2.message_id)
    # Ensure distinct received_at timestamps
    m_old.received_at = datetime.now(UTC) - timedelta(days=2)
    m_new.received_at = datetime.now(UTC) - timedelta(hours=1)
    db.commit()
    return user, account, m_old, m_new


def test_pin_toggle_and_explicit(client, test_data, db):
    user, _, m_old, _ = test_data
    headers = H(user)

    # 1. Initially not pinned
    res = client.get(f"/api/v1/messages/{m_old.id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["pinned"] is False

    # 2. Toggle pin on (empty body)
    r1 = client.post(f"/api/v1/messages/{m_old.id}/pin", headers=headers, json={})
    assert r1.status_code == 200
    assert r1.json()["pinned"] is True
    db.expire_all()
    assert db.get(Message, m_old.id).pinned is True

    # 3. Toggle pin off
    r2 = client.post(f"/api/v1/messages/{m_old.id}/pin", headers=headers, json={})
    assert r2.status_code == 200
    assert r2.json()["pinned"] is False
    db.expire_all()
    assert db.get(Message, m_old.id).pinned is False

    # 4. Explicit pin True
    r3 = client.post(f"/api/v1/messages/{m_old.id}/pin", headers=headers, json={"pinned": True})
    assert r3.status_code == 200
    assert r3.json()["pinned"] is True

    # 5. Explicit pin False
    r4 = client.post(f"/api/v1/messages/{m_old.id}/pin", headers=headers, json={"pinned": False})
    assert r4.status_code == 200
    assert r4.json()["pinned"] is False


def test_batch_pin_and_unpin(client, test_data, db):
    user, _, m_old, m_new = test_data
    headers = H(user)

    # Batch pin both
    r = client.post(
        "/api/v1/messages/pin",
        headers=headers,
        json={"message_ids": [str(m_old.id), str(m_new.id)], "pinned": True},
    )
    assert r.status_code == 200
    assert r.json() == {"pinned": True, "count": 2}
    db.expire_all()
    assert db.get(Message, m_old.id).pinned is True
    assert db.get(Message, m_new.id).pinned is True

    # Batch unpin both
    r2 = client.post(
        "/api/v1/messages/pin",
        headers=headers,
        json={"message_ids": [str(m_old.id), str(m_new.id)], "pinned": False},
    )
    assert r2.status_code == 200
    assert r2.json() == {"pinned": False, "count": 2}
    db.expire_all()
    assert db.get(Message, m_old.id).pinned is False
    assert db.get(Message, m_new.id).pinned is False


def test_feed_pinned_sort_order(client, test_data, db):
    user, _, m_old, m_new = test_data
    headers = H(user)

    # Default order: newer message first
    feed1 = client.get("/api/v1/messages", headers=headers).json()["items"]
    assert len(feed1) >= 2
    assert feed1[0]["id"] == str(m_new.id)
    assert feed1[1]["id"] == str(m_old.id)

    # Pin older message
    client.post(f"/api/v1/messages/{m_old.id}/pin", headers=headers, json={"pinned": True})

    # Pinned order: older message is now first
    feed2 = client.get("/api/v1/messages", headers=headers).json()["items"]
    assert feed2[0]["id"] == str(m_old.id)
    assert feed2[0]["pinned"] is True
    assert feed2[1]["id"] == str(m_new.id)
    assert feed2[1]["pinned"] is False


def test_feed_pagination_excludes_pinned_on_next_pages(client, test_data, db):
    user, _, m_old, m_new = test_data
    headers = H(user)

    # Pin older message
    client.post(f"/api/v1/messages/{m_old.id}/pin", headers=headers, json={"pinned": True})

    # Page 1 with limit 1: returns the pinned message (m_old)
    p1 = client.get("/api/v1/messages", headers=headers, params={"limit": 1}).json()
    assert len(p1["items"]) == 1
    assert p1["items"][0]["id"] == str(m_old.id)
    next_before = p1["next_before"]

    # Page 2 using before cursor: should return m_new, and NOT repeat m_old
    p2 = client.get("/api/v1/messages", headers=headers, params={"limit": 1, "before": next_before}).json()
    assert len(p2["items"]) == 1
    assert p2["items"][0]["id"] == str(m_new.id)


def test_search_is_pinned_filter(client, test_data, db):
    user, _, m_old, m_new = test_data
    headers = H(user)

    # Pin m_old only
    client.post(f"/api/v1/messages/{m_old.id}/pin", headers=headers, json={"pinned": True})

    # Search is:pinned
    res = client.get("/api/v1/search", headers=headers, params={"q": "is:pinned"})
    assert res.status_code == 200
    hits = res.json()["items"]
    assert len(hits) == 1
    assert hits[0]["id"] == str(m_old.id)

    # Search -is:pinned
    res_neg = client.get("/api/v1/search", headers=headers, params={"q": "-is:pinned"})
    assert res_neg.status_code == 200
    hits_neg = res_neg.json()["items"]
    assert any(h["id"] == str(m_new.id) for h in hits_neg)
    assert not any(h["id"] == str(m_old.id) for h in hits_neg)


def test_assistant_pin_and_unpin_action(test_data, db):
    user, _, m_old, _ = test_data
    from app.assistant import _preview, _run_one

    # 1. Preview pin
    step_pin = {"action": "pin_mail", "q": f'subject:"{m_old.subject}"'}
    prev_pin = _preview(db, user.id, step_pin, {})
    assert "Pin 1 mail" in prev_pin.text

    # 2. Run pin
    res_pin = _run_one(db, user.id, step_pin, uuid.uuid4())
    assert res_pin["text"] == "Pinned 1 mail"
    db.expire_all()
    assert db.get(Message, m_old.id).pinned is True

    # 3. Preview unpin
    step_unpin = {"action": "unpin_mail", "q": f'subject:"{m_old.subject}"'}
    prev_unpin = _preview(db, user.id, step_unpin, {})
    assert "Unpin 1 mail" in prev_unpin.text

    # 4. Run unpin
    res_unpin = _run_one(db, user.id, step_unpin, uuid.uuid4())
    assert res_unpin["text"] == "Unpinned 1 mail"
    db.expire_all()
    assert db.get(Message, m_old.id).pinned is False


def test_pin_user_isolation(client, test_data, db):
    user1, _, m_old, _ = test_data
    user2 = User(email="second_demo@demo.sift.local")
    db.add(user2)
    db.commit()

    headers2 = H(user2)
    assert client.post(f"/api/v1/messages/{m_old.id}/pin", headers=headers2, json={}).status_code == 404
    assert client.post("/api/v1/messages/pin", headers=headers2, json={"message_ids": [str(m_old.id)], "pinned": True}).status_code == 404

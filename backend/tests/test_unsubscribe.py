"""Tests for One-Tap Unsubscribe Hub and RFC 8058 execution (Phase C Item 3)."""
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from app import unsubscribe
from app.models import GmailAccount, Message, Rule, User
from app.security import create_token
from tests.test_pipeline import fake_llm, run, setup, with_key  # noqa: F401


def H(user: User) -> dict:
    return {"Authorization": f"Bearer {create_token(user)}"}


def test_parse_unsubscribe_headers():
    h = "<https://demo-marketing.local/unsub?u=999>, <mailto:unsub@demo-marketing.local?subject=unsubscribe>"
    url, mailto, is_post = unsubscribe.parse_unsubscribe_headers(h, "List-Unsubscribe=One-Click")
    assert url == "https://demo-marketing.local/unsub?u=999"
    assert mailto == "mailto:unsub@demo-marketing.local?subject=unsubscribe"
    assert is_post is True

    # Without post header
    url2, mailto2, is_post2 = unsubscribe.parse_unsubscribe_headers(h, None)
    assert url2 == "https://demo-marketing.local/unsub?u=999"
    assert mailto2 == "mailto:unsub@demo-marketing.local?subject=unsubscribe"
    assert is_post2 is False


def test_one_click_unsubscribe_execution_and_rule_generation(client, db, setup):
    user, account, _, _ = setup
    headers = H(user)

    msg = Message(
        user_id=user.id,
        account_id=account.id,
        gmail_id=f"g-{uuid.uuid4().hex[:12]}",
        thread_id=f"t-{uuid.uuid4().hex[:12]}",
        sender="promo@demo-retail.local",
        sender_name="Demo Retailer",
        subject="Weekend Big Sale",
        snippet="50% off all catalog items",
        received_at=datetime.now(UTC),
        unsubscribe_url="https://demo-retail.local/api/one-click-unsub",
        unsubscribe_mailto="mailto:unsub@demo-retail.local",
        unsubscribe_post=True,
        status="processed",
    )
    db.add(msg)
    db.commit()

    # Mock httpx POST for RFC 8058 one-click execution
    mock_res = MagicMock()
    mock_res.status_code = 200

    with patch("app.unsubscribe.httpx.post", return_value=mock_res) as mock_post:
        res = client.post(f"/api/v1/messages/{msg.id}/unsubscribe", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "one_click_posted"
        assert data["sender"] == "promo@demo-retail.local"
        assert data["rule_created"] is True

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "https://demo-retail.local/api/one-click-unsub"
        assert kwargs["data"] == {"List-Unsubscribe": "One-Click"}

    # Verify rule was added to silence future emails from this sender
    created_rule = db.scalar(select(Rule).where(Rule.user_id == user.id, Rule.name.like("Unsubscribed:%")))
    assert created_rule is not None
    assert "Unsubscribed:" in created_rule.name
    assert created_rule.conditions == {"field": "sender", "op": "equals", "value": "promo@demo-retail.local"}
    assert created_rule.action == {"type": "silence"}


def test_plain_url_unsubscribe_and_newsletters_list(client, db, setup):
    user, account, _, _ = setup
    headers = H(user)

    msg = Message(
        user_id=user.id,
        account_id=account.id,
        gmail_id=f"g-{uuid.uuid4().hex[:12]}",
        thread_id=f"t-{uuid.uuid4().hex[:12]}",
        sender="digest@demo-weekly.local",
        sender_name="Weekly Digest",
        subject="Issue #42",
        snippet="Tech newsletter roundup",
        received_at=datetime.now(UTC),
        list_id="weekly.demo-weekly.local",
        unsubscribe_url="https://demo-weekly.local/unsubscribe?id=abc",
        unsubscribe_post=False,
        status="processed",
    )
    db.add(msg)
    db.commit()

    # 1. Test newsletters list
    res_list = client.get("/api/v1/newsletters", headers=headers)
    assert res_list.status_code == 200
    nl_data = res_list.json()
    assert nl_data["total"] == 1
    item = nl_data["items"][0]
    assert item["email"] == "digest@demo-weekly.local"
    assert item["can_unsubscribe"] is True
    assert item["unsubscribe_url"] == "https://demo-weekly.local/unsubscribe?id=abc"

    # 2. Test unsubscribe on plain URL
    res_unsub = client.post(f"/api/v1/messages/{msg.id}/unsubscribe", headers=headers)
    assert res_unsub.status_code == 200
    res_json = res_unsub.json()
    assert res_json["status"] == "url_available"
    assert res_json["unsubscribe_url"] == "https://demo-weekly.local/unsubscribe?id=abc"
    assert res_json["rule_created"] is True


def test_unsubscribe_isolation(client, db, setup):
    user_a, account_a, _, _ = setup

    user_b = User(id=uuid.uuid4(), email="dana@demo.sift.local")
    db.add(user_b)
    db.flush()
    account_b = GmailAccount(
        id=uuid.uuid4(),
        user_id=user_b.id,
        email="dana@demo.sift.local",
        status="active",
    )
    db.add(account_b)
    db.commit()

    msg_a = Message(
        user_id=user_a.id,
        account_id=account_a.id,
        gmail_id=f"g-{uuid.uuid4().hex[:12]}",
        thread_id=f"t-{uuid.uuid4().hex[:12]}",
        sender="newsletter@demo.local",
        subject="User A Newsletter",
        unsubscribe_url="https://demo.local/unsub",
        status="processed",
    )
    db.add(msg_a)
    db.commit()

    # User B cannot unsubscribe User A's email
    res = client.post(f"/api/v1/messages/{msg_a.id}/unsubscribe", headers=H(user_b))
    assert res.status_code == 400

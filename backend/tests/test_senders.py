"""Tests for Senders View & Statistics (Phase C Item 2)."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import senders
from app.models import GmailAccount, Message, Rule, User
from app.security import create_token
from tests.test_pipeline import fake_llm, run, setup, with_key  # noqa: F401


def H(user: User) -> dict:
    return {"Authorization": f"Bearer {create_token(user)}"}


def _add_msg(db, user, account, sender, sender_name, subject, received_ago_mins=0, unread=False, urgent=False, has_attachment=False):
    msg = Message(
        user_id=user.id,
        account_id=account.id,
        gmail_id=f"g-{uuid.uuid4().hex[:12]}",
        thread_id=f"t-{uuid.uuid4().hex[:12]}",
        sender=sender,
        sender_name=sender_name,
        authenticated_domain=sender.split("@")[-1],
        subject=subject,
        snippet=f"Snippet for {subject}",
        received_at=datetime.now(UTC) - timedelta(minutes=received_ago_mins),
        labels=["INBOX", "UNREAD"] if unread else ["INBOX"],
        priority="urgent" if urgent else "normal",
        has_attachment=has_attachment,
        status="processed",
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def test_senders_list_aggregation_and_sorting(client, db, setup):
    user, account, _, _ = setup
    headers = H(user)

    # Sender 1: Alice (3 messages, 2 unread, 1 urgent, latest)
    _add_msg(db, user, account, "alice@demo.sift.local", "Alice Smith", "Hi there 1", received_ago_mins=10, unread=True, urgent=True)
    _add_msg(db, user, account, "alice@demo.sift.local", "Alice Smith", "Hi there 2", received_ago_mins=5, unread=True)
    _add_msg(db, user, account, "alice@demo.sift.local", "Alice Smith", "Hi there 3", received_ago_mins=1, unread=False, has_attachment=True)

    # Sender 2: Bob (5 messages, 0 unread)
    for i in range(5):
        _add_msg(db, user, account, "bob@demo-partners.local", "Bob Builder", f"Project update {i}", received_ago_mins=60 + i)

    # Sender 3: News (1 message, 1 unread)
    _add_msg(db, user, account, "news@demo-press.local", "Daily Press", "Today news", received_ago_mins=20, unread=True)

    # 1. Default sort by count desc: Bob (5) -> Alice (3) -> News (1)
    res = client.get("/api/v1/senders", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 3
    items = data["items"]
    assert items[0]["email"] == "bob@demo-partners.local"
    assert items[0]["total_count"] == 5
    assert items[1]["email"] == "alice@demo.sift.local"
    assert items[1]["total_count"] == 3
    assert items[1]["unread_count"] == 2
    assert items[1]["urgent_count"] == 1
    assert items[1]["attachment_count"] == 1
    assert items[1]["sample_subject"] == "Hi there 3"

    # 2. Sort by unread desc: Alice (2) -> News (1) -> Bob (0)
    res_unread = client.get("/api/v1/senders?sort_by=unread", headers=headers)
    assert res_unread.status_code == 200
    unreads = [x["email"] for x in res_unread.json()["items"]]
    assert unreads[0] == "alice@demo.sift.local"
    assert unreads[1] == "news@demo-press.local"
    assert unreads[2] == "bob@demo-partners.local"

    # 3. Sort by recent desc: Alice (1 min ago) -> News (20 mins ago) -> Bob (60 mins ago)
    res_recent = client.get("/api/v1/senders?sort_by=recent", headers=headers)
    assert res_recent.status_code == 200
    recents = [x["email"] for x in res_recent.json()["items"]]
    assert recents[0] == "alice@demo.sift.local"
    assert recents[1] == "news@demo-press.local"
    assert recents[2] == "bob@demo-partners.local"

    # 4. Filter by query q="bob"
    res_q = client.get("/api/v1/senders?q=bob", headers=headers)
    assert res_q.status_code == 200
    assert res_q.json()["total"] == 1
    assert res_q.json()["items"][0]["email"] == "bob@demo-partners.local"

    # 5. Filter by min_count=2
    res_min = client.get("/api/v1/senders?min_count=2", headers=headers)
    assert res_min.status_code == 200
    assert res_min.json()["total"] == 2  # Bob (5) and Alice (3)


def test_sender_detail_and_rules(client, db, setup):
    user, account, _, _ = setup
    headers = H(user)

    _add_msg(db, user, account, "support@demo-billing.local", "Billing Dept", "Invoice #101", received_ago_mins=15)
    _add_msg(db, user, account, "support@demo-billing.local", "Billing Dept", "Invoice #102", received_ago_mins=5, has_attachment=True)

    # Create a rule matching billing
    rule = Rule(
        user_id=user.id,
        name="Archive billing",
        position=1,
        enabled=True,
        conditions={"field": "sender", "op": "contains", "value": "demo-billing.local"},
        action={"type": "archive"},
    )
    db.add(rule)
    db.commit()

    # Get detail for support@demo-billing.local
    res = client.get("/api/v1/senders/support@demo-billing.local", headers=headers)
    assert res.status_code == 200
    detail = res.json()
    assert detail["email"] == "support@demo-billing.local"
    assert detail["name"] == "Billing Dept"
    assert detail["total_count"] == 2
    assert detail["attachment_count"] == 1
    assert len(detail["recent_messages"]) == 2
    assert len(detail["rules"]) == 1
    assert detail["rules"][0]["name"] == "Archive billing"


def test_senders_user_isolation(client, db, setup):
    user_a, account_a, _, _ = setup

    user_b = User(id=uuid.uuid4(), email="charlie@demo.sift.local")
    db.add(user_b)
    db.flush()
    account_b = GmailAccount(
        id=uuid.uuid4(),
        user_id=user_b.id,
        email="charlie@demo.sift.local",
        status="active",
    )
    db.add(account_b)
    db.commit()

    _add_msg(db, user_a, account_a, "partner_a@demo.local", "Partner A", "Secret A")
    _add_msg(db, user_b, account_b, "partner_b@demo.local", "Partner B", "Secret B")

    # User A only sees partner_a
    res_a = client.get("/api/v1/senders", headers=H(user_a))
    assert res_a.status_code == 200
    emails_a = [x["email"] for x in res_a.json()["items"]]
    assert "partner_a@demo.local" in emails_a
    assert "partner_b@demo.local" not in emails_a

    # User B cannot get details of partner_a
    res_b_detail = client.get("/api/v1/senders/partner_a@demo.local", headers=H(user_b))
    assert res_b_detail.status_code == 404

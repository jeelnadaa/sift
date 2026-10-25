import uuid
from datetime import UTC, datetime

import pytest
from app import notify, vip
from app.models import Message
from app.pipeline import Outcome, process_message
from app.security import create_token
from tests.test_pipeline import setup  # noqa: F401


def test_vip_sender_flow(client, setup, db):
    user, account, _, _ = setup
    token = create_token(user)

    vip_email = "mentor@vip-advisors.example"

    # Initially not VIP
    assert not vip.is_vip(db, user.id, vip_email)

    # Add VIP via API
    res = client.post(
        f"/api/v1/senders/{vip_email}/vip",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.json()["is_vip"] is True
    assert vip.is_vip(db, user.id, vip_email)

    # Check Senders API list
    # Add a message from this sender
    msg = Message(
        user_id=user.id,
        account_id=account.id,
        gmail_id="vip_msg_1",
        thread_id="t_vip_1",
        sender=vip_email,
        sender_name="Senior Advisor",
        subject="Important strategy meeting",
        snippet="Let us catch up today.",
        status="processed",
        priority="urgent",
        received_at=datetime.now(UTC),
    )
    db.add(msg)
    db.commit()

    list_res = client.get(
        "/api/v1/senders",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_res.status_code == 200
    senders = list_res.json()["items"]
    target = next((s for s in senders if s["email"] == vip_email), None)
    assert target is not None
    assert target["is_vip"] is True

    # Remove VIP via API
    del_res = client.delete(
        f"/api/v1/senders/{vip_email}/vip",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_res.status_code == 200
    assert del_res.json()["is_vip"] is False
    assert not vip.is_vip(db, user.id, vip_email)


def test_muted_thread_notification_suppression(client, setup, db):
    user, account, _, _ = setup
    token = create_token(user)

    thread_id = "t_noisy_discussions_99"

    # Mute thread via API
    mute_res = client.post(
        f"/api/v1/threads/{thread_id}/mute",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert mute_res.status_code == 200
    assert mute_res.json()["is_muted"] is True
    assert vip.is_thread_muted(db, user.id, thread_id)

    # Check muted status endpoint
    chk_res = client.get(
        f"/api/v1/threads/{thread_id}/muted",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert chk_res.status_code == 200
    assert chk_res.json()["is_muted"] is True

    # Incoming message in muted thread should suppress push notification
    msg = Message(
        user_id=user.id,
        account_id=account.id,
        gmail_id="noisy_msg_1",
        thread_id=thread_id,
        sender="noreply@noisy-updates.example",
        sender_name="Noisy Updates",
        subject="Discussion thread update #42",
        status="processed",
        priority="normal",
        received_at=datetime.now(UTC),
    )
    db.add(msg)
    db.commit()

    n = notify.notify_message(db, msg, account)
    assert n is None  # Notification suppressed for muted thread

    # Unmute thread via API
    unmute_res = client.delete(
        f"/api/v1/threads/{thread_id}/mute",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert unmute_res.status_code == 200
    assert unmute_res.json()["is_muted"] is False
    assert not vip.is_thread_muted(db, user.id, thread_id)

"""Tests for Attachments Hub (indexing, filtering, stats, isolation, API)."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import attachments
from app.models import GmailAccount, Message, MessageAttachment, User
from app.security import create_token
from tests.test_pipeline import fake_llm, run, setup, with_key  # noqa: F401


def H(user: User) -> dict:
    return {"Authorization": f"Bearer {create_token(user)}"}


def _make_msg(db, user, account, subject="Quarterly Report", sender="finance@demo.sift.local", has_attachment=True):
    msg = Message(
        user_id=user.id,
        account_id=account.id,
        gmail_id=f"g-{uuid.uuid4().hex[:12]}",
        thread_id=f"t-{uuid.uuid4().hex[:12]}",
        sender=sender,
        sender_name="Finance Team",
        subject=subject,
        snippet="Please find attached the financial review.",
        received_at=datetime.now(UTC),
        has_attachment=has_attachment,
        status="processed",
        priority="normal",
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def test_attachment_indexing_and_idempotency(db, setup):
    user, account, provider, _ = setup
    msg = _make_msg(db, user, account)

    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {
                "mimeType": "text/plain",
                "body": {"data": ""},
            },
            {
                "mimeType": "application/pdf",
                "filename": "Q3_Report.pdf",
                "body": {"attachmentId": "att-pdf-123", "size": 1048576},
            },
            {
                "mimeType": "image/png",
                "filename": "chart.png",
                "body": {"attachmentId": "att-png-456", "size": 204800},
                "headers": [{"name": "Content-ID", "value": "<chart-cid>"}]
            },
        ],
    }

    indexed = attachments.index_attachments(db, msg, account, payload)
    assert len(indexed) == 2
    filenames = {a.filename for a in indexed}
    assert "Q3_Report.pdf" in filenames
    assert "chart.png" in filenames

    # Idempotency check: indexing the same payload again creates 0 new rows
    second_run = attachments.index_attachments(db, msg, account, payload)
    assert len(second_run) == 0

    rows = list(db.scalars(select(MessageAttachment).where(MessageAttachment.message_id == msg.id)))
    assert len(rows) == 2


def test_attachments_api_list_and_filters(client, db, setup):
    user, account, _, _ = setup
    headers = H(user)
    msg = _make_msg(db, user, account, subject="Design Specs")

    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {
                "mimeType": "application/pdf",
                "filename": "spec.pdf",
                "body": {"attachmentId": "att-1", "size": 500_000},
            },
            {
                "mimeType": "image/jpeg",
                "filename": "diagram.jpeg",
                "body": {"attachmentId": "att-2", "size": 1_200_000},
            },
            {
                "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "filename": "budget.xlsx",
                "body": {"attachmentId": "att-3", "size": 80_000},
            },
            {
                "mimeType": "application/zip",
                "filename": "archive.zip",
                "body": {"attachmentId": "att-4", "size": 3_500_000},
            },
        ],
    }
    attachments.index_attachments(db, msg, account, payload)
    db.commit()

    # 1. List all attachments
    res = client.get("/api/v1/attachments", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 4
    assert len(data["items"]) == 4

    # Verify download_url is present
    for item in data["items"]:
        assert "download_url" in item
        assert "/api/v1/files/" in item["download_url"]

    # 2. Filter by type = pdf
    res_pdf = client.get("/api/v1/attachments?type=pdf", headers=headers)
    assert res_pdf.status_code == 200
    assert res_pdf.json()["total"] == 1
    assert res_pdf.json()["items"][0]["filename"] == "spec.pdf"

    # 3. Filter by type = image
    res_img = client.get("/api/v1/attachments?type=image", headers=headers)
    assert res_img.status_code == 200
    assert res_img.json()["total"] == 1
    assert res_img.json()["items"][0]["filename"] == "diagram.jpeg"

    # 4. Filter by type = sheet
    res_sheet = client.get("/api/v1/attachments?type=sheet", headers=headers)
    assert res_sheet.status_code == 200
    assert res_sheet.json()["total"] == 1
    assert res_sheet.json()["items"][0]["filename"] == "budget.xlsx"

    # 5. Filter by type = archive
    res_arc = client.get("/api/v1/attachments?type=archive", headers=headers)
    assert res_arc.status_code == 200
    assert res_arc.json()["total"] == 1
    assert res_arc.json()["items"][0]["filename"] == "archive.zip"

    # 6. Filter by min_size (>= 1 MB)
    res_size = client.get("/api/v1/attachments?min_size=1000000", headers=headers)
    assert res_size.status_code == 200
    assert res_size.json()["total"] == 2  # diagram.jpeg (1.2MB) and archive.zip (3.5MB)

    # 7. Search query q
    res_q = client.get("/api/v1/attachments?q=budget", headers=headers)
    assert res_q.status_code == 200
    assert res_q.json()["total"] == 1
    assert res_q.json()["items"][0]["filename"] == "budget.xlsx"


def test_attachment_stats(client, db, setup):
    user, account, _, _ = setup
    headers = H(user)
    msg = _make_msg(db, user, account)

    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {"mimeType": "application/pdf", "filename": "doc1.pdf", "body": {"attachmentId": "a1", "size": 100}},
            {"mimeType": "application/pdf", "filename": "doc2.pdf", "body": {"attachmentId": "a2", "size": 200}},
            {"mimeType": "image/png", "filename": "pic.png", "body": {"attachmentId": "a3", "size": 300}},
        ],
    }
    attachments.index_attachments(db, msg, account, payload)
    db.commit()

    res = client.get("/api/v1/attachments/stats", headers=headers)
    assert res.status_code == 200
    stats = res.json()
    assert stats["total_count"] == 3
    assert stats["total_size"] == 600
    assert stats["by_type"]["pdf"]["count"] == 2
    assert stats["by_type"]["pdf"]["size"] == 300
    assert stats["by_type"]["image"]["count"] == 1
    assert stats["by_type"]["image"]["size"] == 300


def test_attachment_isolation_between_users(client, db, setup):
    user_a, account_a, _, _ = setup

    # Create second user
    user_b = User(id=uuid.uuid4(), email="bob@demo.sift.local")
    db.add(user_b)
    db.flush()
    account_b = GmailAccount(
        id=uuid.uuid4(),
        user_id=user_b.id,
        email="bob@demo.sift.local",
        status="active",
    )
    db.add(account_b)
    db.commit()

    msg_a = _make_msg(db, user_a, account_a, subject="User A confidential")
    msg_b = _make_msg(db, user_b, account_b, subject="User B file")

    attachments.index_attachments(db, msg_a, account_a, {
        "parts": [{"mimeType": "application/pdf", "filename": "secret_a.pdf", "body": {"attachmentId": "a-1", "size": 100}}]
    })
    attachments.index_attachments(db, msg_b, account_b, {
        "parts": [{"mimeType": "application/pdf", "filename": "secret_b.pdf", "body": {"attachmentId": "b-1", "size": 100}}]
    })
    db.commit()

    # User A only sees their own
    res_a = client.get("/api/v1/attachments", headers=H(user_a))
    assert res_a.status_code == 200
    assert res_a.json()["total"] == 1
    assert res_a.json()["items"][0]["filename"] == "secret_a.pdf"

    # User B only sees their own
    res_b = client.get("/api/v1/attachments", headers=H(user_b))
    assert res_b.status_code == 200
    assert res_b.json()["total"] == 1
    assert res_b.json()["items"][0]["filename"] == "secret_b.pdf"

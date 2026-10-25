import uuid
from datetime import UTC, datetime

import pytest
from app.models import Folder, Message, Tag
from app.security import create_token
from tests.test_pipeline import setup  # noqa: F401


def test_trigram_fuzzy_search(client, setup, db):
    user, account, _, _ = setup
    token = create_token(user)

    # Insert test messages
    msg1 = Message(
        user_id=user.id,
        account_id=account.id,
        gmail_id="trgm1",
        thread_id="t_trgm1",
        sender="recruitment@acmecorp.com",
        sender_name="Acme Corp Recruiting",
        subject="Invitation to Software Engineering Interview",
        snippet="Please choose your interview slot.",
        status="processed",
        priority="urgent",
        received_at=datetime.now(UTC),
    )
    msg2 = Message(
        user_id=user.id,
        account_id=account.id,
        gmail_id="trgm2",
        thread_id="t_trgm2",
        sender="newsletter@weeklytechdigest.io",
        sender_name="Weekly Tech Digest",
        subject="The Future of Distributed Systems and Databases",
        snippet="Weekly updates on system design.",
        status="processed",
        priority="normal",
        received_at=datetime.now(UTC),
    )
    db.add_all([msg1, msg2])
    db.commit()

    # Exact search works
    res = client.get(
        "/api/v1/search?q=Engineering&fuzzy=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    assert any(item["subject"] == "Invitation to Software Engineering Interview" for item in data["items"])

    # Fuzzy typo search (e.g. "Engineerin" or "Acmecrp")
    res_typo = client.get(
        "/api/v1/search?q=Engineerin&fuzzy=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_typo.status_code == 200
    data_typo = res_typo.json()
    assert data_typo["total"] >= 1
    assert any("Engineering" in (item["subject"] or "") for item in data_typo["items"])


def test_trigram_suggest_fuzzy(client, setup, db):
    user, account, _, _ = setup
    token = create_token(user)

    msg = Message(
        user_id=user.id,
        account_id=account.id,
        gmail_id="trgm3",
        thread_id="t_trgm3",
        sender="support@anthropic.com",
        sender_name="Anthropic Support",
        subject="Your API key details",
        status="processed",
        priority="normal",
        received_at=datetime.now(UTC),
    )
    fld = Folder(id=uuid.uuid4(), user_id=user.id, name="Interviews", parent_id=None, position=0)
    tag = Tag(id=uuid.uuid4(), user_id=user.id, name="ActionRequired", color="#ff0000")
    db.add_all([msg, fld, tag])
    db.commit()

    # Typo: "anthrpc" should suggest "support@anthropic.com"
    res = client.get(
        "/api/v1/search/suggest?q=anthrpc",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    sug = res.json()
    assert any("anthropic" in s["detail"].lower() for s in sug["senders"])

    # Typo: "intrview" should suggest folder "Interviews"
    res_f = client.get(
        "/api/v1/search/suggest?q=intrview",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_f.status_code == 200
    sug_f = res_f.json()
    assert any(f["label"] == "Interviews" for f in sug_f["folders"])

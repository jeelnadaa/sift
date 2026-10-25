import os
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import app
from app.models import GmailAccount, Message, Opportunity, OpportunityEvent, Todo, User
from app.security import create_token, hash_password


@pytest.fixture
def auth_client(db: Session):
    user = User(email="cleanuptest@demo.sift.local", password_hash=hash_password("password123"))
    db.add(user)
    db.flush()

    account = GmailAccount(
        user_id=user.id,
        email="cleanuptest@demo.sift.local",
        status="active",
        history_id="100",
    )
    db.add(account)
    db.flush()

    token = create_token(user)
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client, user, account, db


def test_delete_opportunity_clears_message_extraction(auth_client):
    client, user, account, db = auth_client

    # 1. Create an opportunity
    opp = Opportunity(user_id=user.id, company="CleanCo", aliases=[])
    db.add(opp)
    db.flush()

    # 2. Create message linked to this opportunity
    msg = Message(
        user_id=user.id,
        account_id=account.id,
        gmail_id="clean_g1",
        thread_id="clean_t1",
        subject="Interview with CleanCo",
        sender="hr@cleanco.demo",
        extraction={"company": "CleanCo", "opportunity_id": str(opp.id), "summary": "CleanCo interview next week"},
    )
    db.add(msg)
    db.flush()

    # 3. Create an event linking the message
    event = OpportunityEvent(
        opportunity_id=opp.id,
        message_id=msg.id,
        kind="interview",
        matched_by="user",
        occurred_at=datetime.now(UTC),
    )
    db.add(event)
    db.commit()

    # Verify message detail returns opportunity_id
    detail_res = client.get(f"/api/v1/messages/{msg.id}")
    assert detail_res.status_code == 200
    assert detail_res.json()["opportunity_id"] == str(opp.id)

    # 4. Delete the opportunity
    del_res = client.delete(f"/api/v1/opportunities/{opp.id}")
    assert del_res.status_code == 204

    # 5. Check message detail again: opportunity_id must now be None!
    detail_res_after = client.get(f"/api/v1/messages/{msg.id}")
    assert detail_res_after.status_code == 200
    assert detail_res_after.json()["opportunity_id"] is None

    # Check database row directly
    db.expire_all()
    msg_db = db.get(Message, msg.id)
    assert "opportunity_id" not in (msg_db.extraction or {})


def test_delete_todo_clears_message_extraction(auth_client):
    client, user, account, db = auth_client

    # 1. Create message
    msg = Message(
        user_id=user.id,
        account_id=account.id,
        gmail_id="clean_g2",
        thread_id="clean_t2",
        subject="Action Needed: Submit Form",
        sender="admin@demo.sift.local",
        extraction={"summary": "Please submit form by Friday"},
    )
    db.add(msg)
    db.commit()

    # 2. Create a to-do linked to this message
    todo_res = client.post(
        "/api/v1/todos",
        json={
            "title": "Submit the CleanCo form",
            "message_id": str(msg.id),
        },
    )
    assert todo_res.status_code == 201
    todo_id = todo_res.json()["id"]

    # Verify message detail now has todo_id
    detail = client.get(f"/api/v1/messages/{msg.id}").json()
    assert detail["todo_id"] == todo_id

    # 3. Delete the to-do
    del_todo_res = client.delete(f"/api/v1/todos/{todo_id}")
    assert del_todo_res.status_code == 204

    # 4. Verify message detail no longer has todo_id
    detail_after = client.get(f"/api/v1/messages/{msg.id}").json()
    assert detail_after["todo_id"] is None

    # Check database row directly
    db.expire_all()
    msg_db = db.get(Message, msg.id)
    assert "todo_id" not in (msg_db.extraction or {})


def test_orphaned_references_self_heal_on_get_message(auth_client):
    client, user, account, db = auth_client

    ghost_opp_id = str(uuid.uuid4())
    ghost_todo_id = str(uuid.uuid4())

    msg = Message(
        user_id=user.id,
        account_id=account.id,
        gmail_id="clean_g3",
        thread_id="clean_t3",
        subject="Ghost references",
        sender="ghost@demo.sift.local",
        extraction={
            "company": "GhostCorp",
            "opportunity_id": ghost_opp_id,
            "todo_id": ghost_todo_id,
        },
    )
    db.add(msg)
    db.commit()

    # Call get_message
    detail = client.get(f"/api/v1/messages/{msg.id}").json()
    assert detail["opportunity_id"] is None
    assert detail["todo_id"] is None

    # Verify self-healing in database
    db.expire_all()
    msg_db = db.get(Message, msg.id)
    assert "opportunity_id" not in (msg_db.extraction or {})
    assert "todo_id" not in (msg_db.extraction or {})

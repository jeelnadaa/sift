"""Tests for Mail Notes (private annotations on emails)."""
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import GmailAccount, MailNote, Message, User
from app.notes import MAX_NOTE_LENGTH
from app.search import engine as search_engine
from app.search.query import parse
from app.security import create_token
from tests.test_pipeline import fake_llm, run, setup, with_key  # noqa: F401


def H(user: User) -> dict:
    return {"Authorization": f"Bearer {create_token(user)}"}


@pytest.fixture
def test_data(db, setup):
    user, account, provider, msgs = setup
    # Process messages through pipeline so they are stored as processed in Message table
    out1 = run(db, account, provider, msgs["recruiter"])
    out2 = run(db, account, provider, msgs["bank"])
    m1 = db.get(Message, out1.message_id)
    m2 = db.get(Message, out2.message_id)
    return user, account, m1, m2


def test_note_crud_lifecycle(client, test_data, db):
    user, _, m1, _ = test_data
    headers = H(user)

    # 1. Message detail initially has empty notes
    res = client.get(f"/api/v1/messages/{m1.id}", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["notes"] == []
    assert data["has_note"] is False
    assert data["notes_count"] == 0

    # 2. Create note 1
    create_res1 = client.post(
        f"/api/v1/messages/{m1.id}/notes",
        headers=headers,
        json={"body": "Follow up with recruiter on Thursday."},
    )
    assert create_res1.status_code == 201
    n1 = create_res1.json()
    assert n1["body"] == "Follow up with recruiter on Thursday."
    assert n1["message_id"] == str(m1.id)
    assert n1["id"]

    # 3. Create note 2
    create_res2 = client.post(
        f"/api/v1/messages/{m1.id}/notes",
        headers=headers,
        json={"body": "Salary range discussed: 120-140k."},
    )
    assert create_res2.status_code == 201
    n2 = create_res2.json()

    # 4. List notes endpoint
    list_res = client.get(f"/api/v1/messages/{m1.id}/notes", headers=headers)
    assert list_res.status_code == 200
    notes_list = list_res.json()["notes"]
    assert len(notes_list) == 2
    assert notes_list[0]["id"] == n1["id"]
    assert notes_list[1]["id"] == n2["id"]

    # 5. Message detail and list_messages reflect notes
    detail_res = client.get(f"/api/v1/messages/{m1.id}", headers=headers)
    assert detail_res.status_code == 200
    assert len(detail_res.json()["notes"]) == 2
    assert detail_res.json()["has_note"] is True
    assert detail_res.json()["notes_count"] == 2

    feed_res = client.get("/api/v1/messages", headers=headers)
    assert feed_res.status_code == 200
    feed_item = next(i for i in feed_res.json()["items"] if i["id"] == str(m1.id))
    assert feed_item["has_note"] is True
    assert feed_item["notes_count"] == 2

    # 6. Update note 1
    patch_res = client.patch(
        f"/api/v1/messages/{m1.id}/notes/{n1['id']}",
        headers=headers,
        json={"body": "Follow up with recruiter on Friday morning."},
    )
    assert patch_res.status_code == 200
    updated_n1 = patch_res.json()
    assert updated_n1["body"] == "Follow up with recruiter on Friday morning."
    assert updated_n1["id"] == n1["id"]

    # Verify update in DB
    db_note = db.get(MailNote, uuid.UUID(n1["id"]))
    assert db_note.body == "Follow up with recruiter on Friday morning."

    # 7. Delete note 1
    del_res = client.delete(f"/api/v1/messages/{m1.id}/notes/{n1['id']}", headers=headers)
    assert del_res.status_code == 200
    assert del_res.json() == {"ok": True}

    # Verify only note 2 remains
    remaining_res = client.get(f"/api/v1/messages/{m1.id}/notes", headers=headers)
    remaining = remaining_res.json()["notes"]
    assert len(remaining) == 1
    assert remaining[0]["id"] == n2["id"]


def test_note_validation(client, test_data):
    user, _, m1, _ = test_data
    headers = H(user)

    # Empty body
    r = client.post(f"/api/v1/messages/{m1.id}/notes", headers=headers, json={"body": ""})
    assert r.status_code == 422

    # Whitespace only
    r = client.post(f"/api/v1/messages/{m1.id}/notes", headers=headers, json={"body": "   \n   "})
    assert r.status_code == 422

    # Note exceeding maximum length
    r = client.post(
        f"/api/v1/messages/{m1.id}/notes",
        headers=headers,
        json={"body": "a" * (MAX_NOTE_LENGTH + 1)},
    )
    assert r.status_code == 422


def test_note_security_and_isolation(client, test_data, db):
    user1, _, m1, m2 = test_data
    headers1 = H(user1)

    # Create note by user 1 on m1
    res = client.post(
        f"/api/v1/messages/{m1.id}/notes",
        headers=headers1,
        json={"body": "Private confidential note"},
    )
    assert res.status_code == 201
    note_id = res.json()["id"]

    # Setup user 2
    user2 = User(email="other_demo_user@demo.sift.local")
    db.add(user2)
    db.commit()
    headers2 = H(user2)

    # User 2 cannot access notes on user 1's message (returns 404)
    assert client.get(f"/api/v1/messages/{m1.id}/notes", headers=headers2).status_code == 404
    assert client.post(f"/api/v1/messages/{m1.id}/notes", headers=headers2, json={"body": "Hack"}).status_code == 404
    assert client.patch(f"/api/v1/messages/{m1.id}/notes/{note_id}", headers=headers2, json={"body": "Hack"}).status_code == 404
    assert client.delete(f"/api/v1/messages/{m1.id}/notes/{note_id}", headers=headers2).status_code == 404

    # User 1 cannot access note with mismatched message id
    assert client.patch(f"/api/v1/messages/{m2.id}/notes/{note_id}", headers=headers1, json={"body": "Mismatched"}).status_code == 404
    assert client.delete(f"/api/v1/messages/{m2.id}/notes/{note_id}", headers=headers1).status_code == 404


def test_has_note_search_filter(client, test_data, db):
    user, _, m1, m2 = test_data
    headers = H(user)

    # Initially has:note matches 0
    search_res = client.get("/api/v1/search", headers=headers, params={"q": "has:note"})
    assert search_res.status_code == 200
    assert len(search_res.json()["items"]) == 0

    # Add note to m1
    client.post(f"/api/v1/messages/{m1.id}/notes", headers=headers, json={"body": "A critical note"})

    # Now has:note matches m1 only
    search_res = client.get("/api/v1/search", headers=headers, params={"q": "has:note"})
    assert search_res.status_code == 200
    items = search_res.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == str(m1.id)


def test_assistant_note_mail_action(client, test_data, db):
    user, _, m1, _ = test_data
    from app.assistant import _preview, _run_one
    from app.models import MailNote

    step = {"action": "note_mail", "q": f'subject:"{m1.subject}"', "text": "Note from AI assistant"}
    preview = _preview(db, user.id, step, {})
    assert "Add note to 1 mail" in preview.text
    res = _run_one(db, user.id, step, uuid.uuid4())
    assert res["text"] == "Added note to 1 mail"
    assert res["link"]["q"] == "has:note"

    notes = list(db.scalars(select(MailNote).where(MailNote.message_id == m1.id)))
    assert len(notes) == 1
    assert notes[0].body == "Note from AI assistant"

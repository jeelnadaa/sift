"""Editing timelines and to-dos by hand: sections placed by their date and time, reminders for
sections in the future, renaming companies, and to-do edits."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import Message, Opportunity, OpportunityEvent, Reminder, User
from tests.test_rule_tools import H


@pytest.fixture
def owner(db, keys):
    user = User(email="owner@gmail.com")
    db.add(user)
    db.commit()
    return user


def make_opp(client, user, company="Acme Corp"):
    return client.post("/api/v1/opportunities", headers=H(user), json={"company": company}).json()


def at(days: float) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def test_sections_are_placed_by_their_date_and_time(client, db, owner):
    o = make_opp(client, owner)
    url = f"/api/v1/opportunities/{o['id']}/sections"
    client.post(url, headers=H(owner), json={"kind": "interview", "title": "Round 2", "at": at(5)})
    r = client.post(url, headers=H(owner), json={"kind": "registration", "title": "Registered on portal", "note": "Roll no. used", "at": at(-3)}).json()
    titles = [e["title"] for e in r["timeline"]]
    assert titles == ["Registered on portal", "Round 2"], "an earlier date goes earlier, whatever order they were added in"
    first = r["timeline"][0]
    assert first["manual"] is True and first["note"] == "Roll no. used" and first["message_id"] is None
    # moving a section's date moves it
    r = client.patch(f"/api/v1/opportunities/{o['id']}/events/{first['id']}", headers=H(owner), json={"at": at(9)}).json()
    assert [e["title"] for e in r["timeline"]] == ["Round 2", "Registered on portal"]


def test_reminded_section_becomes_the_deadline_with_reminders(client, db, owner):
    o = make_opp(client, owner)
    r = client.post(f"/api/v1/opportunities/{o['id']}/sections", headers=H(owner),
                    json={"kind": "interview", "title": "Final interview", "at": at(3), "remind": True}).json()
    assert r["deadline"] is not None
    keys = {x.dedupe_key.rsplit(":", 1)[-1] for x in db.scalars(select(Reminder))}
    assert len(keys) == 2  # 24 h and 2 h before
    sec = r["timeline"][0]
    # turning the reminder off removes the pending reminders
    client.patch(f"/api/v1/opportunities/{o['id']}/events/{sec['id']}", headers=H(owner), json={"remind": False})
    db.expire_all()
    assert db.scalars(select(Reminder)).all() == []
    # and removing the section clears what it set
    r = client.delete(f"/api/v1/opportunities/{o['id']}/events/{sec['id']}", headers=H(owner)).json()
    assert r["timeline"] == [] and r["deadline"] is None


def test_a_mail_on_the_timeline_keeps_its_subject_and_time(client, db, owner):
    from app.models import GmailAccount
    acc = GmailAccount(user_id=owner.id, email="me@gmail.com", status="active")
    db.add(acc)
    db.flush()
    m = Message(user_id=owner.id, account_id=acc.id, gmail_id="g1", thread_id="t1", subject="Test link", status="processed",
                received_at=datetime.now(UTC) - timedelta(days=1), extraction={"opportunity_id": "x"})
    db.add(m)
    db.commit()
    o = make_opp(client, owner)
    client.post(f"/api/v1/opportunities/{o['id']}/events", headers=H(owner), json={"message_id": str(m.id)})
    ev = db.scalar(select(OpportunityEvent))
    url = f"/api/v1/opportunities/{o['id']}/events/{ev.id}"
    assert client.patch(url, headers=H(owner), json={"title": "renamed"}).status_code == 422
    assert client.patch(url, headers=H(owner), json={"kind": "assessment"}).json()["timeline"][0]["kind"] == "assessment"
    client.delete(url, headers=H(owner))
    db.expire_all()
    assert db.get(Message, m.id) is not None and "opportunity_id" not in (db.get(Message, m.id).extraction or {})


def test_rename_company_and_check_input(client, db, owner):
    o = make_opp(client, owner)
    assert client.patch(f"/api/v1/opportunities/{o['id']}", headers=H(owner), json={"company": "Acme Corporation"}).json()["company"] == "Acme Corporation"
    bad = client.post(f"/api/v1/opportunities/{o['id']}/sections", headers=H(owner), json={"title": "x", "at": "2026-11-01T10:00:00"})
    assert bad.status_code == 422  # a time without a time zone is refused
    assert client.post(f"/api/v1/opportunities/{o['id']}/sections", headers=H(owner), json={"title": "", "at": at(1)}).status_code == 422


def test_other_users_cannot_touch_a_timeline(client, db, owner):
    o = make_opp(client, owner)
    other = User(email="x@gmail.com")
    db.add(other)
    db.commit()
    assert client.post(f"/api/v1/opportunities/{o['id']}/sections", headers=H(other), json={"title": "x", "at": at(1)}).status_code == 404
    sec = client.post(f"/api/v1/opportunities/{o['id']}/sections", headers=H(owner), json={"title": "mine", "at": at(1)}).json()["timeline"][0]
    other_opp = make_opp(client, other, "Globex")
    assert client.delete(f"/api/v1/opportunities/{other_opp['id']}/events/{sec['id']}", headers=H(other)).status_code == 404
    assert db.get(OpportunityEvent, uuid.UUID(sec["id"])) is not None


def test_todos_can_be_added_renamed_and_rescheduled(client, db, owner):
    t = client.post("/api/v1/todos", headers=H(owner), json={"title": "Send CV", "due_at": at(2)}).json()
    r = client.patch(f"/api/v1/todos/{t['id']}", headers=H(owner), json={"title": "Send updated CV", "due_at": at(4)}).json()
    assert r["title"] == "Send updated CV" and r["due_at"].startswith((datetime.now(UTC) + timedelta(days=4)).date().isoformat())
    assert client.patch(f"/api/v1/todos/{t['id']}", headers=H(owner), json={"clear_due": True}).json()["due_at"] is None
    assert db.scalars(select(Reminder)).all() == []

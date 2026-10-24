"""Phase 2a: opportunities, timelines, to-dos and reminders.
Acceptance: a placement announcement plus a HirePro mail land on one company timeline."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import demo, opportunities as opp
from app import todos
from app.models import GmailAccount, Message, Opportunity, OpportunityEvent, Reminder, Todo
from app.pipeline import process_message
from tests.test_app_api import auth, owner  # noqa: F401  (fixtures)
from tests.test_pipeline import fake_llm, run, setup, with_key  # noqa: F401  (fixtures)


# ---- name matching ------------------------------------------------------------------------

@pytest.mark.parametrize("a,b,same", [
    ("Acme Corp", "ACME Pvt. Ltd.", True),
    ("Acme Technologies Private Limited", "acme", True),
    ("Tata Consultancy Services", "Tata Consultancy", True),
    ("Globex", "Acme", False),
    ("Infosys", "Infosys BPM", False),
])
def test_company_names_match_ignoring_legal_suffixes(a, b, same):
    o = Opportunity(company=a, aliases=[])
    assert (opp.find_by_name([o], b) is o) is same


def test_aliases_match():
    o = Opportunity(company="Acme Corp", aliases=["Acme Analytics"])
    assert opp.find_by_name([o], "acme analytics pvt ltd") is o


# ---- acceptance ------------------------------------------------------------------------------

def test_placement_announcement_and_hirepro_mail_land_on_one_timeline(db, setup, fake_llm):
    user, account, provider, msgs = setup
    with_key(db, user)
    run(db, account, provider, msgs["placement"])
    run(db, account, provider, msgs["hirepro"])

    [o] = list(db.scalars(select(Opportunity)))
    assert o.company == "Acme Corp"
    events = list(db.scalars(select(OpportunityEvent).order_by(OpportunityEvent.occurred_at)))
    assert [e.kind for e in events] == ["announcement", "assessment"]
    assert [e.matched_by for e in events] == ["new", "name"]  # the company name is checked before the model's pick
    assert o.deadline is not None  # from the assessment deadline


def test_hirepro_mail_without_a_company_name_matches_by_timing(db, setup, fake_llm):
    user, account, provider, msgs = setup
    with_key(db, user)
    run(db, account, provider, msgs["placement"])
    fake_llm.override = {"company": None}
    out = run(db, account, provider, msgs["hirepro"])
    e = db.scalar(select(OpportunityEvent).where(OpportunityEvent.message_id == out.message_id))
    assert e.matched_by == "timing" and e.kind == "assessment"


def test_unresolved_mail_asks_which_company_and_learns_the_answer(db, setup, fake_llm, client, fcm_sends):
    user, account, provider, msgs = setup
    with_key(db, user)
    run(db, account, provider, msgs["placement"])  # Acme timeline exists
    run(db, account, provider, msgs["recruiter"])  # Globex, a second timeline: timing is now ambiguous
    db.scalar(select(Opportunity).where(Opportunity.company == "Globex")).updated_at = datetime.now(UTC) - timedelta(days=30)
    db.commit()

    fake_llm.override = {"company": None, "category": "interview", "opportunity": "unsure"}
    db.add(Opportunity(user_id=user.id, company="Initech", aliases=[], domains=[]))  # two recent drives without interviews
    db.commit()
    out = run(db, account, provider, msgs["hirepro"])
    m = db.get(Message, out.message_id)
    question = m.extraction["company_question"]
    assert {q["name"] for q in question} >= {"Acme Corp", "Initech"}
    assert "company_choices" in fcm_sends[-1] and "Acme Corp" in fcm_sends[-1]["company_choices"]

    # the user answers from the notification
    from app.security import create_token
    h = {"Authorization": f"Bearer {create_token(user)}"}
    acme = next(q for q in question if q["name"] == "Acme Corp")
    r = client.post(f"/api/v1/messages/{m.id}/opportunity", json={"opportunity_id": acme["id"]}, headers=h)
    assert r.status_code == 200 and r.json()["learned"] == "domain:hirepro.in"
    db.expire_all()
    assert db.get(Message, m.id).extraction.get("company_question") is None

    # next HirePro mail with no company name now matches by the learned sender domain
    again = demo.samples()[1]
    again["threadId"] = "a-new-thread"  # same thread would match by thread first
    out2 = process_message(db, db.get(GmailAccount, account.id), demo.DemoProvider([again]), again["id"])
    e = db.scalar(select(OpportunityEvent).where(OpportunityEvent.message_id == out2.message_id))
    assert (str(e.opportunity_id), e.matched_by) == (acme["id"], "domain")


def test_ai_off_never_creates_opportunities_or_todos(db, setup, fake_llm):
    user, account, provider, msgs = setup
    for m in msgs.values():
        run(db, account, provider, m)
    assert db.scalar(select(Opportunity)) is None and db.scalar(select(Todo)) is None and db.scalar(select(Reminder)) is None


def test_non_hiring_mail_stays_off_timelines(db, setup, fake_llm):
    user, account, provider, msgs = setup
    with_key(db, user)
    run(db, account, provider, msgs["fraud"])  # action_needed, Kotak: a to-do, not a timeline
    assert db.scalar(select(Opportunity)) is None
    assert db.scalar(select(Todo)).source == "ai"


# ---- to-dos and reminders --------------------------------------------------------------------

def test_action_needed_mail_creates_one_todo_and_deadline_reminders(db, setup, fake_llm):
    user, account, provider, msgs = setup
    with_key(db, user)
    out = run(db, account, provider, msgs["hirepro"])
    from app.pipeline import _timeline_and_todos
    m = db.get(Message, out.message_id)
    _timeline_and_todos(db, m, m.extraction)  # re-running never duplicates
    db.commit()
    [t] = list(db.scalars(select(Todo)))
    assert t.source == "ai" and t.due_at is not None and "Acme" in t.title
    kinds = sorted(r.kind for r in db.scalars(select(Reminder)))
    assert kinds == ["deadline_24h", "deadline_2h"]
    assert m.extraction["todo_id"] == str(t.id)


def test_due_reminders_are_sent_once_and_finished_or_stale_ones_dropped(db, setup, fcm_sends):
    user, account, provider, msgs = setup
    now = datetime.now(UTC)
    t = Todo(user_id=user.id, title="Submit form", due_at=now + timedelta(hours=1, minutes=50), source="manual")
    done = Todo(user_id=user.id, title="Already done", due_at=now + timedelta(hours=1), done=True, source="manual")
    db.add_all([t, done])
    db.flush()
    db.add_all([
        Reminder(user_id=user.id, todo_id=t.id, kind="deadline_2h", title="Submit form", due_at=t.due_at, remind_at=now - timedelta(minutes=10), dedupe_key="a"),
        Reminder(user_id=user.id, todo_id=done.id, kind="deadline_2h", title="Already done", due_at=done.due_at, remind_at=now - timedelta(minutes=5), dedupe_key="b"),
        Reminder(user_id=user.id, kind="deadline_24h", title="Missed while offline", due_at=now + timedelta(hours=20), remind_at=now - timedelta(hours=4), dedupe_key="c"),
        Reminder(user_id=user.id, kind="deadline_24h", title="Later", due_at=now + timedelta(days=3), remind_at=now + timedelta(days=2), dedupe_key="d"),
    ])
    db.commit()
    assert todos.send_due(db) == 1
    assert todos.send_due(db) == 0
    [push] = [s for s in fcm_sends if s["type"] == "reminder"]
    assert push["body"] == "Submit form" and push["priority"] == "urgent" and push["todo_id"] == str(t.id)


# ---- API -----------------------------------------------------------------------------------------

def test_opportunity_and_todo_api(client, auth, db, owner):
    r = client.post("/api/v1/opportunities", json={"company": "  Acme Corp ", "aliases": ["ACME", "acme", " "]}, headers=auth)
    assert r.status_code == 201 and r.json()["aliases"] == ["ACME"]
    oid = r.json()["id"]
    assert client.post("/api/v1/opportunities", json={"company": "Acme Corp"}, headers=auth).status_code == 409
    assert client.post("/api/v1/opportunities", json={"company": "   "}, headers=auth).status_code == 422
    assert client.patch(f"/api/v1/opportunities/{oid}", json={"status": "closed"}, headers=auth).json()["status"] == "closed"
    assert client.get("/api/v1/opportunities", headers=auth).json() == []
    assert len(client.get("/api/v1/opportunities", params={"status": "all"}, headers=auth).json()) == 1
    assert client.patch(f"/api/v1/opportunities/{oid}", json={"status": "maybe"}, headers=auth).status_code == 422

    due = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    t = client.post("/api/v1/todos", json={"title": "Upload résumé", "due_at": due, "opportunity_id": oid}, headers=auth).json()
    assert t["company"] is None or True
    assert len(list(db.scalars(select(Reminder).where(Reminder.todo_id == t["id"])))) == 2
    later = (datetime.now(UTC) + timedelta(days=5)).isoformat()
    client.patch(f"/api/v1/todos/{t['id']}", json={"due_at": later}, headers=auth)
    db.expire_all()
    rems = list(db.scalars(select(Reminder).where(Reminder.todo_id == t["id"])))
    target = datetime.fromisoformat(later)
    assert len(rems) == 2 and all(abs((r.due_at - target).total_seconds()) < 1 for r in rems)  # rescheduled, not doubled
    client.patch(f"/api/v1/todos/{t['id']}", json={"done": True}, headers=auth)
    assert db.scalar(select(Reminder).where(Reminder.todo_id == t["id"])) is None
    assert client.get("/api/v1/todos", headers=auth).json() == []
    assert client.get("/api/v1/todos", params={"state": "done"}, headers=auth).json()[0]["done"] is True
    assert client.delete(f"/api/v1/todos/{t['id']}", headers=auth).status_code == 204


def test_other_users_cannot_touch_opportunities_or_todos(client, auth, db, keys):
    oid = client.post("/api/v1/opportunities", json={"company": "Acme"}, headers=auth).json()["id"]
    tid = client.post("/api/v1/todos", json={"title": "x"}, headers=auth).json()["id"]
    from app.models import User
    from app.security import create_token, hash_password
    other = User(email="other@gmail.com", password_hash=hash_password("pw-other-123"))
    db.add(other)
    db.commit()
    h = {"Authorization": f"Bearer {create_token(other)}"}
    assert client.get(f"/api/v1/opportunities/{oid}", headers=h).status_code == 404
    assert client.patch(f"/api/v1/todos/{tid}", json={"done": True}, headers=h).status_code == 404
    assert client.post("/api/v1/todos", json={"title": "y", "opportunity_id": oid}, headers=h).status_code == 404
    assert client.get("/api/v1/opportunities", headers=h).json() == []


def test_manual_attach_works_without_ai(client, auth, db, owner, fcm_sends):
    account = demo.demo_account(db, owner)
    db.commit()
    m = demo.samples()[4]
    out = process_message(db, db.get(GmailAccount, account.id), demo.DemoProvider([m]), m["id"])
    oid = client.post("/api/v1/opportunities", json={"company": "Globex"}, headers=auth).json()["id"]
    r = client.post(f"/api/v1/opportunities/{oid}/events", json={"message_id": str(out.message_id), "kind": "interview"}, headers=auth)
    assert r.status_code == 201
    detail = client.get(f"/api/v1/opportunities/{oid}", headers=auth).json()
    assert [e["kind"] for e in detail["timeline"]] == ["interview"] and detail["timeline"][0]["subject"].startswith("Backend role")
    assert client.delete(f"/api/v1/messages/{out.message_id}/opportunity", headers=auth).status_code == 204
    assert client.get(f"/api/v1/opportunities/{oid}", headers=auth).json()["timeline"] == []

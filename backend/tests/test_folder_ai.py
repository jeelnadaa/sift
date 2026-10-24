"""Folders that file and sort themselves with the AI, AI tasks over a folder, per-task token use,
the starter setup, sign-up, and the data reset."""
import pytest
from sqlalchemy import func, select

from app import folder_ai, starter
from app.models import (
    AiTask, Folder, FolderItem, GmailAccount, LlmCredential, Message, Opportunity, Rule, Todo, TokenUsage, User,
)
from tests.test_pipeline import fake_llm, run, setup, with_key  # noqa: F401  (fixtures)
from tests.test_rule_tools import H


def folder(db, user, name, parent=None):
    return db.scalar(select(Folder).where(Folder.user_id == user.id, Folder.name == name,
                                          Folder.parent_id == (parent.id if parent else None)) if parent else
                     select(Folder).where(Folder.user_id == user.id, Folder.name == name, Folder.parent_id.is_(None)))


def threads_in(db, f):
    return {t for (t,) in db.execute(select(FolderItem.thread_id).where(FolderItem.folder_id == f.id))}


def stored(db, account, kind):
    return db.scalar(select(Message).where(Message.account_id == account.id, Message.gmail_id.like(f"demo-{kind}-%")))


# ---- starter setup and new mail ------------------------------------------------------------------

def test_starter_setup_adds_placements_folder_and_bank_rule_once(db, setup):
    user, *_ = setup
    starter.setup(db, user)
    starter.setup(db, user)
    db.commit()
    places = list(db.scalars(select(Folder).where(Folder.user_id == user.id, Folder.name == "Placements")))
    assert len(places) == 1 and places[0].auto_sort == "company" and places[0].ai_rule["timeline"] is True
    assert "assessment_link" in places[0].ai_rule["categories"]
    assert db.scalar(select(func.count()).select_from(Rule).where(Rule.user_id == user.id)) == 1


def test_placement_mail_is_filed_and_sorted_into_a_company_subfolder(db, setup, fake_llm):
    user, account, provider, msgs = setup
    starter.setup(db, user)
    with_key(db, user)
    run(db, account, provider, msgs["placement"])
    run(db, account, provider, msgs["hirepro"])
    run(db, account, provider, msgs["recruiter"])
    places = folder(db, user, "Placements")
    acme = folder(db, user, "Acme Corp", places)
    assert acme is not None, "the company subfolder is created on its own"
    assert {stored(db, account, "placement").thread_id, stored(db, account, "hirepro").thread_id} <= threads_in(db, acme)
    assert threads_in(db, places) & threads_in(db, acme) == set(), "sorted mail leaves the parent folder"
    globex = folder(db, user, "Globex", places)
    assert globex is not None and stored(db, account, "recruiter").thread_id in threads_in(db, globex)
    # company sorting needs no extra AI call
    assert not any(c["system"].startswith("You file one email") for c in fake_llm.calls)


def test_without_ai_nothing_is_filed_by_the_ai_rule(db, setup, fake_llm):
    user, account, provider, msgs = setup
    starter.setup(db, user)
    run(db, account, provider, msgs["placement"])
    assert fake_llm.calls == []
    assert db.scalar(select(func.count()).select_from(FolderItem)) == 0


def test_filing_by_hand_into_a_sender_sorted_folder(client, db, setup, fake_llm):
    user, account, provider, msgs = setup
    run(db, account, provider, msgs["bank"])
    bank = stored(db, account, "bank")
    f = client.post("/api/v1/folders", headers=H(user), json={"name": "Money"}).json()
    r = client.patch(f"/api/v1/folders/{f['id']}", headers=H(user), json={"auto_sort": "sender"})
    assert r.status_code == 200 and r.json()["auto_sort"] == "sender"
    client.post(f"/api/v1/folders/{f['id']}/threads", headers=H(user), json={"message_ids": [str(bank.id)]})
    money = db.get(Folder, __import__("uuid").UUID(f["id"]))
    child = db.scalar(select(Folder).where(Folder.parent_id == money.id))
    assert child is not None and bank.thread_id in threads_in(db, child) and not threads_in(db, money)


def test_ai_sorting_needs_an_instruction_and_uses_one_small_call(client, db, setup, fake_llm):
    user, account, provider, msgs = setup
    with_key(db, user)
    f = client.post("/api/v1/folders", headers=H(user), json={"name": "College"}).json()
    assert client.patch(f"/api/v1/folders/{f['id']}", headers=H(user), json={"auto_sort": "ai"}).status_code == 422
    assert client.patch(f"/api/v1/folders/{f['id']}", headers=H(user), json={"auto_sort": "ai", "auto_sort_instruction": "one folder per course"}).status_code == 200
    db.add(Message(user_id=user.id, account_id=account.id, gmail_id="c1", thread_id="tc1", subject="DBMS lab moved", sender="prof@univ.edu", status="processed"))
    db.commit()
    m = db.scalar(select(Message).where(Message.gmail_id == "c1"))
    client.post(f"/api/v1/folders/{f['id']}/threads", headers=H(user), json={"message_ids": [str(m.id)]})
    sorts = [c for c in fake_llm.calls if c["system"].startswith("You file one email")]
    assert len(sorts) == 1 and "one folder per course" in sorts[0]["prompt"]
    assert db.scalar(select(Folder).where(Folder.name == "Course Updates")) is not None
    assert db.scalar(select(TokenUsage.purpose).where(TokenUsage.purpose == "sort")) == "sort"


# ---- AI tasks over a folder ------------------------------------------------------------------------

def _old_mail_in(client, db, setup, name):
    """Mail that arrived while AI was off, filed by hand into a folder; then a key is added."""
    user, account, provider, msgs = setup
    for k in ("placement", "hirepro", "recruiter"):
        run(db, account, provider, msgs[k])
    f = client.post("/api/v1/folders", headers=H(user), json={"name": name}).json()
    ids = [str(m.id) for m in db.scalars(select(Message).where(Message.account_id == account.id))]
    client.post(f"/api/v1/folders/{f['id']}/threads", headers=H(user), json={"message_ids": ids})
    with_key(db, user)
    return user, f


def test_timelines_task_reads_old_mail_once_and_builds_timelines(client, db, setup, fake_llm):
    user, f = _old_mail_in(client, db, setup, "Old placements")
    r = client.post(f"/api/v1/folders/{f['id']}/ai-tasks", headers=H(user), json={"kind": "timelines"})
    assert r.status_code == 202
    task_id = __import__("uuid").UUID(r.json()["id"])
    assert client.post(f"/api/v1/folders/{f['id']}/ai-tasks", headers=H(user), json={"kind": "todos"}).status_code == 409  # one at a time
    folder_ai.run_task(task_id)
    db.expire_all()
    t = db.get(AiTask, task_id)
    assert t.status == "done" and t.total == 3 and t.done == 3 and t.changed >= 2
    assert {o.company for o in db.scalars(select(Opportunity).where(Opportunity.user_id == user.id))} >= {"Acme Corp", "Globex"}
    spent = db.scalar(select(func.sum(TokenUsage.input_tokens + TokenUsage.output_tokens)).where(TokenUsage.task_id == task_id))
    assert spent and spent > 0
    # running again reads nothing twice
    calls = len(fake_llm.calls)
    again = folder_ai.create_task(db, user.id, db.get(Folder, t.folder_id), "timelines", True, None)
    db.commit()
    folder_ai.run_task(again.id)
    assert len(fake_llm.calls) == calls
    usage = client.get("/api/v1/usage", headers=H(user)).json()
    assert usage["tasks"][1]["tokens"] == spent and usage["tasks"][0]["tokens"] == 0


def test_todos_task_makes_todos_for_mail_that_needs_action(client, db, setup, fake_llm):
    user, f = _old_mail_in(client, db, setup, "Inbox stuff")
    r = client.post(f"/api/v1/folders/{f['id']}/ai-tasks", headers=H(user), json={"kind": "todos"}).json()
    folder_ai.run_task(__import__("uuid").UUID(r["id"]))
    assert db.scalar(select(func.count()).select_from(Todo).where(Todo.user_id == user.id, Todo.source == "ai")) >= 2


def test_ai_tasks_need_a_key(client, db, setup, fake_llm):
    user, account, provider, msgs = setup
    f = client.post("/api/v1/folders", headers=H(user), json={"name": "X"}).json()
    r = client.post(f"/api/v1/folders/{f['id']}/ai-tasks", headers=H(user), json={"kind": "timelines"})
    assert r.status_code == 409 and "API key" in r.json()["detail"] and fake_llm.calls == []


def test_usage_separates_everyday_work_from_tasks(client, db, setup, fake_llm):
    user, account, provider, msgs = setup
    with_key(db, user)
    run(db, account, provider, msgs["placement"])
    usage = client.get("/api/v1/usage", headers=H(user)).json()
    reading = next(a for a in usage["automatic"] if a["purpose"] == "extract")
    assert reading["label"] == "Reading each new mail" and reading["tokens"] > 0 and usage["tasks"] == []


# ---- sign-up -------------------------------------------------------------------------------------

def test_register_creates_an_account_with_the_starter_setup(client, db):
    r = client.post("/api/v1/auth/register", json={"email": "New.User@Example.com", "password": "a-long-pass-phrase"})
    assert r.status_code == 201 and r.json()["token"]
    u = db.scalar(select(User).where(User.email == "new.user@example.com"))
    assert db.scalar(select(Folder).where(Folder.user_id == u.id, Folder.name == "Placements")) is not None
    assert client.post("/api/v1/auth/login", json={"email": "new.user@example.com", "password": "a-long-pass-phrase"}).status_code == 200
    assert client.post("/api/v1/auth/register", json={"email": "new.user@example.com", "password": "another-long-one"}).status_code == 409


@pytest.mark.parametrize("email,password", [("not-an-email", "a-long-pass-phrase"), ("a@b.co", "short"), ("asha@x.com", "asha123456789"), ("b@x.com", "aaaaaaaaaaaa")])
def test_register_refuses_bad_input(client, email, password):
    assert client.post("/api/v1/auth/register", json={"email": email, "password": password}).status_code == 422


def test_register_can_be_closed_and_is_rate_limited(client, override_settings):
    assert client.get("/api/v1/auth/options").json() == {"registration": True}
    for i in range(5):
        assert client.post("/api/v1/auth/register", json={"email": f"u{i}@x.com", "password": "a-long-pass-phrase"}).status_code == 201
    assert client.post("/api/v1/auth/register", json={"email": "u9@x.com", "password": "a-long-pass-phrase"}).status_code == 429
    override_settings(registration="closed")
    assert client.get("/api/v1/auth/options").json() == {"registration": False}
    assert client.post("/api/v1/auth/register", json={"email": "z@x.com", "password": "a-long-pass-phrase"}).status_code == 403


# ---- reset -----------------------------------------------------------------------------------------

def test_reset_clears_what_sift_stored_and_keeps_the_setup(client, db, setup, fake_llm, keys):
    user, account, provider, msgs = setup
    starter.setup(db, user)
    with_key(db, user)
    real = GmailAccount(user_id=user.id, email="me@gmail.com", status="active", encrypted_refresh_token="x")
    db.add(real)
    db.commit()
    for k in ("placement", "hirepro", "bank"):
        run(db, account, provider, msgs[k])
    assert db.scalar(select(func.count()).select_from(Message)) == 3
    counts = starter.reset(db, user.id)
    db.commit()
    assert counts["messages"] == 3 and counts["demo_accounts"] == 1
    assert db.scalar(select(func.count()).select_from(Message)) == 0
    assert db.scalar(select(func.count()).select_from(Opportunity)) == 0
    assert db.get(GmailAccount, real.id) is not None and db.scalar(select(LlmCredential)) is not None
    assert [f.name for f in db.scalars(select(Folder).where(Folder.user_id == user.id))] == ["Placements"]

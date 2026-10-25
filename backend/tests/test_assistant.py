"""Ask Sift: one planner call per request, checked plans, confirmation before changes, cached AI
reading reused, pacing under the provider's limits, and the edges (bad model output, unknown
actions, missing folders, a double Run)."""
import json
import threading
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app import assistant, demo, folder_ai, folders
from app.db import get_sessionmaker
from app.llm import service as llm
from app.llm.base import LlmResult
from app.models import (AssistantRun, Device, FolderItem, GmailAccount, Message, Opportunity, OpportunityEvent, Todo, TokenUsage,
                        User)
from app.pipeline import process_message
from app.security import hash_password
from tests.test_pipeline import FakeLlm, with_key

PLANNER = "You are the planner inside Sift"


class PlanLlm(FakeLlm):
    """FakeLlm that also answers the planner with `self.plan` (a dict, or raw text)."""

    def __init__(self):
        super().__init__()
        self.plan = {"reply": "", "steps": []}
        self.planner_calls = []

    def generate_json(self, system, prompt, schema, max_output_tokens=600):
        if system.startswith(PLANNER):
            self.planner_calls.append({"system": system, "prompt": prompt, "schema": schema})
            text = self.plan if isinstance(self.plan, str) else json.dumps(self.plan)
            return LlmResult(text=text, input_tokens=1200, output_tokens=80)
        return super().generate_json(system, prompt, schema, max_output_tokens)


@pytest.fixture
def fake(monkeypatch):
    f = PlanLlm()
    monkeypatch.setattr(llm, "provider_factory", lambda provider, key, model: f)
    return f


@pytest.fixture
def world(db, keys, fcm_sends, fake):
    """A user with AI on, the demo account, and the demo mail read by the (fake) AI."""
    user = User(email="owner@gmail.com", password_hash=hash_password("correct horse"))
    db.add(user)
    db.flush()
    db.add(Device(user_id=user.id, fcm_token="phone"))
    demo.ensure_starter_rules(db, user)
    account = demo.demo_account(db, user)
    db.commit()
    with_key(db, user)
    samples = demo.samples()
    provider = demo.DemoProvider(samples)
    for m in samples:
        process_message(db, db.get(GmailAccount, account.id), provider, m["id"])
    fake.calls.clear()
    return user, account


@pytest.fixture
def auth(client, world):
    r = client.post("/api/v1/auth/login", json={"email": "owner@gmail.com", "password": "correct horse"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def ask(client, auth, text, plan, fake):
    fake.plan = plan
    return client.post("/api/v1/assistant", json={"text": text}, headers=auth)


# ---- gate, cost ---------------------------------------------------------------------------------

def test_ai_off_makes_no_call(client, db, keys, fake):
    u = User(email="nokey@gmail.com", password_hash=hash_password("pw-pw-pw-pw"))
    db.add(u)
    db.commit()
    h = {"Authorization": "Bearer " + client.post("/api/v1/auth/login", json={"email": "nokey@gmail.com", "password": "pw-pw-pw-pw"}).json()["token"]}
    r = client.post("/api/v1/assistant", json={"text": "make timelines"}, headers=h)
    assert r.status_code == 422 and "AI key" in r.json()["detail"]
    assert fake.planner_calls == [] and fake.calls == []


def test_one_small_call_per_request_and_no_mail_text_reaches_the_planner(client, db, world, auth, fake):
    r = ask(client, auth, "show mail from hirepro", {"reply": "Here it is", "steps": [{"action": "find_mail", "q": "from:hirepro"}]}, fake)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "done" and not body["needs_confirm"]  # read-only: ran at once
    assert len(fake.planner_calls) == 1 and fake.calls == []
    assert body["results"][0]["ok"] and len(body["results"][0]["mail"]) >= 1
    prompt = fake.planner_calls[0]["prompt"]
    for m in db.scalars(select(Message)):
        assert (m.subject or "zz-none") not in prompt and (m.snippet or "zz-none")[:30] not in prompt  # names only, never mail
    usage = db.scalar(select(TokenUsage).where(TokenUsage.purpose == "assistant"))
    assert usage.input_tokens == 1200 and body["tokens"] == 1280
    assert len(fake.planner_calls[0]["system"]) < 6000  # the catalogue stays small (~1.3k tokens)


def test_bad_model_output_gives_a_plain_answer_not_an_error(client, world, auth, fake):
    r = ask(client, auth, "do the thing", "{not json", fake)
    assert r.status_code == 200 and r.json()["steps"] == [] and "differently" in r.json()["reply"]


# ---- checking the plan ------------------------------------------------------------------------------

def test_unknown_actions_are_dropped_and_bad_steps_are_explained(client, db, world, auth, fake):
    plan = {"reply": "ok", "steps": [
        {"action": "drop_database"},
        {"action": "file_mail", "q": "from:hirepro", "folder": "Nowhere"},
        {"action": "set_setting", "key": "encryption_keys", "value": "x"},
        {"action": "add_section", "company": "Acme Corp", "title": "Interview"},  # no time
        {"action": "file_mail", "q": "from:hirepro"},  # no folder
    ]}
    body = ask(client, auth, "mess", plan, fake).json()
    errors = [s["error"] for s in body["steps"]]
    assert [s["action"] for s in body["steps"]] == ["file_mail", "set_setting", "add_section", "file_mail"]
    assert "no folder called Nowhere" in errors[0] and "can't be changed" in errors[1]
    assert "needs at" in errors[2] and "needs folder" in errors[3]
    assert not body["needs_confirm"]  # nothing runnable


def test_writes_wait_for_run_then_run_once(client, db, world, auth, fake):
    plan = {"reply": "Making a folder and filing", "steps": [
        {"action": "create_folder", "name": "Tests"},
        {"action": "file_mail", "q": "from:hirepro", "folder": "Tests"},  # a folder made by the step before
    ]}
    body = ask(client, auth, "file hirepro mail in a new Tests folder", plan, fake).json()
    assert body["needs_confirm"] and body["status"] == "planned" and not body["changes_gmail"]
    assert all(s["error"] is None for s in body["steps"]) and "File 1 conversation" in body["steps"][1]["preview"]
    assert db.scalar(select(func.count()).select_from(FolderItem)) == 0  # nothing changed yet

    r = client.post(f"/api/v1/assistant/{body['id']}/run", headers=auth)
    assert r.status_code == 200 and [x["ok"] for x in r.json()["results"]] == [True, True]
    f = [x for x in folders.load_tree(db, world[0].id).by_id.values() if x.name == "Tests"][0]
    assert db.scalar(select(func.count()).select_from(FolderItem).where(FolderItem.folder_id == f.id)) == 1
    assert client.post(f"/api/v1/assistant/{body['id']}/run", headers=auth).status_code == 409  # never twice


def test_cancelled_plan_never_runs(client, world, auth, fake):
    body = ask(client, auth, "new folder", {"reply": "", "steps": [{"action": "create_folder", "name": "X"}]}, fake).json()
    assert client.post(f"/api/v1/assistant/{body['id']}/cancel", headers=auth).json()["status"] == "cancelled"
    assert client.post(f"/api/v1/assistant/{body['id']}/run", headers=auth).status_code == 409


def test_a_double_run_at_the_same_moment_runs_once(client, db, world, auth, fake):
    body = ask(client, auth, "todo", {"reply": "", "steps": [{"action": "add_todo", "title": "Call Riya"}]}, fake).json()
    codes = []

    def go():
        codes.append(client.post(f"/api/v1/assistant/{body['id']}/run", headers=auth).status_code)
    threads = [threading.Thread(target=go) for _ in range(3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes) == [200, 409, 409]
    assert db.scalar(select(func.count()).select_from(Todo).where(Todo.title == "Call Riya")) == 1


def test_other_users_runs_are_not_found(client, db, world, auth, fake, keys):
    body = ask(client, auth, "todo", {"reply": "", "steps": [{"action": "add_todo", "title": "Mine"}]}, fake).json()
    u = User(email="other@gmail.com", password_hash=hash_password("other-pass-1"))
    db.add(u)
    db.commit()
    h = {"Authorization": "Bearer " + client.post("/api/v1/auth/login", json={"email": "other@gmail.com", "password": "other-pass-1"}).json()["token"]}
    assert client.post(f"/api/v1/assistant/{body['id']}/run", headers=h).status_code == 404


# ---- what it can do ------------------------------------------------------------------------------

def test_rebuild_a_deleted_timeline_from_a_folder_without_new_ai_reading(client, db, world, auth, fake):
    user, account = world
    acme = db.scalar(select(Opportunity).where(Opportunity.company == "Acme Corp"))
    assert acme is not None
    places = folders.create(db, user.id, "Placements")
    sub = folders.create(db, user.id, "Acme Corp", places.id)
    for m in db.scalars(select(Message).where(Message.extraction["company"].astext == "Acme Corp")):
        folders.file_thread(db, user.id, sub, m.account_id, m.thread_id)
    db.commit()

    body = ask(client, auth, "delete the acme timeline", {"reply": "", "steps": [{"action": "delete_timeline", "company": "acme corp"}]}, fake).json()
    client.post(f"/api/v1/assistant/{body['id']}/run", headers=auth)
    assert db.scalar(select(Opportunity).where(Opportunity.company == "Acme Corp")) is None

    plan = {"reply": "", "steps": [{"action": "build_timelines", "q": "folder:\"Acme Corp\"", "name": "Placements -> Acme"}]}
    body = ask(client, auth, "make the timeline again from placements -> acme", plan, fake).json()
    assert body["steps"][0]["tokens"] == 0 and body["estimate"] == 0  # the AI read these before: nothing new to pay
    assert any("Acme" in t for t in body["steps"][0]["targets"])  # the user sees which mail it touches
    r = client.post(f"/api/v1/assistant/{body['id']}/run", headers=auth).json()
    task_id = r["results"][0]["task_id"]
    fake.calls.clear()
    folder_ai.run_task(task_id)
    db.expire_all()
    again = db.scalar(select(Opportunity).where(Opportunity.company == "Acme Corp"))
    assert again is not None and db.scalar(select(func.count()).select_from(OpportunityEvent).where(OpportunityEvent.opportunity_id == again.id)) >= 1
    assert fake.calls == []  # the AI's earlier reading was reused: zero tokens


def test_timelines_over_a_search_read_only_what_the_ai_never_read(client, db, world, auth, fake):
    user, account = world
    m = db.scalar(select(Message).where(Message.sender.contains("hirepro")))
    m.extraction = {"source": "default"}  # as if it arrived while AI was off
    db.commit()
    body = ask(client, auth, "timelines from hirepro", {"reply": "", "steps": [{"action": "build_timelines", "q": "from:hirepro"}]}, fake).json()
    assert body["steps"][0]["tokens"] == assistant.READ_ESTIMATE  # one mail to read, said up front
    task_id = client.post(f"/api/v1/assistant/{body['id']}/run", headers=auth).json()["results"][0]["task_id"]
    folder_ai.run_task(task_id)
    assert len(fake.calls) == 1  # exactly the unread one


def test_folder_paths_and_fuzzy_names_resolve(db, world):
    user, _ = world
    places = folders.create(db, user.id, "Placements")
    folders.create(db, user.id, "Nvidia", places.id)
    db.commit()
    for name in ("Placements -> Nvidia", "placements/nvidia", "nvidia", "Placements › NVIDIA"):
        assert assistant._folder_by_name(db, user.id, name).name == "Nvidia", name
    assert assistant._folder_by_name(db, user.id, "Amazon") is None


def test_sections_todos_and_settings(client, db, world, auth, fake):
    user, _ = world
    plan = {"reply": "", "steps": [
        {"action": "add_section", "company": "Acme Corp", "stage": "interview", "title": "HR round", "at": "2026-11-03T10:00"},
        {"action": "add_todo", "title": "Print CV", "at": "2026-11-02"},
        {"action": "set_setting", "key": "undo_send_seconds", "value": "20"},
        {"action": "set_setting", "key": "daily_token_cap", "value": "999999999"},  # out of range
    ]}
    body = ask(client, auth, "several", plan, fake).json()
    results = client.post(f"/api/v1/assistant/{body['id']}/run", headers=auth).json()["results"]
    assert [r["ok"] for r in results] == [True, True, True, False]
    ev = db.scalar(select(OpportunityEvent).where(OpportunityEvent.details["title"].astext == "HR round"))
    assert ev.kind == "interview" and ev.occurred_at.utcoffset() is not None
    assert ev.occurred_at == datetime(2026, 11, 3, 4, 30, tzinfo=UTC)  # 10:00 in Asia/Kolkata
    assert db.scalar(select(Todo).where(Todo.title == "Print CV")).due_at is not None

    body = ask(client, auth, "done", {"reply": "", "steps": [{"action": "finish_todo", "title": "print"}]}, fake).json()
    client.post(f"/api/v1/assistant/{body['id']}/run", headers=auth)
    db.expire_all()
    assert db.scalar(select(Todo).where(Todo.title == "Print CV")).done


def test_gmail_changes_are_marked_and_need_write_access(client, db, world, auth, fake):
    body = ask(client, auth, "archive bank mail", {"reply": "", "steps": [{"action": "mail_action", "q": "from:kotak", "op": "archive"}]}, fake).json()
    assert body["changes_gmail"] and body["needs_confirm"]
    # an account without write access: nothing changes, and the step says what to do
    acc = db.get(GmailAccount, world[1].id)
    acc.encrypted_refresh_token, acc.scopes = "x", ["https://www.googleapis.com/auth/gmail.readonly"]
    db.commit()
    r = client.post(f"/api/v1/assistant/{body['id']}/run", headers=auth).json()
    assert r["results"][0]["ok"] is False and "permission" in r["results"][0]["text"]


def test_followups_see_the_previous_request(client, world, auth, fake):
    ask(client, auth, "timelines from acme", {"reply": "", "steps": [{"action": "list_timelines"}]}, fake)
    ask(client, auth, "same for globex", {"reply": "", "steps": []}, fake)
    assert "PREVIOUS REQUEST: timelines from acme" in fake.planner_calls[1]["prompt"]


# ---- pacing under the provider's limits -------------------------------------------------------------

def _usage_rows(db, user, n, seconds_ago=1):
    for _ in range(n):
        db.add(TokenUsage(user_id=user.id, day=llm._today(db, user.id), provider="gemini", model="m", purpose="extract",
                          input_tokens=10, output_tokens=1, created_at=datetime.now(UTC) - timedelta(seconds=seconds_ago)))
    db.commit()


def test_over_the_per_minute_limit_a_request_waits_or_says_when(client, db, world, auth, fake, monkeypatch):
    user, _ = world
    from app import user_settings
    user_settings.update(db, user.id, {"ai_requests_per_minute": 3})
    db.commit()
    _usage_rows(db, user, 3, seconds_ago=50)
    token = llm.pace_wait.set(0.0)  # someone is watching: don't wait, say when
    try:
        r = ask(client, auth, "anything", {"reply": "", "steps": []}, fake)
    finally:
        llm.pace_wait.reset(token)
    assert r.status_code == 422 and "per-minute" in r.json()["detail"]
    assert fake.planner_calls == []  # never sent just to be refused

    slept = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: (slept.append(s), _clear_usage(db)))
    assert ask(client, auth, "anything", {"reply": "", "steps": []}, fake).status_code == 200
    assert slept and 0 < slept[0] <= 11  # waited for the oldest call to leave the minute


def _clear_usage(db):
    with get_sessionmaker()() as s:
        s.query(TokenUsage).delete()
        s.commit()


def test_daily_request_limit_stops_and_mail_still_arrives(db, world, fake, fcm_sends):
    user, account = world
    from app import user_settings
    user_settings.update(db, user.id, {"ai_requests_per_day": 5})
    db.commit()
    _usage_rows(db, user, 5, seconds_ago=3600)
    with pytest.raises(assistant.AssistantError, match="request limit"):
        assistant.plan(db, user.id, "anything")
    # new mail: no call, delivered as normal, and the key is not marked as over quota
    sample = dict(next(m for m in demo.samples() if "recruiter" in m["id"]), id="demo-fresh-1", threadId="t-fresh-1")
    o = process_message(db, db.get(GmailAccount, account.id), demo.DemoProvider([sample]), sample["id"])
    assert o.priority == "normal" and fake.calls == []
    assert llm.credential(db, user.id).status == "valid"


def test_many_requests_in_a_row_cost_one_call_each(client, db, world, auth, fake):
    from app import user_settings
    user_settings.update(db, world[0].id, {"ai_requests_per_minute": 1000})
    db.commit()
    for i in range(12):
        r = ask(client, auth, f"find {i}", {"reply": "", "steps": [{"action": "find_mail", "q": "from:hirepro"}]}, fake)
        assert r.status_code == 200
    assert len(fake.planner_calls) == 12
    assert db.scalar(select(func.count()).select_from(TokenUsage).where(TokenUsage.purpose == "assistant")) == 12
    assert db.scalar(select(func.count()).select_from(AssistantRun)) == 12


def test_plans_in_the_args_format_the_model_uses(client, db, world, auth, fake):
    from app.assistant import parse_args
    assert parse_args('q="folder:\\"Acme Corp\\" newer_than:30d" ; name="x"') == {"q": 'folder:"Acme Corp" newer_than:30d', "name": "x"}
    assert parse_args("q='company:\"Acme Corp\"' ; at=2026-10-26T09:00:00+05:30 ; bogus=1") == {"q": 'company:"Acme Corp"', "at": "2026-10-26T09:00:00+05:30"}
    body = ask(client, auth, "todo", {"reply": "", "steps": [{"action": "add_todo", "args": 'title="Print CV" ; at="2026-11-02T09:00:00+05:30"'}]}, fake).json()
    assert body["steps"][0]["error"] is None and "Print CV" in body["steps"][0]["preview"] and "02 Nov" in body["steps"][0]["preview"]

def test_list_todos_when_done_and_overdue(db, world):
    from app.assistant import _list_todos
    from app.models import Todo
    user, _ = world
    t1 = Todo(user_id=user.id, title="Finished task", done=True, done_at=datetime.now(UTC))
    t2 = Todo(user_id=user.id, title="Open task", done=False, due_at=datetime.now(UTC) - timedelta(hours=2))
    db.add_all([t1, t2])
    db.commit()
    done_res = _list_todos(db, user.id, "done")
    assert done_res["text"] == "1 to-do done" and len(done_res["todos"]) == 1
    overdue_res = _list_todos(db, user.id, "overdue")
    assert overdue_res["text"] == "1 to-do overdue" and len(overdue_res["todos"]) == 1

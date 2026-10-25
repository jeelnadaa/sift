"""Things that run at the same time: worker lanes, long jobs, per-user mail processing, sending,
and two devices saving one draft. Nothing may run twice, block new mail, or lose an update."""
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text

from app import folder_ai, jobs, outbox, starter
from app.db import get_sessionmaker
from app.locks import LockBusy, user_lock
from app.models import Job, Message, Outbox
from tests.test_compose import FakeGmail, new_draft, world  # noqa: F401  (fixture)
from tests.test_pipeline import fake_llm, run, setup, with_key  # noqa: F401  (fixtures)
from tests.test_rule_tools import H


def add_job(db, kind, status="queued", locked_minutes_ago=None):
    j = Job(kind=kind, payload={}, status=status,
            locked_at=datetime.now(UTC) - timedelta(minutes=locked_minutes_ago) if locked_minutes_ago is not None else None)
    db.add(j)
    db.commit()
    return j


def test_the_quick_lane_never_takes_long_jobs(db):
    add_job(db, "ai_task")
    check = add_job(db, "check_account")
    with get_sessionmaker()() as s:
        got = jobs.claim_next(s, jobs.FAST_KINDS)
        assert got.id == check.id
    with get_sessionmaker()() as s:
        assert jobs.claim_next(s, jobs.FAST_KINDS) is None, "the long job is left for a general lane"
    with get_sessionmaker()() as s:
        assert jobs.claim_next(s).kind == "ai_task"


def test_long_jobs_are_not_taken_for_crashed_too_early(db):
    long_job = add_job(db, "onboarding_scan", status="running", locked_minutes_ago=30)
    quick = add_job(db, "check_account", status="running", locked_minutes_ago=30)
    with get_sessionmaker()() as s:
        got = jobs.claim_next(s)
        assert got.id == quick.id, "a quick job stuck for 30 min is a crash"
    with get_sessionmaker()() as s:
        assert jobs.claim_next(s) is None, "a scan running for 30 min is still working"
    db.execute(text("UPDATE jobs SET locked_at = now() - interval '3 hours' WHERE id = :i"), {"i": long_job.id})
    db.commit()
    with get_sessionmaker()() as s:
        assert jobs.claim_next(s).id == long_job.id


def test_lanes_never_claim_the_same_job(db):
    for _ in range(30):
        db.add(Job(kind="check_account", payload={}))
    db.commit()
    claimed, errors = [], []

    def lane():
        try:
            while True:
                with get_sessionmaker()() as s:
                    j = jobs.claim_next(s)
                    if j is None:
                        return
                    claimed.append(j.id)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=lane) for _ in range(4)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    assert errors == [] and len(claimed) == 30 and len(set(claimed)) == 30


def test_user_lock_makes_mail_processing_take_turns():
    user = uuid.uuid4()
    inside, overlaps = [], []

    def worker():
        with user_lock(user, wait_seconds=10):
            if inside:
                overlaps.append(True)
            inside.append(1)
            time.sleep(0.15)
            inside.pop()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    [t.start() for t in threads]
    [t.join(20) for t in threads]
    assert overlaps == []
    # other users are not held up
    with user_lock(user, wait_seconds=1), user_lock(uuid.uuid4(), wait_seconds=1):
        pass


def test_user_lock_gives_up_instead_of_hanging():
    user = uuid.uuid4()
    with user_lock(user):
        with pytest.raises(LockBusy):
            with user_lock(user, wait_seconds=0.3):
                pass
    with user_lock(user, wait_seconds=1):  # released afterwards
        pass


def test_one_mail_is_sent_once_even_when_lanes_race(client, db, world):
    user, acc, msg, g = world
    did = new_draft(client, user, acc).json()["draft_id"]
    r = client.post(f"/api/v1/compose/drafts/{acc.id}/{did}/send", headers=H(user), json={}).json()
    db.execute(Outbox.__table__.update().values(send_at=datetime.now(UTC) - timedelta(seconds=1)))
    db.commit()
    results = []
    threads = [threading.Thread(target=lambda: results.append(outbox.send_one(uuid.UUID(r["id"])))) for _ in range(5)]
    [t.start() for t in threads]
    [t.join(20) for t in threads]
    assert g.sent == [did] and sorted(results).count("sent") == 1


def test_two_devices_saving_at_the_same_moment_never_lose_a_version(client, db, world, monkeypatch):
    user, acc, msg, g = world
    d = new_draft(client, user, acc).json()
    url = f"/api/v1/compose/drafts/{acc.id}/{d['draft_id']}"
    real = g.update_draft

    def slow_update(did, raw, thread_id):
        time.sleep(0.3)  # both requests are in flight together
        return real(did, raw, thread_id)

    monkeypatch.setattr(g, "update_draft", slow_update)
    codes = {}

    def save(device):
        codes[device] = client.put(url, headers=H(user), json={"to": ["asha@acme.com"], "body": f"from the {device}", "base_version": d["version"]}).status_code

    threads = [threading.Thread(target=save, args=(dev,)) for dev in ("phone", "laptop")]
    [t.start() for t in threads]
    [t.join(20) for t in threads]
    assert sorted(codes.values()) == [200, 409], "one saves, the other is told the draft changed"


def test_a_folder_ai_failure_never_undoes_the_mails_classification(db, setup, fake_llm, monkeypatch):
    user, account, provider, msgs = setup
    starter.setup(db, user)
    with_key(db, user)

    def boom(*a, **k):
        raise RuntimeError("sorting broke")

    monkeypatch.setattr(folder_ai, "sort_if_needed", boom)
    out = run(db, account, provider, msgs["placement"])
    db.expire_all()
    m = db.get(Message, out.message_id)
    assert m.status == "processed" and m.priority is not None and m.category == "placement_announcement"


def test_new_mail_and_an_ai_task_on_the_same_user_do_not_collide(client, db, setup, fake_llm):
    """An AI task and mail checks for one user run on different lanes; the user lock makes them
    take turns, so the same company never gets two timelines or two subfolders."""
    user, account, provider, msgs = setup
    starter.setup(db, user)
    for k in ("placement", "hirepro"):
        run(db, account, provider, msgs[k])  # read without AI: nothing filed yet
    f = client.post("/api/v1/folders", headers=H(user), json={"name": "Old"}).json()
    ids = [str(m.id) for m in db.scalars(select(Message).where(Message.account_id == account.id))]
    client.post(f"/api/v1/folders/{f['id']}/threads", headers=H(user), json={"message_ids": ids})
    with_key(db, user)
    task = client.post(f"/api/v1/folders/{f['id']}/ai-tasks", headers=H(user), json={"kind": "timelines"}).json()
    errors = []

    def task_lane():
        try:
            folder_ai.run_task(uuid.UUID(task["id"]))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def mail_lane():
        try:
            with user_lock(user.id), get_sessionmaker()() as s:
                from app.models import GmailAccount
                from app.pipeline import process_message
                process_message(s, s.get(GmailAccount, account.id), provider, msgs["recruiter"]["id"])
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=task_lane), threading.Thread(target=mail_lane)]
    [t.start() for t in threads]
    [t.join(60) for t in threads]
    assert errors == []
    from app.models import Opportunity
    names = [n for (n,) in db.execute(select(Opportunity.company).where(Opportunity.user_id == user.id))]
    assert len(names) == len(set(names)), names
    assert db.scalar(select(func.count()).select_from(Message).where(Message.status == "processing")) == 0

def test_concurrent_deduplication_across_accounts_delivers_once(db, setup):
    user, account1, _, _ = setup
    from app.models import GmailAccount, Message
    from app.pipeline import process_message
    from app import demo

    account2 = GmailAccount(user_id=user.id, email="secondary@demo.sift.local", status="active")
    db.add(account2)
    db.commit()

    shared_msg_id = f"<shared-{uuid.uuid4().hex}@domain.com>"
    m1 = demo._msg("dup1", "Sender <sender@domain.com>", "Same subject", "Same body", ["INBOX"], extra_headers={"Message-ID": shared_msg_id})
    m2 = demo._msg("dup2", "Sender <sender@domain.com>", "Same subject", "Same body", ["INBOX"], extra_headers={"Message-ID": shared_msg_id})

    outcomes = []
    errors = []

    def run_worker(acct_id, raw_msg):
        try:
            with get_sessionmaker()() as s:
                p = demo.DemoProvider([raw_msg])
                a = s.get(GmailAccount, acct_id)
                outcomes.append(process_message(s, a, p, raw_msg["id"]))
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=run_worker, args=(account1.id, m1))
    t2 = threading.Thread(target=run_worker, args=(account2.id, m2))
    t1.start(); t2.start()
    t1.join(30); t2.join(30)

    assert errors == []
    assert len(outcomes) == 2
    priorities = sorted([o.priority for o in outcomes])
    assert priorities == ["normal", "silent"], f"One must be normal and one silent duplicate, got {priorities}"
    decided = sorted([o.decided_by for o in outcomes])
    assert "duplicate" in decided

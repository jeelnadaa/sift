"""Phase 2c: opt-in grouping (brief section 21)."""
import copy
import uuid
import time

import pytest
from sqlalchemy import delete, select

from app import demo, grouping
from app.models import GroupMember, MailGroup, Message, Rule
from tests.test_pipeline import run, setup  # noqa: F401  (fixtures)
from tests.test_rule_tools import H

BASE_MS = int(time.time() * 1000) - 60_000  # "now": mail older than 30 min counts as late (pipeline.LATE_AGE)
DAY_MS = 86_400_000


def variant(sample: dict, n: int, subject: str | None = None, sender: str | None = None, list_id: str | None = None, days_ago: float = 0) -> dict:
    m = copy.deepcopy(sample)
    m["id"], m["threadId"] = f"{sample['id']}-{n}", f"{sample['threadId']}-{n}"
    m["internalDate"] = str(int(BASE_MS - days_ago * DAY_MS + n * 1000))
    headers = m["payload"]["headers"]
    for h in headers:
        if h["name"] == "Subject" and subject is not None:
            h["value"] = subject
        if h["name"] == "From" and sender is not None:
            h["value"] = sender
        if h["name"] == "Message-ID":
            h["value"] = f"<{uuid.uuid4().hex}@x>"
    if list_id:
        headers.append({"name": "List-Id", "value": list_id})
    return m


@pytest.fixture
def plain(db, setup):
    """Starter bank rule removed, so bank alerts reach the feed (the acceptance scenario)."""
    user, account, provider, msgs = setup
    db.execute(delete(Rule).where(Rule.user_id == user.id))
    db.commit()
    return user, account, msgs


def feed(client, user, **params):
    return client.get("/api/v1/messages", headers=H(user), params={"grouped": True, **params}).json()


def turn_on(client, user):
    assert client.post("/api/v1/grouping", headers=H(user), json={"answer": "yes"}).json()["grouping_enabled"] == "yes"


def deliver(db, account, mails):
    provider = demo.DemoProvider(mails)
    return [run(db, account, provider, m) for m in mails]


# ---- consent --------------------------------------------------------------------------------------

def test_prompt_is_asked_up_to_three_times(client, setup):
    user = setup[0]
    assert client.get("/api/v1/grouping", headers=H(user)).json() == {"grouping_enabled": "not_asked", "prompts": 0, "should_ask": True}
    for _ in range(3):
        client.post("/api/v1/grouping", headers=H(user), json={"answer": "dismissed"})
    s = client.get("/api/v1/grouping", headers=H(user)).json()
    assert s["grouping_enabled"] == "not_asked" and s["should_ask"] is False
    assert client.post("/api/v1/grouping", headers=H(user), json={"answer": "no"}).json()["should_ask"] is False
    assert client.get("/api/v1/groups", headers=H(user)).status_code == 409


@pytest.mark.parametrize("answer", [None, "no"])
def test_off_or_unanswered_computes_nothing(client, db, plain, answer):
    user, account, msgs = plain
    if answer:
        client.post("/api/v1/grouping", headers=H(user), json={"answer": answer})
    deliver(db, account, [variant(msgs["bank"], i) for i in range(6)])
    assert db.scalar(select(MailGroup)) is None and db.scalar(select(GroupMember)) is None
    items = feed(client, user)["items"]
    assert len(items) == 6 and "type" not in items[0]


# ---- the acceptance scenario ---------------------------------------------------------------------

def test_twenty_bank_alerts_one_row_and_fraud_alert_stands_alone(client, db, plain, fcm_sends):
    user, account, msgs = plain
    turn_on(client, user)
    db.add(Rule(user_id=user.id, position=0, name="fraud urgent", origin="editor",
                conditions={"field": "subject", "op": "contains_any", "value": ["card blocked"]}, action={"type": "notify_urgent"}))
    db.commit()
    amounts = [f"{100 + i * 37}.00" for i in range(20)]
    deliver(db, account, [variant(msgs["bank"], i, subject=f"Rs {a} debited from your account via UPI") for i, a in enumerate(amounts)])
    sends_before = len(fcm_sends)
    assert sends_before == 20  # grouping never changes notifications: each alert notified on its own

    fraud = variant(msgs["fraud"], 99)
    out = deliver(db, account, [fraud])[0]
    assert out.priority == "urgent" and out.notified and fcm_sends[-1]["priority"] == "urgent"

    items = feed(client, user)["items"]
    groups = [i for i in items if i["type"] == "group"]
    assert len(groups) == 1 and groups[0]["count"] == 20 and groups[0]["title"] == "Kotak Mahindra Bank"
    assert groups[0]["unread"] == 20
    mails = [i for i in items if i["type"] == "mail"]
    assert any(i["priority"] == "urgent" and "card blocked" in i["subject"] for i in mails)
    assert not any("via UPI" in (i["subject"] or "") for i in mails)  # folded into the group row

    detail = client.get(f"/api/v1/groups/{groups[0]['id']}", headers=H(user)).json()
    assert len(detail["items"]) == 20


def test_groups_show_from_three_and_silenced_mail_stays_out(client, db, plain):
    user, account, msgs = plain
    turn_on(client, user)
    deliver(db, account, [variant(msgs["bank"], i) for i in range(2)])
    assert [i["type"] for i in feed(client, user)["items"]] == ["mail", "mail"]  # a group of 2 isn't shown
    assert db.scalar(select(MailGroup)) is not None
    deliver(db, account, [variant(msgs["bank"], 2)])
    assert [i["type"] for i in feed(client, user)["items"]] == ["group"]

    db.add(Rule(user_id=user.id, position=0, name="silence", origin="editor",
                conditions={"field": "sender_domain", "op": "is", "value": "kotak.com"}, action={"type": "silent"}))
    db.commit()
    deliver(db, account, [variant(msgs["bank"], 3)])
    g = db.scalar(select(MailGroup))
    assert len(grouping.members(db, g)) == 3


# ---- the grouping order ---------------------------------------------------------------------------

def test_list_id_groups_varied_subjects(client, db, plain):
    user, account, msgs = plain
    turn_on(client, user)
    subjects = ["Weekly digest: Rust", "Your Monday reading list", "Ten links about databases"]
    deliver(db, account, [variant(msgs["recruiter"], i, subject=s, list_id="Tech News <news.example.com>") for i, s in enumerate(subjects)])
    g = db.scalar(select(MailGroup))
    assert (g.kind, g.title, len(grouping.members(db, g))) == ("list", "Tech News", 3)


def test_similar_subjects_from_one_domain_group_but_different_ones_dont(client, db, plain):
    user, account, msgs = plain
    turn_on(client, user)
    mails = [
        variant(msgs["recruiter"], 1, subject="Your order has shipped", sender="Shop <a@globex.com>"),
        variant(msgs["recruiter"], 2, subject="Your order has been shipped", sender="Shop <b@globex.com>"),
        variant(msgs["recruiter"], 3, subject="Lunch on Friday?", sender="Priya <priya@globex.com>"),
    ]
    deliver(db, account, mails)
    g = db.scalar(select(MailGroup))
    assert g.kind == "similar" and {m.subject for m in grouping.members(db, g)} == {"Your order has shipped", "Your order has been shipped"}
    assert grouping.similarity("your order has shipped", "your order has been shipped") >= grouping.SIMILARITY
    assert grouping.similarity("your order has shipped", "lunch on friday") < grouping.SIMILARITY


def test_groups_close_after_thirty_quiet_days(client, db, plain):
    user, account, msgs = plain
    turn_on(client, user)
    deliver(db, account, [variant(msgs["bank"], i, days_ago=40) for i in range(3)])
    deliver(db, account, [variant(msgs["bank"], 10 + i) for i in range(3)])
    groups = list(db.scalars(select(MailGroup)))
    assert len(groups) == 2 and all(len(grouping.members(db, g)) == 3 for g in groups)


def test_backfill_groups_last_thirty_days_when_turned_on(client, db, plain, monkeypatch):
    from app import jobs
    user, account, msgs = plain
    deliver(db, account, [variant(msgs["bank"], i, days_ago=1) for i in range(4)] + [variant(msgs["bank"], 9, days_ago=45)])
    assert db.scalar(select(MailGroup)) is None
    queued = []
    monkeypatch.setattr(jobs, "enqueue_sync", lambda kind, payload, dedupe_key=None: queued.append((kind, payload)))
    turn_on(client, user)
    assert queued == [("grouping_backfill", {"user_id": str(user.id)})]
    jobs.HANDLERS["grouping_backfill"](queued[0][1])
    db.expire_all()
    g = db.scalar(select(MailGroup))
    assert len(grouping.members(db, g)) == 4  # the 45-day-old alert is left out
    assert grouping.backfill(db, user.id) == 0  # stable: nothing reshuffled on a second run


# ---- user control ---------------------------------------------------------------------------------

def test_remove_split_merge_rename_mute(client, db, plain, fcm_sends):
    user, account, msgs = plain
    turn_on(client, user)
    deliver(db, account, [variant(msgs["bank"], i) for i in range(6)])
    g = db.scalar(select(MailGroup))
    ids = [m.id for m in grouping.members(db, g)]
    h = H(user)

    assert client.post(f"/api/v1/groups/{g.id}/remove", headers=h, json={"message_id": str(ids[0])}).status_code == 200
    assert client.get(f"/api/v1/groups/{g.id}", headers=h).json()["count"] == 5
    assert grouping.assign(db, db.get(Message, ids[0])) is None  # a removed mail stays out

    new = client.post(f"/api/v1/groups/{g.id}/split", headers=h, json={"message_ids": [str(i) for i in ids[1:4]], "title": "Split off"}).json()
    assert new["count"] == 3 and new["title"] == "Split off"
    assert client.get(f"/api/v1/groups/{g.id}", headers=h).json()["count"] == 2
    merged = client.post(f"/api/v1/groups/{new['id']}/merge", headers=h, json={"target_id": str(g.id)}).json()
    assert merged["count"] == 5

    r = client.patch(f"/api/v1/groups/{g.id}", headers=h, json={"title": "Kotak UPI", "muted": True, "collapsed": False}).json()
    assert (r["title"], r["muted"], r["collapsed"]) == ("Kotak UPI", True, False)
    sent = len(fcm_sends)
    deliver(db, account, [variant(msgs["bank"], 50)])  # joins the muted group: no notification
    assert len(fcm_sends) == sent
    assert client.post("/api/v1/groups/collapse-all", headers=h, json={"collapsed": True}).json()["updated"] >= 1


def test_never_and_always_group_preferences(client, db, plain):
    user, account, msgs = plain
    turn_on(client, user)
    h = H(user)
    client.put("/api/v1/grouping/preferences", headers=h, json={"sender_or_domain": "kotak.com", "mode": "never"})
    deliver(db, account, [variant(msgs["bank"], i) for i in range(4)])
    assert db.scalar(select(MailGroup)) is None

    client.put("/api/v1/grouping/preferences", headers=h, json={"sender_or_domain": "priya@globex.com", "mode": "always"})
    deliver(db, account, [variant(msgs["recruiter"], i, subject=s) for i, s in enumerate(["Hi", "Lunch?", "That doc"])])
    g = db.scalar(select(MailGroup))
    assert g.kind == "sender" and len(grouping.members(db, g)) == 3
    prefs = client.get("/api/v1/grouping/preferences", headers=h).json()
    assert {p["sender_or_domain"]: p["mode"] for p in prefs} == {"kotak.com": "never", "priya@globex.com": "always"}


def test_file_tag_and_rule_from_group(client, db, plain):
    from app import folders
    from app.models import FolderItem, MailTag
    user, account, msgs = plain
    turn_on(client, user)
    deliver(db, account, [variant(msgs["bank"], i) for i in range(3)])
    g = db.scalar(select(MailGroup))
    f = folders.create(db, user.id, "Bank")
    db.commit()
    h = H(user)
    assert client.post(f"/api/v1/groups/{g.id}/file", headers=h, json={"folder_id": str(f.id)}).json()["filed"] == 3
    assert len(list(db.scalars(select(FolderItem)))) == 3
    assert client.post(f"/api/v1/groups/{g.id}/tag", headers=h, json={"name": "Money"}).json()["tagged"] == 3
    assert len(list(db.scalars(select(MailTag)))) == 3
    r = client.post(f"/api/v1/groups/{g.id}/rule", headers=h, json={"action": "file", "folder_id": str(f.id), "save": True}).json()
    assert r["draft"]["action"] == {"type": "llm", "folder_id": str(f.id)} and r["rule_id"] and r["preview"]["matches"] == 3


def test_pages_report_totals_and_tile_without_gaps(client, db, plain):
    user, account, msgs = plain
    deliver(db, account, [variant(msgs["recruiter"], i, subject=f"Note {i}") for i in range(7)])
    h = H(user)
    seen, before, pages = [], None, 0
    while True:
        r = client.get("/api/v1/messages", headers=h, params={"limit": 3, **({"before": before} if before else {})}).json()
        assert (r["total"], r["pages"]) == (7, 3)
        seen += [i["id"] for i in r["items"]]
        pages += 1
        before = r["next_before"]
        if not before:
            break
    assert pages == 3 and len(seen) == len(set(seen)) == 7
    # a filter changes the totals (the client renumbers from 1)
    other = client.get("/api/v1/messages", headers=h, params={"limit": 3, "priority": "urgent"}).json()
    assert (other["total"], other["pages"], other["items"]) == (0, 1, [])

    turn_on(client, user)
    deliver(db, account, [variant(msgs["bank"], 20 + i) for i in range(4)])
    g = client.get("/api/v1/messages", headers=h, params={"limit": 3, "grouped": True}).json()
    assert g["total"] == 8 and g["pages"] == 3  # 7 notes + 1 group row; pages count mail rows

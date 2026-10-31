"""Acting on many conversations at once (POST /api/v1/bulk): targets, mixed selections, write
access, undo, background jobs, limits, and other users' mail."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import accounts as account_service
from app import bulk
from app.mail import google_oauth
from app.models import BulkJob, Folder, FolderItem, GmailAccount, GroupMember, MailGroup, Message, MutedThread, Opportunity, OpportunityEvent, User
from tests.test_actions import MODIFY, FakeGmail
from tests.test_rule_tools import H


@pytest.fixture
def world(db, keys, monkeypatch, fcm_sends):
    user = User(email="owner@gmail.com")
    db.add(user)
    db.flush()
    acc = GmailAccount(user_id=user.id, email="me@gmail.com", status="active", encrypted_refresh_token="x",
                       scopes=[google_oauth.READONLY_SCOPE, MODIFY])
    db.add(acc)
    db.flush()
    msgs = [Message(user_id=user.id, account_id=acc.id, gmail_id=f"g{i}", thread_id=f"t{i}", subject=f"Mail {i}", sender="a@shop.com",
                    status="processed", priority="urgent" if i == 4 else "normal", labels=["INBOX", "UNREAD"],
                    received_at=datetime.now(UTC) - timedelta(hours=i))
            for i in range(6)]
    db.add_all(msgs)
    db.flush()
    group = MailGroup(user_id=user.id, title="Shop", kind="custom", key="custom:shop")
    db.add(group)
    db.flush()
    for m in msgs[3:]:
        db.add(GroupMember(group_id=group.id, message_id=m.id, account_id=acc.id, added_by="user"))
    db.commit()
    g = FakeGmail()
    monkeypatch.setattr(account_service, "provider_for", lambda a: g)
    return user, acc, msgs, group, g


def post(client, user, **body):
    return client.post("/api/v1/bulk", headers=H(user), json=body)


def test_mails_plus_groups_act_on_every_conversation_once(client, db, world):
    user, acc, msgs, group, g = world
    # mail 3 is picked on its own and inside the group: still one conversation
    r = post(client, user, message_ids=[str(msgs[0].id), str(msgs[3].id)], group_ids=[str(group.id)], action="archive")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["picked"] == {"mails": 2, "groups": 1, "group_mails": 3, "urgent_in_groups": 1, "conversations": 4}
    assert body["changed"] == 4 and sorted(c[1] for c in g.calls) == ["t0", "t3", "t4", "t5"]
    for m in (msgs[0], msgs[3], msgs[4], msgs[5]):
        db.refresh(m)
        assert "INBOX" not in m.labels
    assert body["undo"]["action"] == "unarchive" and len(body["undo"]["message_ids"]) == 4


def test_preview_changes_nothing(client, db, world):
    user, acc, msgs, group, g = world
    r = post(client, user, group_ids=[str(group.id)], action="trash", preview=True).json()
    assert r["conversations"] == 3 and r["picked"]["urgent_in_groups"] == 1 and g.calls == []


def test_undo_reverses_exactly_what_changed(client, db, world):
    user, acc, msgs, group, g = world
    msgs[1].labels = ["INBOX"]  # already read: not part of the change, so Undo leaves it read
    db.commit()
    r = post(client, user, message_ids=[str(m.id) for m in msgs[:3]], action="read").json()
    assert r["changed"] == 2 and len(g.calls) == 2
    undo = r["undo"]
    assert undo["action"] == "unread" and str(msgs[1].id) not in undo["message_ids"]
    post(client, user, message_ids=undo["message_ids"], action=undo["action"])
    for m in msgs[:3]:
        db.refresh(m)
    assert ["UNREAD" in m.labels for m in msgs[:3]] == [True, False, True]


def test_trash_hides_mail_from_feed_and_undo_restores_it(client, db, world):
    user, acc, msgs, group, g = world
    r = post(client, user, message_ids=[str(msgs[0].id)], action="trash").json()
    ids = [i["id"] for i in client.get("/api/v1/messages", headers=H(user)).json()["items"]]
    assert str(msgs[0].id) not in ids and ("trash", "t0") in g.calls
    post(client, user, message_ids=r["undo"]["message_ids"], action=r["undo"]["action"])
    ids = [i["id"] for i in client.get("/api/v1/messages", headers=H(user)).json()["items"]]
    assert str(msgs[0].id) in ids and ("untrash", "t0") in g.calls


def test_without_write_access_nothing_changes_and_the_accounts_are_named(client, db, world):
    user, acc, msgs, group, g = world
    acc.scopes = [google_oauth.READONLY_SCOPE]
    db.commit()
    r = post(client, user, message_ids=[str(m.id) for m in msgs], action="archive")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "needs_write_access"
    assert r.json()["detail"]["accounts"][0]["email"] == "me@gmail.com" and g.calls == []
    # read/unread never asks: Sift's copy changes, Gmail doesn't
    r = post(client, user, message_ids=[str(msgs[0].id)], action="read").json()
    assert r["sift_only"] == ["me@gmail.com"] and g.calls == []


def test_select_all_matching_covers_the_whole_feed_with_its_filter(client, db, world):
    user, acc, msgs, group, g = world
    r = post(client, user, match={"view": "feed", "priority": "urgent"}, action="star").json()
    assert r["conversations"] == 1 and g.calls == [("modify_thread", "t4", ("STARRED",), ())]
    r = post(client, user, match={"group_id": str(group.id)}, action="pin").json()
    assert r["changed"] == 3


def test_sift_only_actions_and_their_undo(client, db, world):
    user, acc, msgs, group, g = world
    folder = Folder(user_id=user.id, name="Shops", position=0)
    opp = Opportunity(user_id=user.id, company="Acme", aliases=[], domains=[])
    db.add_all([folder, opp])
    db.commit()
    ids = [str(m.id) for m in msgs[:2]]
    r = post(client, user, message_ids=ids, action="file", folder_id=str(folder.id)).json()
    assert r["changed"] == 2 and db.scalar(select(FolderItem).where(FolderItem.thread_id == "t0"))
    post(client, user, **{**r["undo"], **r["undo"].pop("params")})
    assert db.scalar(select(FolderItem).where(FolderItem.thread_id == "t0")) is None
    r = post(client, user, message_ids=ids, action="mute").json()
    assert r["changed"] == 2 and len(db.scalars(select(MutedThread)).all()) == 2
    r = post(client, user, message_ids=ids, action="timeline", opportunity_id=str(opp.id)).json()
    assert r["changed"] == 2 and len(db.scalars(select(OpportunityEvent)).all()) == 2
    r = post(client, user, message_ids=ids, action="group_add", group_id=str(group.id)).json()
    assert r["changed"] == 2
    r = post(client, user, message_ids=[str(msgs[3].id)], action="group_remove", group_id=str(group.id)).json()
    assert r["changed"] == 1 and r["undo"]["action"] == "group_add"
    until = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    r = post(client, user, message_ids=ids, action="snooze", until=until).json()
    assert r["changed"] == 2 and r["undo"] is None


def test_others_mail_and_groups_are_refused(client, db, world):
    user, acc, msgs, group, g = world
    other = User(email="other@gmail.com")
    db.add(other)
    db.commit()
    assert post(client, other, message_ids=[str(msgs[0].id)], action="archive").status_code == 422
    assert post(client, other, group_ids=[str(group.id)], action="archive").status_code == 422
    assert post(client, other, match={"group_id": str(group.id)}, action="archive").status_code == 422
    assert g.calls == []


def test_actions_that_need_a_choice_say_so(client, world):
    user, acc, msgs, group, g = world
    assert post(client, user, message_ids=[str(msgs[0].id)], action="file").status_code == 422
    assert post(client, user, message_ids=[str(msgs[0].id)], action="explode").status_code == 422
    assert post(client, user, action="archive").status_code == 422


def test_big_gmail_change_runs_as_a_job_with_progress(client, db, world, monkeypatch):
    user, acc, msgs, group, g = world
    monkeypatch.setattr(bulk, "INLINE_GMAIL", 2)
    monkeypatch.setattr(bulk, "CHUNK", 2)
    monkeypatch.setattr(bulk, "PACE_SECONDS", 0)
    queued = []
    from app import jobs
    monkeypatch.setattr(jobs, "enqueue_sync", lambda kind, payload, dedupe_key=None: queued.append((kind, payload)))
    r = post(client, user, match={"view": "feed"}, action="archive").json()
    assert r["job"]["status"] == "queued" and r["job"]["total"] == 6 and g.calls == []
    assert queued == [("bulk", {"job_id": r["job"]["id"]})]
    bulk.run_job(__import__("uuid").UUID(r["job"]["id"]))
    job = client.get(f"/api/v1/bulk/jobs/{r['job']['id']}", headers=H(user)).json()
    assert (job["status"], job["done"], job["changed"]) == ("done", 6, 6) and len(g.calls) == 6
    assert job["undo"]["action"] == "unarchive" and len(job["undo"]["message_ids"]) == 6
    other = User(email="other@gmail.com")
    db.add(other)
    db.commit()
    assert client.get(f"/api/v1/bulk/jobs/{r['job']['id']}", headers=H(other)).status_code == 404


def test_limit(client, db, world, monkeypatch):
    user, acc, msgs, group, g = world
    monkeypatch.setattr(bulk, "LIMIT", 3)
    r = post(client, user, match={"view": "feed"}, action="archive")
    assert r.status_code == 422 and "at most 3" in r.json()["detail"]
    assert db.scalar(select(BulkJob)) is None


def test_timelines_stand_for_the_mail_on_them(client, db, world):
    user, acc, msgs, group, g = world
    opp = Opportunity(user_id=user.id, company="Acme", aliases=[], domains=[])
    db.add(opp)
    db.commit()
    post(client, user, message_ids=[str(msgs[0].id), str(msgs[1].id)], action="timeline", opportunity_id=str(opp.id))
    r = post(client, user, opportunity_ids=[str(opp.id)], action="read").json()
    assert r["conversations"] == 2 and r["changed"] == 2
    other = User(email="other@gmail.com")
    db.add(other)
    db.commit()
    assert post(client, other, opportunity_ids=[str(opp.id)], action="read").status_code == 422


def test_folders_stand_for_the_mail_filed_in_them_and_their_subfolders(client, db, world):
    user, acc, msgs, group, g = world
    top = Folder(user_id=user.id, name="Shops", position=0)
    db.add(top)
    db.flush()
    sub = Folder(user_id=user.id, name="Books", parent_id=top.id, position=0)
    db.add(sub)
    db.flush()
    db.add_all([FolderItem(folder_id=top.id, account_id=acc.id, thread_id="t0"),
                FolderItem(folder_id=sub.id, account_id=acc.id, thread_id="t1")])
    db.commit()
    r = post(client, user, folder_ids=[str(top.id)], action="read").json()
    assert r["conversations"] == 2 and r["changed"] == 2
    other = User(email="other@gmail.com")
    db.add(other)
    db.commit()
    assert post(client, other, folder_ids=[str(top.id)], action="read").status_code == 422

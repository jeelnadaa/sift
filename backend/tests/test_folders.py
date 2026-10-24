"""Phase 2c: folders (brief section 18) — tree limits, filing, roll-up counts, merge/delete,
per-folder notifications, the file-in-folder rule action and label sync."""
import uuid

import pytest
from sqlalchemy import select

from app import accounts, folders
from app.models import Folder, FolderItem, Message, Rule
from tests.test_pipeline import run, setup  # noqa: F401  (fixtures)
from tests.test_rule_tools import H


@pytest.fixture
def mail(db, setup):
    user, account, provider, msgs = setup
    for m in msgs.values():
        run(db, account, provider, m)
    by_key = {k: db.scalar(select(Message).where(Message.gmail_id == m["id"])) for k, m in msgs.items()}
    return user, account, by_key


def mk(client, user, name, parent=None, status=201):
    r = client.post("/api/v1/folders", headers=H(user), json={"name": name, "parent_id": str(parent) if parent else None})
    assert r.status_code == status, r.text
    return r.json()


# ---- tree limits ---------------------------------------------------------------------------------

def test_depth_limit_and_cycles_are_rejected(client, db, setup):
    user = setup[0]
    chain = [mk(client, user, "L1")]
    for i in range(2, folders.MAX_FOLDER_DEPTH + 1):
        chain.append(mk(client, user, f"L{i}", chain[-1]["id"]))
    r = client.post("/api/v1/folders", headers=H(user), json={"name": "too deep", "parent_id": chain[-1]["id"]})
    assert r.status_code == 422 and "10 levels" in r.json()["detail"]

    # a folder with one child can't move under level 9 (that would make 11 levels)
    a = mk(client, user, "A")
    mk(client, user, "A child", a["id"])
    r = client.post(f"/api/v1/folders/{a['id']}/move", headers=H(user), json={"parent_id": chain[8]["id"]})
    assert r.status_code == 422
    assert client.post(f"/api/v1/folders/{a['id']}/move", headers=H(user), json={"parent_id": chain[7]["id"]}).status_code == 200

    # a folder can't go inside itself or its own subfolder
    for target in (chain[0]["id"], chain[3]["id"]):
        r = client.post(f"/api/v1/folders/{chain[0]['id']}/move", headers=H(user), json={"parent_id": target})
        assert r.status_code == 422 and "inside itself" in r.json()["detail"]


def test_rename_recolor_pin_reorder(client, db, setup):
    user = setup[0]
    a, b, c = (mk(client, user, n) for n in ("Alpha", "Beta", "Gamma"))
    r = client.patch(f"/api/v1/folders/{c['id']}", headers=H(user), json={"name": "  Gamma   rays ", "color": "#c6f432", "pinned": True, "notify_mode": "mute"})
    assert r.json()["name"] == "Gamma rays" and r.json()["notify_mode"] == "mute"
    assert client.patch(f"/api/v1/folders/{c['id']}", headers=H(user), json={"color": "red"}).status_code == 422
    tree = client.post("/api/v1/folders/reorder", headers=H(user), json={"ids": [b["id"], a["id"], c["id"]]}).json()
    assert [f["name"] for f in tree["folders"]] == ["Gamma rays", "Beta", "Alpha"]  # pinned first, then order
    assert client.post("/api/v1/folders/reorder", headers=H(user), json={"ids": [b["id"]]}).status_code == 422


# ---- filing and reading --------------------------------------------------------------------------

def test_file_view_rollup_and_new_replies(client, db, mail):
    user, account, m = mail
    work = mk(client, user, "Work")
    place = mk(client, user, "Placements", work["id"])
    r = client.post(f"/api/v1/folders/{place['id']}/threads", headers=H(user), json={"message_ids": [str(m["placement"].id), str(m["hirepro"].id)]})
    assert r.json()["filed"] == 2
    assert client.post(f"/api/v1/folders/{place['id']}/threads", headers=H(user), json={"message_ids": [str(m["placement"].id)]}).json()["filed"] == 0

    tree = client.get("/api/v1/folders", headers=H(user)).json()
    root = tree["folders"][0]
    assert (root["unread"], root["unread_total"], root["children"][0]["unread"]) == (0, 2, 2)
    assert tree["last_used_id"] == place["id"]

    view = client.get(f"/api/v1/folders/{work['id']}/threads", headers=H(user)).json()
    assert view["items"] == [] and [p["name"] for p in view["path"]] == ["Work"]
    view = client.get(f"/api/v1/folders/{work['id']}/threads", headers=H(user), params={"include_subfolders": True}).json()
    assert {i["subject"][:8] for i in view["items"]} == {"Acme Cor"}  and len(view["items"]) == 2
    view = client.get(f"/api/v1/folders/{place['id']}/threads", headers=H(user), params={"q": "assessment"}).json()
    assert [p["name"] for p in view["path"]] == ["Work", "Placements"] and len(view["items"]) == 1

    # a new reply in a filed thread shows up in the folder by itself (threads are filed, not mails)
    p = m["placement"]
    db.add(Message(user_id=user.id, account_id=account.id, gmail_id="reply-1", thread_id=p.thread_id, sender=p.sender,
                   subject="Re: " + p.subject, received_at=p.received_at.replace(year=p.received_at.year + 1),
                   labels=["INBOX", "UNREAD"], status="processed", priority="normal"))
    db.commit()
    view = client.get(f"/api/v1/folders/{place['id']}/threads", headers=H(user)).json()
    top = view["items"][0]
    assert top["subject"].startswith("Re: ") and (top["thread_count"], top["thread_unread"]) == (2, 2) and len(view["items"]) == 2

    # one tap: last used folder; unfile
    assert client.post("/api/v1/folders/last-used/threads", headers=H(user), json={"message_ids": [str(m["recruiter"].id)]}).json()["filed"] == 1
    assert [f["name"] for f in client.get(f"/api/v1/folders/for-message/{m['recruiter'].id}", headers=H(user)).json()] == ["Placements"]
    assert client.post(f"/api/v1/folders/{place['id']}/threads/remove", headers=H(user), json={"message_ids": [str(m["recruiter"].id)]}).json()["removed"] == 1


def test_other_users_folders_and_mail_are_off_limits(client, db, mail, keys):
    from app.models import User
    user, account, m = mail
    mine = mk(client, user, "Mine")
    other = User(email="other@gmail.com")
    db.add(other)
    db.commit()
    assert client.get(f"/api/v1/folders/{mine['id']}/threads", headers=H(other)).status_code == 404
    theirs = mk(client, other, "Theirs")
    r = client.post(f"/api/v1/folders/{theirs['id']}/threads", headers=H(other), json={"message_ids": [str(m["bank"].id)]})
    assert r.status_code == 404
    rule = {"name": "x", "conditions": {"field": "subject", "op": "contains_any", "value": ["x"]}, "action": {"type": "llm", "folder_id": theirs["id"]}}
    assert client.post("/api/v1/rules", headers=H(user), json=rule).status_code == 422


def test_smart_folders_take_no_manual_filing(db, mail):
    from app.models import SavedSearch
    user, account, m = mail
    s = SavedSearch(user_id=user.id, name="Unread", query="is:unread")
    db.add(s)
    db.flush()
    f = Folder(user_id=user.id, name="Unread", saved_search_id=s.id)
    db.add(f)
    db.flush()
    with pytest.raises(folders.FolderError):
        folders.file_thread(db, user.id, f, account.id, m["bank"].thread_id)


# ---- merge and delete ----------------------------------------------------------------------------

def test_merge_moves_mail_subfolders_and_rules(client, db, mail):
    user, account, m = mail
    old, new = mk(client, user, "Old"), mk(client, user, "New")
    kid = mk(client, user, "Kid", old["id"])
    client.post(f"/api/v1/folders/{old['id']}/threads", headers=H(user), json={"message_ids": [str(m["recruiter"].id)]})
    rule = client.post("/api/v1/rules", headers=H(user), json={"name": "f", "conditions": {"field": "subject", "op": "contains_any", "value": ["globex"]},
                                                               "action": {"type": "llm", "folder_id": old["id"]}}).json()
    assert client.post(f"/api/v1/folders/{old['id']}/merge", headers=H(user), json={"target_id": kid["id"]}).status_code == 422
    r = client.post(f"/api/v1/folders/{old['id']}/merge", headers=H(user), json={"target_id": new["id"]}).json()
    assert r == {"moved_threads": 1, "moved_folders": 1, "rules_updated": 1}
    assert db.get(Rule, uuid.UUID(rule["id"])).action["folder_id"] == new["id"]
    tree = client.get("/api/v1/folders", headers=H(user)).json()["folders"]
    assert [(f["name"], [k["name"] for k in f["children"]], f["threads"]) for f in tree] == [("New", ["Kid"], 1)]


@pytest.mark.parametrize("mode,left", [("move_up", ["Kid", "Other"]), ("delete", ["Other"])])
def test_delete_keeps_mail_and_asks_about_subfolders(client, db, mail, mode, left):
    user, account, m = mail
    top = mk(client, user, "Top")
    mk(client, user, "Kid", top["id"])
    mk(client, user, "Other")
    client.post(f"/api/v1/folders/{top['id']}/threads", headers=H(user), json={"message_ids": [str(m["recruiter"].id)]})
    rule = client.post("/api/v1/rules", headers=H(user), json={"name": "f", "conditions": {"field": "subject", "op": "contains_any", "value": ["globex"]},
                                                               "action": {"type": "digest", "folder_id": top["id"]}}).json()
    r = client.delete(f"/api/v1/folders/{top['id']}", headers=H(user), params={"subfolders": mode}).json()
    assert r["rules_updated"] == 1
    assert sorted(f["name"] for f in client.get("/api/v1/folders", headers=H(user)).json()["folders"]) == left
    assert db.get(Rule, uuid.UUID(rule["id"])).action == {"type": "digest"}  # the rule keeps working, just stops filing
    assert db.get(Message, m["recruiter"].id) is not None and db.scalar(select(FolderItem)) is None


# ---- notifications and rules ---------------------------------------------------------------------

def test_muted_folder_holds_back_normal_but_never_urgent(db, setup, fcm_sends):
    user, account, provider, msgs = setup
    db.add(Rule(user_id=user.id, position=-1, name="fraud urgent", origin="editor",
                conditions={"field": "subject", "op": "contains_any", "value": ["card blocked"]}, action={"type": "notify_urgent"}))
    muted = folders.create(db, user.id, "Quiet")
    folders.edit(muted, notify_mode="mute")
    for k in ("recruiter", "fraud"):
        folders.file_thread(db, user.id, muted, account.id, msgs[k]["threadId"])
    db.commit()
    assert not run(db, account, provider, msgs["recruiter"]).notified  # normal mail in a muted folder
    out = run(db, account, provider, msgs["fraud"])
    assert out.priority == "urgent" and out.notified
    assert [s["priority"] for s in fcm_sends] == ["urgent"]


def test_always_folder_turns_digest_into_a_normal_notification(db, setup, fcm_sends):
    user, account, provider, msgs = setup
    db.add(Rule(user_id=user.id, position=-1, name="globex digest", origin="editor",
                conditions={"field": "subject", "op": "contains_any", "value": ["globex"]}, action={"type": "digest"}))
    loud = folders.create(db, user.id, "Loud")
    folders.edit(loud, notify_mode="always")
    folders.file_thread(db, user.id, loud, account.id, msgs["recruiter"]["threadId"])
    db.commit()
    out = run(db, account, provider, msgs["recruiter"])
    assert out.priority == "digest" and out.notified and fcm_sends[-1]["priority"] == "normal"


def test_file_in_folder_rule_and_rule_from_message(client, db, setup):
    user, account, provider, msgs = setup
    f = folders.create(db, user.id, "Recruiters")
    db.commit()
    run(db, account, provider, msgs["recruiter"])
    msg = db.scalar(select(Message).where(Message.gmail_id == msgs["recruiter"]["id"]))
    r = client.post(f"/api/v1/folders/{f.id}/rule-from-message", headers=H(user), json={"message_id": str(msg.id), "save": True}).json()
    assert r["draft"]["action"] == {"type": "llm", "folder_id": str(f.id)} and r["draft"]["name"].startswith("File in Recruiters")
    assert db.scalar(select(FolderItem).where(FolderItem.folder_id == f.id)).thread_id == msg.thread_id

    # the saved rule files the next mail like it, and classification still runs as usual
    nxt = dict(msgs["recruiter"], id="recruiter-2", threadId="thread-2")
    provider._by_id["recruiter-2"] = nxt
    out = run(db, account, provider, nxt)
    assert out.priority == "normal" and out.notified
    assert {i.thread_id for i in db.scalars(select(FolderItem).where(FolderItem.folder_id == f.id))} == {msg.thread_id, "thread-2"}


def test_label_changes_from_gmail_update_unread_counts(client, db, mail):
    user, account, m = mail
    f = mk(client, user, "Bank")
    client.post(f"/api/v1/folders/{f['id']}/threads", headers=H(user), json={"message_ids": [str(m["bank"].id)]})
    assert client.get("/api/v1/folders", headers=H(user)).json()["folders"][0]["unread"] == 1
    accounts.apply_label_changes(db, account, [(m["bank"].gmail_id, [], ["UNREAD"]), ("never-stored", ["UNREAD"], [])])
    db.commit()
    assert client.get("/api/v1/folders", headers=H(user)).json()["folders"][0]["unread"] == 0
    accounts.apply_label_changes(db, account, [(m["bank"].gmail_id, ["UNREAD", "STARRED"], [])])
    db.commit()
    assert db.get(Message, m["bank"].id).labels.count("UNREAD") == 1


# ---- backup ---------------------------------------------------------------------------------------

def test_backup_round_trip_into_another_user(client, db, setup, keys):
    from app.models import Category, Tag, User
    user, account, provider, msgs = setup
    work = folders.create(db, user.id, "Work", color="#c6f432")
    place = folders.create(db, user.id, "Placements", work.id)
    folders.edit(place, notify_mode="always", pinned=True)
    db.add_all([Tag(user_id=user.id, name="Later"), Category(user_id=user.id, name="Bills", definition="Utility bills")])
    db.add(Rule(user_id=user.id, position=5, name="file placements", origin="editor",
                conditions={"field": "account", "op": "in", "value": [str(account.id)]}, action={"type": "llm", "folder_id": str(place.id)},
                account_scope=[str(account.id)]))
    db.commit()
    client.patch("/api/v1/settings", headers=H(user), json={"resend_limit": 2})
    data = client.get("/api/v1/backup", headers=H(user)).json()
    assert data["format"] == "sift-backup" and "encrypted" not in str(data) and str(account.id) not in str(data)

    other = User(email="other@gmail.com")
    db.add(other)
    db.commit()
    r = client.post("/api/v1/backup", headers=H(other), json=data)
    assert r.status_code == 200, r.text
    assert r.json()["folders"] == 2 and r.json()["rules"] == 2 and r.json()["rules_disabled"] == 1  # demo account isn't theirs
    tree = client.get("/api/v1/folders", headers=H(other)).json()["folders"]
    assert [(f["name"], f["color"], [(k["name"], k["notify_mode"], k["pinned"]) for k in f["children"]]) for f in tree] == \
        [("Work", "#c6f432", [("Placements", "always", True)])]
    imported = db.scalar(select(Rule).where(Rule.user_id == other.id, Rule.name == "file placements"))
    assert imported.action["folder_id"] == tree[0]["children"][0]["id"] and imported.enabled is False and imported.account_scope
    assert client.get("/api/v1/settings", headers=H(other)).json()["resend_limit"] == 2


def test_bad_backup_changes_nothing(client, db, setup):
    user = setup[0]
    assert client.post("/api/v1/backup", headers=H(user), json={"format": "other"}).status_code == 422
    bad = {"format": "sift-backup", "version": 1, "folders": [{"ref": "a", "parent": None, "name": "Kept?"}],
           "rules": [{"name": "broken", "conditions": {"field": "nope"}, "action": {"type": "silent"}}]}
    assert client.post("/api/v1/backup", headers=H(user), json=bad).status_code == 422
    assert client.get("/api/v1/folders", headers=H(user)).json()["folders"] == []

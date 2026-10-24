"""Phase 3b: saved searches, smart folders, alerts on new matches, plain-English search."""
from sqlalchemy import select

from app.models import Folder, Notification, SavedSearch
from tests.test_pipeline import fake_llm, run, setup, with_key  # noqa: F401  (fixtures)
from tests.test_rule_tools import H


def save(client, user, **body):
    r = client.post("/api/v1/saved-searches", headers=H(user), json={"name": "x", "query": "priority:normal", **body})
    return r


def test_saved_search_crud_and_validation(client, db, setup):
    user, *_ = setup
    r = save(client, user, name="Normal mail", pinned=True)
    assert r.status_code == 201 and r.json()["smart_folder_id"] is None
    sid = r.json()["id"]
    assert save(client, user, name="normal MAIL").status_code == 409
    assert save(client, user, name="Bad", query="priority:loud").status_code == 422
    assert save(client, user, name="Loop", query="saved:x").status_code == 422
    r = client.patch(f"/api/v1/saved-searches/{sid}", headers=H(user), json={"smart_folder": True, "name": "Normal"}).json()
    f = db.get(Folder, __import__("uuid").UUID(r["smart_folder_id"]))
    assert f.name == "Normal" and f.saved_search_id is not None
    assert client.get("/api/v1/folders", headers=H(user)).json()["folders"][0]["smart"] is True
    assert client.delete(f"/api/v1/saved-searches/{sid}", headers=H(user)).status_code == 204
    db.expire_all()
    assert db.scalar(select(Folder)) is None  # the smart folder goes with it


def test_smart_folder_shows_its_search_and_refuses_filing(client, db, setup):
    user, account, provider, msgs = setup
    for m in msgs.values():
        run(db, account, provider, m)
    r = save(client, user, name="Quiet", query="is:silenced", smart_folder=True).json()
    view = client.get(f"/api/v1/folders/{r['smart_folder_id']}/threads", headers=H(user)).json()
    assert [i["subject"] for i in view["items"]] == ["Rs 240.00 debited from your account via UPI"]
    assert view["folder"]["smart"] and view["folder"]["query"] == "is:silenced"
    any_mail = view["items"][0]["id"]
    assert client.post(f"/api/v1/folders/{r['smart_folder_id']}/threads", headers=H(user), json={"message_ids": [any_mail]}).status_code == 422


def test_new_mail_matching_a_notifying_search_notifies_once(client, db, setup, fcm_sends):
    user, account, provider, msgs = setup
    db.add(SavedSearch(user_id=user.id, name="Kotak debits", query="from:kotak debited", notify=True))
    db.commit()
    out = run(db, account, provider, msgs["bank"])  # silenced by the starter bank rule...
    assert out.priority == "silent" and not out.notified
    n = db.scalar(select(Notification))
    assert n is not None and fcm_sends[-1]["title"].startswith("Kotak debits · ")  # ...but the user asked to hear about these
    sends = len(fcm_sends)
    out = run(db, account, provider, msgs["recruiter"])  # notifies on its own, not as a match
    assert out.notified and len(fcm_sends) == sends + 1 and "Kotak" not in fcm_sends[-1]["title"]


def test_non_matching_and_non_notifying_searches_stay_quiet(db, setup, fcm_sends):
    user, account, provider, msgs = setup
    db.add_all([SavedSearch(user_id=user.id, name="Zomato", query="from:zomato", notify=True),
                SavedSearch(user_id=user.id, name="Kotak", query="from:kotak", notify=False)])
    db.commit()
    run(db, account, provider, msgs["bank"])
    assert db.scalar(select(Notification)) is None and fcm_sends == []


def test_plain_english_search_needs_a_key_and_returns_checked_chips(client, db, setup, fake_llm):
    user, *_ = setup
    assert client.post("/api/v1/search/from-text", headers=H(user), json={"text": "walmart mail last week"}).status_code == 409
    with_key(db, user)
    r = client.post("/api/v1/search/from-text", headers=H(user), json={"text": "walmart mail last week"}).json()
    assert r["query"] == "from:walmart newer_than:7d" and [c["text"] for c in r["chips"]] == ["from:walmart", "newer_than:7d"]
    assert "TODAY:" in fake_llm.calls[-1]["prompt"] and "<request>" in fake_llm.calls[-1]["prompt"]
    fake_llm.search_query = "priority:loud"
    assert client.post("/api/v1/search/from-text", headers=H(user), json={"text": "x"}).status_code == 422

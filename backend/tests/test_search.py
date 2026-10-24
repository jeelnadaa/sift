"""Phase 3b: search across accounts (Gmail part + Sift filters), paging, saved searches, export."""
import uuid
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest
from sqlalchemy import select

from app import accounts as account_service
from app import folders
from app.mail.base import AuthRevoked
from app.models import GmailAccount, MailTag, Message, SavedSearch, Tag, User
from tests.test_rule_tools import H

T0 = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


class FakeGmail:
    """Gmail search over in-memory mail: q matches words in the subject; '-word' excludes."""

    def __init__(self, mails: list[dict]):
        self.mails = sorted(mails, key=lambda m: m["date"], reverse=True)
        self.list_calls = 0
        self.meta_calls = 0

    def search(self, q, token, size):
        self.list_calls += 1
        words = q.lower().split()
        hits = [m for m in self.mails if all((w[1:] not in m["subject"].lower()) if w.startswith("-") else (w in m["subject"].lower()) for w in words)]
        start = int(token or 0)
        page = hits[start:start + size]
        nxt = str(start + size) if start + size < len(hits) else None
        return [{"id": m["id"], "threadId": m["thread"]} for m in page], nxt, len(hits)

    def get_metadata(self, gid):
        self.meta_calls += 1
        m = next(x for x in self.mails if x["id"] == gid)
        return {"id": gid, "threadId": m["thread"], "labelIds": ["INBOX"], "snippet": m["subject"], "internalDate": str(int(m["date"].timestamp() * 1000)),
                "payload": {"headers": [{"name": "From", "value": "Old Sender <old@example.com>"}, {"name": "Subject", "value": m["subject"]},
                                        {"name": "Date", "value": format_datetime(m["date"])}]}}

    def get_thread(self, tid):
        return {"messages": [{"id": m["id"], "threadId": tid, "internalDate": "1", "labelIds": [], "payload": {"mimeType": "text/plain", "headers": [], "body": {}}}
                             for m in self.mails if m["thread"] == tid]}


@pytest.fixture
def world(db, keys, monkeypatch):
    user = User(email="owner@gmail.com")
    db.add(user)
    db.flush()
    a1 = GmailAccount(user_id=user.id, email="me@gmail.com", label="Personal", status="active", encrypted_refresh_token="x")
    a2 = GmailAccount(user_id=user.id, email="me@college.edu", label="College", status="active", encrypted_refresh_token="x")
    db.add_all([a1, a2])
    db.flush()
    g1 = FakeGmail([{"id": f"p{i}", "thread": f"pt{i}", "subject": f"invoice {i} personal", "date": T0 - timedelta(hours=2 * i)} for i in range(10)])
    g2 = FakeGmail([{"id": f"c{i}", "thread": f"ct{i}", "subject": f"invoice {i} college", "date": T0 - timedelta(hours=2 * i + 1)} for i in range(10)]
                   + [{"id": "c-reply", "thread": "ct0", "subject": "Re: invoice 0 college", "date": T0 - timedelta(minutes=30)}])
    # Sift stored a few of them (the rest are older mail Sift never processed)
    for gid, acc, g in (("p0", a1, g1), ("p1", a1, g1), ("c0", a2, g2)):
        m = next(x for x in g.mails if x["id"] == gid)
        db.add(Message(user_id=user.id, account_id=acc.id, gmail_id=gid, thread_id=m["thread"], subject=m["subject"], sender="bill@shop.com",
                       received_at=m["date"], status="processed", priority="normal", labels=["INBOX"]))
    db.commit()
    providers = {a1.id: g1, a2.id: g2}
    monkeypatch.setattr(account_service, "provider_for", lambda a: providers[a.id])
    return user, a1, a2, g1, g2


def search(client, user, q, **params):
    r = client.get("/api/v1/search", headers=H(user), params={"q": q, **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_merges_accounts_newest_first_one_row_per_conversation(client, world):
    user, a1, a2, g1, g2 = world
    r = search(client, user, "invoice", limit=5)
    subjects = [i["subject"] for i in r["items"]]
    # ct0's reply (newest in that thread) stands for the thread; no second ct0 row
    assert subjects == ["invoice 0 personal", "Re: invoice 0 college", "invoice 1 personal", "invoice 1 college", "invoice 2 personal"]
    assert [i["source"] for i in r["items"][:2]] == ["sift", "gmail"]
    assert r["items"][1]["id"] is None and r["items"][1]["account"] == "College" and r["estimated"] is True
    assert r["gmail_query"] == "invoice"


def test_pages_continue_without_repeats(client, world):
    user, *_ = world
    seen, cursor = [], None
    while True:
        r = search(client, user, "invoice", limit=6, **({"cursor": cursor} if cursor else {}))
        seen += [(i["account_id"], i["thread_id"]) for i in r["items"]]
        cursor = r["next_cursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 20  # 10 + 10 conversations, each once


def test_account_filter_limits_which_mailboxes_are_searched(client, world):
    user, a1, a2, g1, g2 = world
    r = search(client, user, "invoice account:college")
    assert {i["account"] for i in r["items"]} == {"College"} and g1.list_calls == 0
    r = search(client, user, "invoice -account:College")
    assert {i["account"] for i in r["items"]} == {"Personal"}


def test_sift_filters_apply_to_gmail_results(client, db, world):
    user, a1, a2, g1, g2 = world
    p1 = db.scalar(select(Message).where(Message.gmail_id == "p1"))
    tag = Tag(user_id=user.id, name="Paid")
    db.add(tag)
    db.flush()
    db.add(MailTag(tag_id=tag.id, message_id=p1.id))
    db.commit()
    r = search(client, user, "invoice tag:paid")
    assert [i["subject"] for i in r["items"]] == ["invoice 1 personal"]
    r = search(client, user, "invoice priority:normal -tag:Paid")
    assert sorted(i["subject"] for i in r["items"]) == ["invoice 0 college", "invoice 0 personal"]


def test_filters_alone_search_sifts_own_store(client, db, world):
    user, a1, a2, g1, g2 = world
    f = folders.create(db, user.id, "Bills")
    sub = folders.create(db, user.id, "Shop", f.id)
    folders.file_thread(db, user.id, sub, a2.id, "ct0")
    db.commit()
    r = search(client, user, "folder:bills")
    assert [i["subject"] for i in r["items"]] == ["invoice 0 college"] and r["estimated"] is False
    assert g1.list_calls == g2.list_calls == 0  # no Gmail call for a Sift-only search
    assert len(search(client, user, "folder:none")["items"]) == 2
    assert client.get("/api/v1/search", headers=H(user), params={"q": "folder:nope"}).status_code == 422


def test_one_failing_account_does_not_fail_the_search(client, world, monkeypatch):
    user, a1, a2, g1, g2 = world

    def broken(q, t, s):
        raise AuthRevoked("token expired")

    monkeypatch.setattr(g2, "search", broken)
    r = search(client, user, "invoice", limit=50)
    assert r["failed_accounts"] == ["me@college.edu"] and {i["account"] for i in r["items"]} == {"Personal"}


def test_saved_searches_expand_and_recent_searches_are_kept(client, db, world):
    user, *_ = world
    db.add(SavedSearch(user_id=user.id, name="Personal bills", query="invoice account:personal"))
    db.commit()
    r = search(client, user, "saved:\"personal bills\"")
    assert {i["account"] for i in r["items"]} == {"Personal"}
    s = client.get("/api/v1/search/suggest", headers=H(user), params={"q": "bill"}).json()
    assert s["saved"][0]["label"] == "Personal bills" and s["recent"][0]["query"] == 'saved:"personal bills"'
    assert s["senders"][0]["query"] == "from:bill@shop.com"
    assert client.get("/api/v1/search", headers=H(user), params={"q": "saved:missing"}).status_code == 422


def test_parse_endpoint_returns_chips_and_errors(client, world):
    user, *_ = world
    r = client.post("/api/v1/search/parse", headers=H(user), json={"q": "from:kotak -tag:done"}).json()
    assert r["gmail_query"] == "from:kotak" and [c["kind"] for c in r["chips"]] == ["gmail", "sift"] and r["chips"][1]["negated"]
    assert client.post("/api/v1/search/parse", headers=H(user), json={"q": "priority:loud"}).json()["error"]


def test_export_is_csv_and_defuses_formulas(client, db, world):
    user, a1, a2, g1, g2 = world
    g1.mails[0]["subject"] = "=HYPERLINK(\"http://evil\") invoice"
    db.scalar(select(Message).where(Message.gmail_id == "p0")).subject = "=HYPERLINK(\"http://evil\") invoice"
    db.commit()
    r = client.get("/api/v1/search/export", headers=H(user), params={"q": "invoice"})
    assert r.headers["content-type"].startswith("text/csv") and "'=HYPERLINK" in r.text and "\n=HYPERLINK" not in r.text


def test_reading_a_conversation_sift_never_stored(client, db, world, keys):
    user, a1, a2, g1, g2 = world
    r = client.get(f"/api/v1/accounts/{a2.id}/threads/ct5", headers=H(user))
    assert r.status_code == 200 and [m["gmail_id"] for m in r.json()["messages"]] == ["c5"]
    other = User(email="x@gmail.com")
    db.add(other)
    db.commit()
    assert client.get(f"/api/v1/accounts/{a2.id}/threads/ct5", headers=H(other)).status_code == 404
    assert client.get(f"/api/v1/accounts/{uuid.uuid4()}/threads/ct5", headers=H(user)).status_code == 404

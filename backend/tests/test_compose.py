"""Phase 4: building mail, replies and forwards, drafts, undo send, send later, follow-ups and AI
reply drafts."""
import base64
from datetime import UTC, datetime, timedelta
from email import message_from_bytes, policy

import pytest
from sqlalchemy import select

from app import accounts as account_service
from app import compose, outbox
from app.mail import google_oauth
from app.mail.gmail import GmailError
from app.models import Device, FollowUp, GmailAccount, Message, Outbox, User
from tests.test_pipeline import fake_llm, with_key  # noqa: F401  (fixture)
from tests.test_rule_tools import H


def b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode()


ORIGINAL = {
    "id": "orig1", "threadId": "thr1", "snippet": "Can you come?",
    "payload": {"mimeType": "multipart/mixed", "headers": [
        {"name": "From", "value": "Asha Rao <asha@acme.com>"},
        {"name": "To", "value": "me@gmail.com, Ben <ben@acme.com>"},
        {"name": "Cc", "value": "carol@acme.com, me@gmail.com"},
        {"name": "Subject", "value": "Interview on Friday"},
        {"name": "Message-ID", "value": "<abc@acme.com>"},
        {"name": "References", "value": "<zero@acme.com>"},
        {"name": "Date", "value": "Fri, 23 Oct 2026 10:00:00 +0530"},
    ], "parts": [
        {"mimeType": "text/plain", "body": {"data": b64("Can you come at 3?\nCall me on 98765 43210.")}},
        {"mimeType": "application/pdf", "filename": "jd.pdf", "body": {"attachmentId": "att1", "size": 5}},
    ]},
}


class FakeGmail:
    def __init__(self):
        self.drafts: dict[str, tuple[bytes, str | None]] = {}
        self.sent: list[str] = []
        self.fail_send: Exception | None = None
        self.n = 0

    def get_full(self, mid):
        assert mid == "orig1"
        return ORIGINAL

    def get_thread(self, tid):
        return {"messages": [ORIGINAL]}

    def get_attachment(self, mid, aid):
        return b"%PDF-"

    def create_draft(self, raw, thread_id):
        self.n += 1
        did = f"d{self.n}"
        self.drafts[did] = (raw, thread_id)
        return {"id": did, "message": {"id": f"m{self.n}", "threadId": thread_id or f"new{self.n}"}}

    def update_draft(self, did, raw, thread_id):
        if did not in self.drafts:
            raise GmailError(404, "gone")
        self.drafts[did] = (raw, thread_id)
        return {"id": did}

    def get_draft_raw(self, did):
        if did not in self.drafts:
            raise GmailError(404, "gone")
        return self.drafts[did]

    def get_draft_meta(self, did):
        if did not in self.drafts:
            raise GmailError(404, "gone")
        return {"id": did, "message": {"threadId": self.drafts[did][1], "payload": {"headers": []}}}

    def list_drafts(self, limit=25):
        return [{"id": d} for d in self.drafts]

    def delete_draft(self, did):
        self.drafts.pop(did)

    def send_draft(self, did):
        if self.fail_send:
            raise self.fail_send
        if did not in self.drafts:
            raise GmailError(404, "gone")
        _, thread = self.drafts.pop(did)
        self.sent.append(did)
        return {"id": f"sent-{did}", "threadId": thread or "thr-new"}


@pytest.fixture
def world(db, keys, monkeypatch, fcm_sends):
    user = User(email="owner@gmail.com")
    db.add(user)
    db.flush()
    db.add(Device(user_id=user.id, fcm_token="phone"))
    acc = GmailAccount(user_id=user.id, email="me@gmail.com", status="active", encrypted_refresh_token="x",
                       scopes=[google_oauth.READONLY_SCOPE, google_oauth.MODIFY_SCOPE])
    db.add(acc)
    db.flush()
    msg = Message(user_id=user.id, account_id=acc.id, gmail_id="orig1", thread_id="thr1", subject="Interview on Friday",
                  sender="asha@acme.com", status="processed", priority="normal", received_at=datetime.now(UTC) - timedelta(hours=1))
    db.add(msg)
    db.commit()
    g = FakeGmail()
    monkeypatch.setattr(account_service, "provider_for", lambda a: g)
    return user, acc, msg, g


def parsed(raw: bytes):
    return message_from_bytes(raw, policy=policy.default)


# ---- building ---------------------------------------------------------------------------------

def test_addresses_are_checked_and_deduplicated():
    assert compose.addresses(["Asha <asha@acme.com>, asha@acme.com", "b@x.io"]) == ["Asha <asha@acme.com>", "b@x.io"]
    for bad in ("not-an-address", "a@b", "a@-x.com", "a b@x.com"):
        with pytest.raises(compose.ComposeError):
            compose.addresses([bad])


def test_header_line_breaks_cannot_inject_headers():
    raw = compose.build("me@gmail.com", "Me", compose.Draft(to=["a@x.com"], subject="Hi\r\nBcc: victim@x.com", body="x"))
    m = parsed(raw)
    assert m["Bcc"] is None and "victim" in m["Subject"]  # folded into the subject, not a header
    with pytest.raises(compose.ComposeError):
        compose.build("me@gmail.com", "Me\nBcc: v@x.com", compose.Draft(to=["a@x.com"], body="x"))


def test_build_and_parse_round_trip_with_attachment_and_html():
    d = compose.Draft(to=["Asha <asha@acme.com>"], cc=["c@x.com"], bcc=["secret@x.com"], subject="Re: Hi", body="See https://x.com/a.\n> quoted <b>",
                      in_reply_to="<abc@acme.com>", references="<z@a> <abc@acme.com>",
                      attachments=[compose.Attachment("cv.pdf", "application/pdf", b"%PDF-1")])
    raw = compose.build("me@gmail.com", "Jeel", d)
    m = parsed(raw)
    assert m["From"] == "Jeel <me@gmail.com>" and m["In-Reply-To"] == "<abc@acme.com>"
    html = m.get_body(preferencelist=("html",)).get_content()
    assert '<a href="https://x.com/a">' in html and "<blockquote" in html and "&lt;b&gt;" in html
    back = compose.parse(raw)
    assert back.to == ["Asha <asha@acme.com>"] and back.bcc == ["secret@x.com"] and back.body.startswith("See https://x.com/a.")
    assert back.attachments[0].filename == "cv.pdf" and back.attachments[0].data == b"%PDF-1"


def test_attachments_over_25_mb_are_refused():
    big = compose.Attachment("big.bin", "application/octet-stream", b"0" * (compose.MAX_TOTAL_BYTES + 1))
    with pytest.raises(compose.ComposeError):
        compose.build("me@gmail.com", "", compose.Draft(to=["a@x.com"], attachments=[big]))


# ---- reply / forward details ------------------------------------------------------------------

def test_reply_goes_to_the_sender_with_threading_and_a_quote():
    c = compose.context(ORIGINAL, "reply", "me@gmail.com")
    assert c["to"] == ["Asha Rao <asha@acme.com>"] and c["cc"] == []
    assert c["subject"] == "Re: Interview on Friday" and c["in_reply_to"] == "<abc@acme.com>"
    assert c["references"] == "<zero@acme.com> <abc@acme.com>" and c["thread_id"] == "thr1"
    assert "> Can you come at 3?" in c["body"] and "Asha Rao <asha@acme.com> wrote:" in c["body"]


def test_reply_all_leaves_me_out_and_keeps_everyone_else_once():
    c = compose.context(ORIGINAL, "reply_all", "ME@gmail.com")
    assert c["to"] == ["Asha Rao <asha@acme.com>"]
    assert c["cc"] == ["Ben <ben@acme.com>", "carol@acme.com"]


def test_reply_to_my_own_mail_goes_to_its_recipients():
    mine = {**ORIGINAL, "payload": {**ORIGINAL["payload"], "headers": [
        {"name": "From", "value": "me@gmail.com"}, {"name": "To", "value": "asha@acme.com"}, {"name": "Subject", "value": "Re: x"}]}}
    c = compose.context(mine, "reply", "me@gmail.com")
    assert c["to"] == ["asha@acme.com"] and c["subject"] == "Re: x"


def test_forward_starts_a_new_conversation_with_the_original_below():
    c = compose.context(ORIGINAL, "forward", "me@gmail.com")
    assert c["to"] == [] and c["subject"] == "Fwd: Interview on Friday" and c["thread_id"] is None
    assert "Forwarded message" in c["body"] and "Can you come at 3?" in c["body"] and c["forward_gmail_id"] == "orig1"


# ---- drafts over the API ----------------------------------------------------------------------

def new_draft(client, user, acc, **kw):
    body = {"account_id": str(acc.id), "to": ["asha@acme.com"], "subject": "Hello", "body": "Hi Asha", **kw}
    return client.post("/api/v1/compose/drafts", headers=H(user), json=body)


def test_read_only_account_is_asked_for_write_access(client, db, world):
    user, acc, msg, g = world
    acc.scopes = [google_oauth.READONLY_SCOPE]
    db.commit()
    r = new_draft(client, user, acc)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "needs_write_access" and g.drafts == {}


def test_demo_account_cannot_send(client, db, world):
    user, acc, msg, g = world
    acc.email, acc.encrypted_refresh_token = "demo+1@demo.sift.local", None
    db.commit()
    assert new_draft(client, user, acc).status_code == 400


def test_autosave_keeps_attachments_and_reply_headers(client, db, world):
    user, acc, msg, g = world
    ctx = client.get("/api/v1/compose/context", headers=H(user), params={"mode": "reply", "message_id": str(msg.id)}).json()
    d = new_draft(client, user, acc, to=ctx["to"], subject=ctx["subject"], body="Yes!" + ctx["body"], thread_id=ctx["thread_id"],
                  in_reply_to=ctx["in_reply_to"], references=ctx["references"]).json()
    assert d["thread_id"] == "thr1"
    did = d["draft_id"]
    r = client.post(f"/api/v1/compose/drafts/{acc.id}/{did}/attachments", headers={**H(user), "Content-Type": "application/pdf"},
                    params={"filename": "cv.pdf"}, content=b"%PDF-1.7")
    assert r.status_code == 200 and r.json()["attachments"][0]["filename"] == "cv.pdf"
    r = client.put(f"/api/v1/compose/drafts/{acc.id}/{did}", headers=H(user), json={"to": ["asha@acme.com"], "subject": ctx["subject"], "body": "Yes, 3 works."})
    assert r.status_code == 200
    m = parsed(g.drafts[did][0])
    assert m["In-Reply-To"] == "<abc@acme.com>" and [a.get_filename() for a in m.iter_attachments()] == ["cv.pdf"]
    assert g.drafts[did][1] == "thr1"
    r = client.delete(f"/api/v1/compose/drafts/{acc.id}/{did}/attachments/0", headers=H(user))
    assert r.json()["attachments"] == []
    loaded = client.get(f"/api/v1/compose/drafts/{acc.id}/{did}", headers=H(user)).json()
    assert loaded["body"] == "Yes, 3 works." and loaded["outbox"] is None


def test_forward_carries_the_original_attachments(client, db, world):
    user, acc, msg, g = world
    ctx = client.get("/api/v1/compose/context", headers=H(user), params={"mode": "forward", "message_id": str(msg.id)}).json()
    assert ctx["attachments"] == [{"filename": "jd.pdf", "mime": "application/pdf", "size": 5}]
    d = new_draft(client, user, acc, to=["x@y.com"], subject=ctx["subject"], body=ctx["body"], forward_gmail_id=ctx["forward_gmail_id"]).json()
    assert [a["filename"] for a in d["attachments"]] == ["jd.pdf"]


def test_invalid_recipient_is_refused(client, db, world):
    user, acc, msg, g = world
    r = new_draft(client, user, acc, to=["nobody"])
    assert r.status_code == 422 and "Not an email address" in r.json()["detail"]


# ---- sending ---------------------------------------------------------------------------------

def test_send_waits_for_the_undo_window_and_undo_keeps_the_draft(client, db, world):
    user, acc, msg, g = world
    did = new_draft(client, user, acc).json()["draft_id"]
    r = client.post(f"/api/v1/compose/drafts/{acc.id}/{did}/send", headers=H(user), json={}).json()
    assert r["status"] == "scheduled" and r["undo_seconds"] == 10 and r["recipients"] == "asha@acme.com"
    assert outbox.send_due() == 0 and g.sent == []  # not due yet
    assert client.post(f"/api/v1/outbox/{r['id']}/cancel", headers=H(user)).json()["status"] == "cancelled"
    assert did in g.drafts and g.sent == []


def test_due_mail_is_sent_exactly_once_and_follow_up_created(client, db, world):
    user, acc, msg, g = world
    did = new_draft(client, user, acc, thread_id="thr1").json()["draft_id"]
    r = client.post(f"/api/v1/compose/drafts/{acc.id}/{did}/send", headers=H(user), json={"follow_up_days": 3}).json()
    db.execute(Outbox.__table__.update().values(send_at=datetime.now(UTC) - timedelta(seconds=1)))
    db.commit()
    assert outbox.send_due() == 1 and outbox.send_due() == 0
    assert g.sent == [did]
    row = db.get(Outbox, __import__("uuid").UUID(r["id"]))
    db.refresh(row)
    assert row.status == "sent" and row.sent_gmail_id == f"sent-{did}"
    f = db.scalar(select(FollowUp))
    assert f.thread_id == "thr1" and f.status == "waiting" and (f.due_at - f.sent_at).days == 3
    assert client.post(f"/api/v1/outbox/{r['id']}/cancel", headers=H(user)).status_code == 409  # too late to undo


def test_no_undo_window_sends_at_once(client, db, world):
    user, acc, msg, g = world
    client.patch("/api/v1/settings", headers=H(user), json={"undo_send_seconds": 0})
    did = new_draft(client, user, acc).json()["draft_id"]
    r = client.post(f"/api/v1/compose/drafts/{acc.id}/{did}/send", headers=H(user), json={}).json()
    assert r["status"] == "sent" and g.sent == [did]


def test_send_needs_a_recipient(client, db, world):
    user, acc, msg, g = world
    did = new_draft(client, user, acc, to=[]).json()["draft_id"]
    r = client.post(f"/api/v1/compose/drafts/{acc.id}/{did}/send", headers=H(user), json={})
    assert r.status_code == 422 and "recipient" in r.json()["detail"]


def test_send_later_validates_the_time_and_can_be_moved_or_sent_now(client, db, world):
    user, acc, msg, g = world
    did = new_draft(client, user, acc).json()["draft_id"]
    url = f"/api/v1/compose/drafts/{acc.id}/{did}/send"
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    assert client.post(url, headers=H(user), json={"send_at": past}).status_code == 422
    assert client.post(url, headers=H(user), json={"send_at": "2026-12-01T09:00:00"}).status_code == 422  # no zone
    later = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    r = client.post(url, headers=H(user), json={"send_at": later}).json()
    assert r["later"] is True and r["undo_seconds"] == 0
    listed = client.get("/api/v1/compose/drafts", headers=H(user)).json()["drafts"]
    assert listed[0]["outbox"]["id"] == r["id"]
    # autosave can still edit a mail scheduled for later
    assert client.put(f"/api/v1/compose/drafts/{acc.id}/{did}", headers=H(user), json={"to": ["asha@acme.com"], "body": "edited"}).status_code == 200
    moved = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    assert client.patch(f"/api/v1/outbox/{r['id']}", headers=H(user), json={"send_at": moved}).status_code == 200
    assert client.post(f"/api/v1/outbox/{r['id']}/send-now", headers=H(user)).status_code == 200
    assert outbox.send_due() == 1 and g.sent == [did]
    assert client.get("/api/v1/outbox", headers=H(user)).json()["recent"][0]["status"] == "sent"


def test_deleted_draft_fails_with_a_notification(client, db, world, fcm_sends):
    user, acc, msg, g = world
    did = new_draft(client, user, acc).json()["draft_id"]
    client.post(f"/api/v1/compose/drafts/{acc.id}/{did}/send", headers=H(user), json={})
    g.drafts.clear()
    db.execute(Outbox.__table__.update().values(send_at=datetime.now(UTC)))
    db.commit()
    outbox.send_due()
    row = db.scalar(select(Outbox))
    assert row.status == "failed" and "deleted" in row.error
    assert any(s.get("title") == "Couldn't send your mail" for s in fcm_sends)


def test_gmail_outage_retries_then_sends(client, db, world):
    user, acc, msg, g = world
    did = new_draft(client, user, acc).json()["draft_id"]
    client.post(f"/api/v1/compose/drafts/{acc.id}/{did}/send", headers=H(user), json={})
    db.execute(Outbox.__table__.update().values(send_at=datetime.now(UTC)))
    db.commit()
    g.fail_send = GmailError(503, "busy")
    outbox.send_due()
    row = db.scalar(select(Outbox))
    assert row.status == "scheduled" and row.send_at > datetime.now(UTC) and "retrying" in row.error
    g.fail_send = None
    db.execute(Outbox.__table__.update().values(send_at=datetime.now(UTC)))
    db.commit()
    assert outbox.send_due() == 1


def test_stuck_sending_row_is_settled_by_whether_gmail_still_has_the_draft(client, db, world):
    user, acc, msg, g = world
    a = new_draft(client, user, acc).json()["draft_id"]
    b = new_draft(client, user, acc).json()["draft_id"]
    old = datetime.now(UTC) - timedelta(minutes=10)
    for did in (a, b):
        db.add(Outbox(user_id=user.id, account_id=acc.id, draft_id=did, send_at=old, status="sending", sending_since=old))
    db.commit()
    g.drafts.pop(a)  # Gmail sent it before the worker died
    outbox.send_due()
    rows = {r.draft_id: r.status for r in db.scalars(select(Outbox))}
    assert rows[a] == "sent" and rows[b] == "sent" and g.sent == [b]  # b went back to scheduled and was sent once


def test_discarding_a_scheduled_draft_cancels_it(client, db, world):
    user, acc, msg, g = world
    did = new_draft(client, user, acc).json()["draft_id"]
    r = client.post(f"/api/v1/compose/drafts/{acc.id}/{did}/send", headers=H(user),
                    json={"send_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat()}).json()
    assert client.delete(f"/api/v1/compose/drafts/{acc.id}/{did}", headers=H(user)).status_code == 200
    assert did not in g.drafts and db.scalar(select(Outbox)).status == "cancelled"
    assert r["id"]


def test_other_users_cannot_touch_my_outbox(client, db, world):
    user, acc, msg, g = world
    did = new_draft(client, user, acc).json()["draft_id"]
    r = client.post(f"/api/v1/compose/drafts/{acc.id}/{did}/send", headers=H(user), json={}).json()
    other = User(email="x@gmail.com")
    db.add(other)
    db.commit()
    assert client.post(f"/api/v1/outbox/{r['id']}/cancel", headers=H(other)).status_code == 404
    assert client.get(f"/api/v1/compose/drafts/{acc.id}/{did}", headers=H(other)).status_code == 404


# ---- follow-ups ------------------------------------------------------------------------------

def follow_up(db, user, acc, days_ago=4):
    sent = datetime.now(UTC) - timedelta(days=days_ago)
    f = FollowUp(user_id=user.id, account_id=acc.id, thread_id="thr9", subject="Offer letter", recipients="hr@acme.com",
                 sent_at=sent, due_at=sent + timedelta(days=3))
    db.add(f)
    db.commit()
    return f


def test_follow_up_reminds_once_when_nobody_replied(db, world, fcm_sends):
    user, acc, msg, g = world
    f = follow_up(db, user, acc)
    assert outbox.remind_due(db) == 1 and outbox.remind_due(db) == 0
    db.refresh(f)
    assert f.status == "reminded" and any(s.get("title") == "No reply yet" for s in fcm_sends)


def test_a_reply_resolves_the_follow_up(db, world, fcm_sends):
    user, acc, msg, g = world
    f = follow_up(db, user, acc)
    reply = Message(user_id=user.id, account_id=acc.id, gmail_id="r1", thread_id="thr9", sender="hr@acme.com",
                    status="processed", received_at=datetime.now(UTC) - timedelta(days=1))
    db.add(reply)
    db.flush()
    outbox.on_new_mail(db, reply, acc)
    db.commit()
    db.refresh(f)
    assert f.status == "replied" and outbox.remind_due(db) == 0


def test_my_own_message_in_the_thread_is_not_a_reply(db, world):
    user, acc, msg, g = world
    f = follow_up(db, user, acc)
    mine = Message(user_id=user.id, account_id=acc.id, gmail_id="r2", thread_id="thr9", sender="me@gmail.com",
                   status="processed", received_at=datetime.now(UTC))
    db.add(mine)
    db.flush()
    outbox.on_new_mail(db, mine, acc)
    assert f.status == "waiting" and outbox.remind_due(db) == 1


# ---- AI reply drafts -------------------------------------------------------------------------

def test_ai_reply_needs_a_key_and_makes_no_call_without_one(client, db, world, fake_llm):
    user, acc, msg, g = world
    r = client.post("/api/v1/compose/ai-draft", headers=H(user), json={"message_id": str(msg.id)})
    assert r.status_code == 409 and "API key" in r.json()["detail"] and fake_llm.calls == []


def test_ai_reply_is_redacted_and_returned_for_review(client, db, world, fake_llm):
    user, acc, msg, g = world
    with_key(db, user)
    r = client.post("/api/v1/compose/ai-draft", headers=H(user), json={"message_id": str(msg.id), "instructions": "say yes"})
    assert r.status_code == 200 and r.json()["body"].startswith("Thanks")
    prompt = fake_llm.calls[0]["prompt"]
    assert "98765 43210" not in prompt and "[phone]" in prompt and "say yes" in prompt
    assert "untrusted" in fake_llm.calls[0]["system"]
    assert g.drafts == {} and g.sent == []  # nothing is written or sent by the AI


def test_compose_settings_are_validated(client, db, world):
    user, *_ = world
    assert client.patch("/api/v1/settings", headers=H(user), json={"sender_name": "Jeel <x>"}).status_code == 422
    assert client.patch("/api/v1/settings", headers=H(user), json={"undo_send_seconds": 99}).status_code == 422
    s = client.patch("/api/v1/settings", headers=H(user), json={"sender_name": "Jeel Nadaa", "signature": "Jeel\r\nSift"}).json()
    assert s["sender_name"] == "Jeel Nadaa" and s["signature"] == "Jeel\nSift"

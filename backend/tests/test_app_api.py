import json

import httpx
import pytest
from sqlalchemy import select

from app import demo
from app.llm import gemini
from app.llm import service as llm
from app.llm.base import LlmAuthError, LlmQuotaError
from app.models import Device, GmailAccount, LlmCredential, Notification, User
from app.pipeline import process_message
from app.security import hash_password
from tests.test_pipeline import FakeLlm


@pytest.fixture
def owner(db, keys):
    u = User(email="owner@gmail.com", password_hash=hash_password("correct horse"))
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def auth(client, owner):
    r = client.post("/api/v1/auth/login", json={"email": "Owner@Gmail.com ", "password": "correct horse"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ---- sign-in -----------------------------------------------------------------------------

def test_login_rejects_wrong_password_and_unknown_user(client, owner):
    assert client.post("/api/v1/auth/login", json={"email": "owner@gmail.com", "password": "nope"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "who@x.com", "password": "correct horse"}).status_code == 401


def test_endpoints_require_a_valid_token(client, auth):
    assert client.get("/api/v1/me", headers=auth).json()["email"] == "owner@gmail.com"
    for path in ("/api/v1/me", "/api/v1/messages", "/api/v1/rules", "/api/v1/settings", "/api/v1/ai", "/api/v1/accounts"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer forged.token.value"}).status_code == 401


def test_user_without_password_cannot_sign_in(client, db, keys):
    db.add(User(email="nopw@gmail.com"))
    db.commit()
    assert client.post("/api/v1/auth/login", json={"email": "nopw@gmail.com", "password": ""}).status_code == 401


# ---- messages ---------------------------------------------------------------------------

@pytest.fixture
def mail(db, owner, fcm_sends):
    db.add(Device(user_id=owner.id, fcm_token="phone-token-123"))
    demo.ensure_starter_rules(db, owner)
    account = demo.demo_account(db, owner)
    db.commit()
    msgs = demo.samples()
    provider = demo.DemoProvider(msgs)
    for m in msgs:
        process_message(db, db.get(GmailAccount, account.id), provider, m["id"])
    return account


def test_feed_excludes_silenced_mail_and_filters(client, auth, mail):
    feed = client.get("/api/v1/messages", headers=auth).json()["items"]
    assert len(feed) == 4 and all(m["priority"] == "normal" for m in feed)
    assert all(m["account"] == "Demo" for m in feed)
    silenced = client.get("/api/v1/messages", params={"view": "silenced"}, headers=auth).json()["items"]
    assert [m["subject"] for m in silenced] == ["Rs 240.00 debited from your account via UPI"]
    assert client.get("/api/v1/messages", params={"priority": "urgent"}, headers=auth).json()["items"] == []


def test_message_detail_and_ack(client, auth, mail, db):
    item = client.get("/api/v1/messages", headers=auth).json()["items"][0]
    detail = client.get(f"/api/v1/messages/{item['id']}", headers=auth).json()
    assert detail["notified_at"] and detail["delivered_at"] is None
    n = db.scalar(select(Notification).where(Notification.message_id == item["id"]))
    assert client.post(f"/api/v1/notifications/{n.id}/ack", headers=auth).status_code == 204
    assert client.get(f"/api/v1/messages/{item['id']}", headers=auth).json()["delivered_at"]


def test_other_users_mail_is_invisible(client, mail, db, keys):
    other = User(email="other@gmail.com", password_hash=hash_password("other password"))
    db.add(other)
    db.commit()
    token = client.post("/api/v1/auth/login", json={"email": "other@gmail.com", "password": "other password"}).json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/messages", headers=h).json()["items"] == []
    some = db.scalar(select(Notification))
    assert client.get(f"/api/v1/messages/{some.message_id}", headers=h).status_code == 404
    assert client.post(f"/api/v1/notifications/{some.id}/ack", headers=h).status_code == 404


# ---- rules ------------------------------------------------------------------------------

def test_rule_crud_validation_and_reorder(client, auth):
    good = {"name": "Placement urgent", "conditions": {"field": "sender_domain", "op": "is", "value": "univ.edu"}, "action": {"type": "notify_urgent"}}
    a = client.post("/api/v1/rules", json=good, headers=auth).json()
    b = client.post("/api/v1/rules", json={**good, "name": "Second"}, headers=auth).json()
    assert (a["position"], b["position"]) == (1, 2)
    bad = client.post("/api/v1/rules", json={**good, "conditions": {"field": "subject", "op": "matches", "value": "("}}, headers=auth)
    assert bad.status_code == 422 and "regex" in bad.json()["detail"]
    assert client.post("/api/v1/rules", json={**good, "action": {"type": "delete_mail"}}, headers=auth).status_code == 422
    order = client.post("/api/v1/rules/reorder", json={"ids": [b["id"], a["id"]]}, headers=auth).json()
    assert [r["name"] for r in order] == ["Second", "Placement urgent"]
    assert client.post("/api/v1/rules/reorder", json={"ids": [a["id"]]}, headers=auth).status_code == 422
    upd = client.put(f"/api/v1/rules/{a['id']}", json={**good, "enabled": False}, headers=auth).json()
    assert upd["enabled"] is False
    assert client.delete(f"/api/v1/rules/{a['id']}", headers=auth).status_code == 204
    assert len(client.get("/api/v1/rules", headers=auth).json()) == 1


# ---- settings and AI key -------------------------------------------------------------------

def test_settings_patch_validates(client, auth):
    assert client.get("/api/v1/settings", headers=auth).json()["resend_after_minutes"] == 5
    assert client.patch("/api/v1/settings", json={"resend_after_minutes": 2}, headers=auth).json()["resend_after_minutes"] == 2
    assert client.patch("/api/v1/settings", json={"evil": 1}, headers=auth).status_code == 422


def test_ai_key_is_validated_stored_encrypted_and_never_returned(client, auth, db, monkeypatch):
    fake = FakeLlm()
    monkeypatch.setattr(llm, "provider_factory", lambda p, k, m: fake)
    status = client.get("/api/v1/ai", headers=auth).json()
    assert (status["status"], status["ai_enabled"]) == ("missing", False)

    key = "AIzaSyTESTKEY1234567890abcd"
    r = client.put("/api/v1/ai/key", json={"provider": "gemini", "model": "gemini-3.5-flash-lite", "api_key": key}, headers=auth)
    body = r.json()
    assert r.status_code == 200 and body["status"] == "valid" and body["ai_enabled"] and body["key_last4"] == "abcd"
    assert key not in r.text and key not in client.get("/api/v1/ai", headers=auth).text
    stored = db.scalar(select(LlmCredential))
    assert key not in stored.encrypted_api_key

    fake.ping = lambda: (_ for _ in ()).throw(LlmAuthError("bad"))
    assert client.post("/api/v1/ai/test", headers=auth).json()["status"] == "invalid"
    fake.ping = lambda: (_ for _ in ()).throw(LlmQuotaError("429"))
    assert client.post("/api/v1/ai/test", headers=auth).json()["status"] == "quota_exceeded"
    assert client.delete("/api/v1/ai/key", headers=auth).status_code == 204
    assert client.get("/api/v1/ai", headers=auth).json()["status"] == "missing"


def test_devices_require_sign_in_and_upsert(client, auth, db):
    payload = {"fcm_token": "token-1234567890", "label": "Pixel"}
    assert client.post("/api/v1/devices", json=payload).status_code == 401
    client.post("/api/v1/devices", json=payload, headers=auth)
    client.post("/api/v1/devices", json={**payload, "label": "Pixel 9"}, headers=auth)
    assert list(db.scalars(select(Device.label))) == ["Pixel 9"]


# ---- Gemini provider wire format --------------------------------------------------------------

def gemini_client(responses):
    seen = []

    def handler(request):
        seen.append(request)
        status, body = responses.pop(0)
        return httpx.Response(status, json=body)
    return httpx.Client(transport=httpx.MockTransport(handler)), seen


OK = {"candidates": [{"content": {"parts": [{"text": '{"a": 1}'}]}}], "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 30, "thoughtsTokenCount": 5}}


def test_gemini_request_shape_and_usage():
    client, seen = gemini_client([(200, OK)])
    r = gemini.GeminiProvider("secret-key", "gemini-x", client).generate_json("SYS", "PROMPT", {"type": "object"})
    req = seen[0]
    assert str(req.url) == "https://generativelanguage.googleapis.com/v1beta/models/gemini-x:generateContent"
    assert req.headers["x-goog-api-key"] == "secret-key" and "secret-key" not in str(req.url)
    body = json.loads(req.content)
    assert body["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "minimal"}
    assert (r.text, r.input_tokens, r.output_tokens) == ('{"a": 1}', 120, 35)


def test_gemini_retries_without_thinking_config_when_model_rejects_it():
    gemini._no_thinking_config.discard("old-model")
    client, seen = gemini_client([(400, {"error": {"message": "Thinking level is not supported for this model."}}), (200, OK)])
    gemini.GeminiProvider("k", "old-model", client).generate_json("S", "P", {})
    assert "thinkingConfig" not in json.loads(seen[1].content)["generationConfig"]


@pytest.mark.parametrize("status,error,exc", [
    (400, {"status": "INVALID_ARGUMENT", "message": "API key not valid. Please pass a valid API key.", "details": [{"reason": "API_KEY_INVALID"}]}, LlmAuthError),
    (403, {"status": "PERMISSION_DENIED", "message": "Your API key was reported as leaked."}, LlmAuthError),
    (429, {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded"}, LlmQuotaError),
])
def test_gemini_error_mapping(status, error, exc):
    client, _ = gemini_client([(status, {"error": error})])
    with pytest.raises(exc):
        gemini.GeminiProvider("k", "m", client).ping()

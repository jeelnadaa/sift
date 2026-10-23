import base64
import json

import pytest

from app.pubsub import PushAuthError, PushPayloadError, parse_gmail_push, verify_push_token

GOOD = {"iss": "https://accounts.google.com", "email": "push@proj.iam.gserviceaccount.com", "email_verified": True, "aud": "x"}


def body(data: dict | str, message_id: str = "m1") -> dict:
    raw = data if isinstance(data, str) else base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return {"message": {"data": raw, "messageId": message_id}, "subscription": "projects/p/subscriptions/s"}


def verifier_returning(claims):
    def v(token, request, audience):
        assert token == "tok"
        return claims
    return v


def test_parse_valid_push_lowercases_email_and_handles_missing_padding():
    push = parse_gmail_push(body({"emailAddress": "Me@Gmail.com", "historyId": 4242}))
    assert (push.email, push.history_id, push.pubsub_message_id) == ("me@gmail.com", 4242, "m1")


@pytest.mark.parametrize("bad", [{}, {"message": {}}, body("not base64!!"), body({"emailAddress": "a@b.c"}), body({"historyId": "x", "emailAddress": "a@b.c"})])
def test_parse_rejects_malformed(bad):
    with pytest.raises(PushPayloadError):
        parse_gmail_push(bad)


def test_verify_accepts_valid_token(settings):
    assert verify_push_token("Bearer tok", settings, verifier_returning(GOOD)) == GOOD


@pytest.mark.parametrize("header", [None, "", "Basic abc", "tok"])
def test_verify_requires_bearer(settings, header):
    with pytest.raises(PushAuthError):
        verify_push_token(header, settings, verifier_returning(GOOD))


@pytest.mark.parametrize("claims", [
    {**GOOD, "email": "attacker@evil.iam.gserviceaccount.com"},
    {**GOOD, "email_verified": False},
    {**GOOD, "iss": "https://evil.example"},
])
def test_verify_rejects_wrong_claims(settings, claims):
    with pytest.raises(PushAuthError):
        verify_push_token("Bearer tok", settings, verifier_returning(claims))


def test_verify_rejects_bad_signature(settings):
    def raising(*a, **k):
        raise ValueError("bad signature")
    with pytest.raises(PushAuthError):
        verify_push_token("Bearer tok", settings, raising)


def test_verify_refuses_when_not_configured(override_settings):
    s = override_settings(pubsub_audience="")
    with pytest.raises(PushAuthError):
        verify_push_token("Bearer tok", s, verifier_returning(GOOD))

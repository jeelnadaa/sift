import httpx
import pytest

from app import fcm


def test_build_message_is_data_only_high_priority_with_string_values():
    msg = fcm.build_message("tok", {"priority": "urgent", "count": 3, "missing": None})["message"]
    assert msg["token"] == "tok"
    assert msg["android"] == {"priority": "high"}
    assert "notification" not in msg
    assert msg["data"] == {"priority": "urgent", "count": "3", "missing": ""}


@pytest.mark.parametrize("status,code,invalid,retry", [
    (404, "UNREGISTERED", True, False),
    (503, "UNAVAILABLE", False, True),
    (429, "QUOTA_EXCEEDED", False, True),
    (500, "INTERNAL", False, True),
    (400, "INVALID_ARGUMENT", False, False),
])
def test_classify_error(status, code, invalid, retry):
    body = {"error": {"status": "X", "details": [{"@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError", "errorCode": code}]}}
    r = fcm.classify_error(status, body)
    assert (r.ok, r.token_invalid, r.retryable, r.error) == (False, invalid, retry, code)


@pytest.fixture
def fake_fcm(monkeypatch, override_settings):
    override_settings(firebase_project_id="proj")
    monkeypatch.setattr(fcm, "_access_token", lambda: "access")
    calls = []

    def make(status, payload):
        def handler(request):
            calls.append(request)
            return httpx.Response(status, json=payload)
        return httpx.Client(transport=httpx.MockTransport(handler))
    return make, calls


def test_send_success_posts_to_v1_endpoint(fake_fcm):
    make, calls = fake_fcm
    r = fcm.send("tok", {"a": 1}, client=make(200, {"name": "projects/proj/messages/1"}))
    assert r.ok and r.name == "projects/proj/messages/1"
    assert str(calls[0].url) == "https://fcm.googleapis.com/v1/projects/proj/messages:send"
    assert calls[0].headers["authorization"] == "Bearer access"


def test_send_unregistered_marks_token_invalid(fake_fcm):
    make, _ = fake_fcm
    r = fcm.send("tok", {}, client=make(404, {"error": {"status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}}))
    assert not r.ok and r.token_invalid


def test_send_without_config_raises(override_settings):
    fcm._credentials.cache_clear()
    override_settings(firebase_credentials_file="", firebase_project_id="")
    with pytest.raises(fcm.FcmNotConfigured):
        fcm.send("tok", {})

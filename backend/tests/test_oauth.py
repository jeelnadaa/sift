import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.mail import google_oauth as g
from app.mail.base import AuthRevoked


@pytest.fixture(autouse=True)
def oauth_settings(override_settings):
    override_settings(app_secret="s3cret", google_client_id="cid", google_client_secret="csecret", public_base_url="http://localhost:8000")


def test_state_roundtrip():
    assert g.read_state(g.make_state("me@gmail.com")) == "me@gmail.com"


def test_tampered_state_rejected():
    state = g.make_state("me@gmail.com")
    body, sig = state.rsplit(".", 1)
    forged = g.make_state("attacker@x.com").rsplit(".", 1)[0] + "." + sig
    with pytest.raises(g.OAuthError):
        g.read_state(forged)
    with pytest.raises(g.OAuthError):
        g.read_state("garbage")


def test_expired_state_rejected(monkeypatch):
    state = g.make_state("me@gmail.com")
    monkeypatch.setattr(time, "time", lambda: 10**10)
    with pytest.raises(g.OAuthError, match="expired"):
        g.read_state(state)


def test_authorization_url_requests_readonly_offline_consent():
    q = parse_qs(urlparse(g.authorization_url("me@gmail.com", login_hint="me@gmail.com")).query)
    assert q["scope"] == ["https://www.googleapis.com/auth/gmail.readonly"]
    assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"]
    assert q["redirect_uri"] == ["http://localhost:8000/api/v1/accounts/oauth/callback"]
    assert q["client_id"] == ["cid"] and q["login_hint"] == ["me@gmail.com"]
    assert g.read_state(q["state"][0]) == "me@gmail.com"


def token_client(status, body):
    seen = []

    def handler(request):
        seen.append(parse_qs(request.content.decode()))
        return httpx.Response(status, json=body)
    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def test_refresh_returns_token_and_expiry():
    client, seen = token_client(200, {"access_token": "at", "expires_in": 3599})
    assert g.refresh_access_token("rt", client) == ("at", 3599)
    assert seen[0]["grant_type"] == ["refresh_token"] and seen[0]["client_secret"] == ["csecret"]


def test_invalid_grant_means_reconnect():
    client, _ = token_client(400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
    with pytest.raises(AuthRevoked) as e:
        g.refresh_access_token("rt", client)
    assert e.value.blocked is False


@pytest.mark.parametrize("body", [
    {"error": "admin_policy_enforced"},
    {"error": "invalid_grant", "error_description": "Your administrator has blocked access"},
])
def test_admin_block_means_blocked(body):
    client, _ = token_client(400, body)
    with pytest.raises(AuthRevoked) as e:
        g.refresh_access_token("rt", client)
    assert e.value.blocked is True


def test_other_token_errors_are_not_auth_revocations():
    client, _ = token_client(401, {"error": "invalid_client"})
    with pytest.raises(g.OAuthError):
        g.exchange_code("code", client)

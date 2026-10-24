"""Google OAuth 2.0 for the web-server flow.

Scopes: every account starts read-only. Write access (gmail.modify: archive, labels, read state,
star, trash, snooze) is asked for per account the first time the user wants it, with incremental
authorization (include_granted_scopes), so accounts that are only read never get it.

Errors (Google "Using OAuth 2.0 for Web Server Applications"):
- admin_policy_enforced is shown on Google's own page; the user is not redirected,
  so we can only detect a block later, when a token refresh fails.
- access_denied comes back to the redirect URI when the user declines.
- invalid_grant on refresh means the token expired (7 days in Testing mode) or was revoked.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.mail.base import AuthRevoked

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
SCOPES = [READONLY_SCOPE]  # what a new connection asks for
CALLBACK_PATH = "/api/v1/accounts/oauth/callback"
STATE_TTL = 15 * 60
BLOCKED_ERRORS = ("admin_policy_enforced", "org_internal")


class OAuthError(Exception):
    pass


def redirect_uri() -> str:
    return get_settings().public_base_url.rstrip("/") + CALLBACK_PATH


# ---- signed state: carries the Sift user through Google and back -------------

def _sign(raw: bytes) -> str:
    secret = get_settings().app_secret
    if not secret:
        raise OAuthError("Set APP_SECRET")
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def make_state(user_email: str, extra: dict | None = None) -> str:
    raw = json.dumps({"u": user_email, "n": secrets.token_hex(8), "e": int(time.time()) + STATE_TTL, "x": extra or {}}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=") + "." + _sign(raw)


def read_state(state: str) -> str:
    return read_state_data(state)["u"]


def read_state_data(state: str) -> dict:
    """{"u": Sift user email, "x": {"intent": "write", "account": email} or {}}"""
    try:
        body, sig = state.rsplit(".", 1)
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except ValueError as exc:
        raise OAuthError("bad state") from exc
    if not hmac.compare_digest(sig, _sign(raw)):
        raise OAuthError("bad state signature")
    data = json.loads(raw)
    if data["e"] < time.time():
        raise OAuthError("state expired, start again")
    data.setdefault("x", {})
    return data


# ---- flow --------------------------------------------------------------------

def authorization_url(user_email: str, login_hint: str | None = None, write: bool = False) -> str:
    """Google's consent page. `write` adds gmail.modify for the account in `login_hint` (on top
    of what it already granted)."""
    s = get_settings()
    if not s.google_client_id:
        raise OAuthError("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET")
    params = {
        "client_id": s.google_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": " ".join(SCOPES + ([MODIFY_SCOPE] if write else [])),
        "access_type": "offline",
        "prompt": "consent",  # always returns a refresh token, also on reconnect
        "include_granted_scopes": "true",
        "state": make_state(user_email, {"intent": "write", "account": login_hint} if write else None),
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTH_URL}?{urlencode(params)}"


def _token_request(data: dict, client: httpx.Client | None) -> dict:
    s = get_settings()
    data = {**data, "client_id": s.google_client_id, "client_secret": s.google_client_secret}
    own = client is None
    client = client or httpx.Client(timeout=15)
    try:
        r = client.post(TOKEN_URL, data=data)
    finally:
        if own:
            client.close()
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code != 200:
        error = body.get("error", f"HTTP {r.status_code}")
        description = body.get("error_description", "")
        if error in BLOCKED_ERRORS or "admin" in description.lower():
            raise AuthRevoked(error, blocked=True)
        if error == "invalid_grant":
            raise AuthRevoked(error)
        raise OAuthError(error)
    return body


def exchange_code(code: str, client: httpx.Client | None = None) -> dict:
    """Returns Google's token response: access_token, refresh_token, expires_in, scope."""
    return _token_request({"code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri()}, client)


def refresh_access_token(refresh_token: str, client: httpx.Client | None = None) -> tuple[str, int]:
    """Returns (access_token, expires_in_seconds)."""
    body = _token_request({"refresh_token": refresh_token, "grant_type": "refresh_token"}, client)
    return body["access_token"], int(body.get("expires_in", 3600))

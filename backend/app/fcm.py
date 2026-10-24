"""Firebase Cloud Messaging HTTP v1 client.

We send data-only, high-priority messages; the Android app builds the
notification itself (per-priority channels, action buttons). All data values
must be strings.
"""
import logging
from dataclasses import dataclass
from functools import lru_cache

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from app.config import get_settings

log = logging.getLogger(__name__)
SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


class FcmNotConfigured(RuntimeError):
    pass


@dataclass(frozen=True)
class SendResult:
    ok: bool
    token_invalid: bool = False  # UNREGISTERED: delete the device
    retryable: bool = False  # UNAVAILABLE, INTERNAL, QUOTA_EXCEEDED
    error: str | None = None
    name: str | None = None  # FCM message name on success


def build_message(token: str, data: dict[str, object]) -> dict:
    # silent syncs go at normal priority (Android limits high-priority messages that show nothing)
    # and collapse, so a phone that was offline gets one sync, not dozens
    android = {"priority": "normal", "collapse_key": "sync"} if data.get("type") == "sync" else {"priority": "high"}
    return {
        "message": {
            "token": token,
            "data": {k: "" if v is None else str(v) for k, v in data.items()},
            "android": android,
        }
    }


@lru_cache
def _credentials() -> service_account.Credentials:
    s = get_settings()
    if not s.firebase_credentials_file or not s.firebase_project_id:
        raise FcmNotConfigured("Set FIREBASE_PROJECT_ID and FIREBASE_CREDENTIALS_FILE")
    return service_account.Credentials.from_service_account_file(s.firebase_credentials_file, scopes=[SCOPE])


def _access_token() -> str:
    creds = _credentials()
    if not creds.valid:
        creds.refresh(Request())
    return creds.token


def classify_error(status: int, body: dict) -> SendResult:
    err = body.get("error", {}) if isinstance(body, dict) else {}
    code = err.get("status", "")
    for d in err.get("details", []) or []:
        code = d.get("errorCode", code)
    return SendResult(
        ok=False,
        token_invalid=code == "UNREGISTERED" or status == 404,
        retryable=code in ("UNAVAILABLE", "INTERNAL", "QUOTA_EXCEEDED") or status in (429, 500, 503),
        error=code or f"HTTP {status}",
    )


def send(token: str, data: dict[str, object], client: httpx.Client | None = None) -> SendResult:
    url = f"https://fcm.googleapis.com/v1/projects/{get_settings().firebase_project_id}/messages:send"
    headers = {"Authorization": f"Bearer {_access_token()}"}
    own = client is None
    client = client or httpx.Client(timeout=10)
    try:
        r = client.post(url, json=build_message(token, data), headers=headers)
    finally:
        if own:
            client.close()
    if r.status_code == 200:
        return SendResult(ok=True, name=r.json().get("name"))
    try:
        body = r.json()
    except ValueError:
        body = {}
    result = classify_error(r.status_code, body)
    log.warning("fcm send failed: %s", result.error)  # never log the token or payload
    return result

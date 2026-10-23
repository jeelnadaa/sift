"""Pub/Sub push handling for Gmail notifications.

Auth (per Google's "Authenticate push subscriptions" doc): Pub/Sub sends an OIDC
JWT in `Authorization: Bearer <token>`. We verify the Google signature, `aud`
and `exp` (verify_oauth2_token does these), then check `email` equals the push
service account and `email_verified` is true.

Body: {"message": {"data": base64({"emailAddress", "historyId"}), "messageId", "publishTime"}, "subscription"}.
"""
import base64
import binascii
import json
from dataclasses import dataclass

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.config import Settings


class PushAuthError(Exception):
    pass


class PushPayloadError(Exception):
    pass


@dataclass(frozen=True)
class GmailPush:
    email: str
    history_id: int
    pubsub_message_id: str


_google_request = google_requests.Request()


def verify_push_token(authorization: str | None, settings: Settings, verifier=id_token.verify_oauth2_token) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise PushAuthError("missing bearer token")
    if not settings.pubsub_audience or not settings.pubsub_service_account:
        raise PushAuthError("PUBSUB_AUDIENCE and PUBSUB_SERVICE_ACCOUNT must be set")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = verifier(token, _google_request, audience=settings.pubsub_audience)
    except Exception as exc:  # google-auth raises ValueError and transport errors
        raise PushAuthError(f"invalid token: {type(exc).__name__}") from exc
    if claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise PushAuthError("unexpected issuer")
    if claims.get("email") != settings.pubsub_service_account or not claims.get("email_verified"):
        raise PushAuthError("unexpected service account")
    return claims


def parse_gmail_push(body: dict) -> GmailPush:
    try:
        message = body["message"]
        raw = message["data"]
        decoded = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        return GmailPush(
            email=str(decoded["emailAddress"]).strip().lower(),
            history_id=int(decoded["historyId"]),
            pubsub_message_id=str(message.get("messageId") or message.get("message_id") or ""),
        )
    except (KeyError, TypeError, ValueError, binascii.Error, json.JSONDecodeError) as exc:
        raise PushPayloadError(type(exc).__name__) from exc

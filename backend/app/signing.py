"""Short-lived signed tokens for links that a browser or WebView fetches without the sign-in
header: attachment downloads, inline (cid:) images and proxied remote images.

A token carries its own data (JSON), a purpose and an expiry, sealed with HMAC-SHA256 under
APP_SECRET. It can't be altered, reused for another purpose, or used after it expires.
"""
import base64
import hashlib
import hmac
import json
import time

from app.config import get_settings


class BadToken(ValueError):
    pass


def _key(purpose: str) -> bytes:
    secret = get_settings().app_secret
    if not secret:
        raise RuntimeError("APP_SECRET is not set")
    # one derived key per purpose, so an image token can never open an attachment
    return hmac.new(secret.encode(), b"sift-link:" + purpose.encode(), hashlib.sha256).digest()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make(purpose: str, data: dict, ttl_seconds: int, window: int | None = None) -> str:
    """`window`: round the expiry up to a multiple of it, so the same data gives the same token
    for that long (a link stays valid between ttl and ttl + window). Stable links let browser,
    WebView and service-worker caches find a mail again instead of fetching it anew."""
    expiry = int(time.time()) + ttl_seconds
    if window:
        expiry = -(-expiry // window) * window
    body = _b64(json.dumps({"d": data, "e": expiry}, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_key(purpose), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read(purpose: str, token: str) -> dict:
    try:
        body, sig = token.split(".", 1)
        expected = _b64(hmac.new(_key(purpose), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            raise BadToken("bad signature")
        payload = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError) as exc:
        raise BadToken("malformed link") from exc
    if payload.get("e", 0) < time.time():
        raise BadToken("link expired")
    return payload["d"]

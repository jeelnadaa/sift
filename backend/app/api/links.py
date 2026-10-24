"""Links a browser or WebView opens without the sign-in header, each carrying a signed,
short-lived token (app/signing.py): the remote-image proxy and attachment downloads."""
import ipaddress
from html import escape as html_escape
import logging
import socket
import uuid
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import accounts as account_service
from app import reader, signing
from app.db import get_db
from app.mail.base import AuthRevoked
from app.mail.gmail import GmailError
from app.models import GmailAccount

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 3
ALLOWED_PORTS = {None, 80, 443, 8080, 8443}
# Served from our own origin, so lock every response down: no sniffing, no scripts, no framing.
SAFE_HEADERS = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox",
                "Referrer-Policy": "no-referrer", "Cross-Origin-Resource-Policy": "same-origin"}


class Refused(Exception):
    pass


def _check_public(url: str) -> None:
    """Server-side request forgery guard: only http(s) on normal ports, to hosts whose every
    address is public (no loopback, private, link-local, reserved or multicast ranges)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise Refused("not an http(s) address")
    if parts.username or parts.password:
        raise Refused("credentials in address")
    try:
        port = parts.port
    except ValueError as exc:
        raise Refused("bad port") from exc
    if port not in ALLOWED_PORTS:
        raise Refused("port not allowed")
    try:
        infos = socket.getaddrinfo(parts.hostname, port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise Refused("unknown host") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            raise Refused("private address")


def fetch_image(url: str, client: httpx.Client | None = None) -> tuple[bytes, str]:
    own = client is None
    client = client or httpx.Client(timeout=8, follow_redirects=False, headers={"User-Agent": "Mozilla/5.0 (Sift image proxy)", "Accept": "image/*"})
    try:
        for _ in range(MAX_REDIRECTS + 1):
            _check_public(url)
            with client.stream("GET", url) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    url = urljoin(url, r.headers["location"])
                    continue
                if r.status_code != 200:
                    raise Refused(f"upstream {r.status_code}")
                ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if not ctype.startswith("image/") or ctype == "image/svg+xml":
                    raise Refused("not an image")
                if int(r.headers.get("content-length") or 0) > MAX_IMAGE_BYTES:
                    raise Refused("too large")
                buf = bytearray()
                for chunk in r.iter_bytes():
                    buf += chunk
                    if len(buf) > MAX_IMAGE_BYTES:
                        raise Refused("too large")
                return bytes(buf), ctype
        raise Refused("too many redirects")
    finally:
        if own:
            client.close()


@router.get("/img")
def image_proxy(t: str = Query(max_length=4096)) -> Response:
    """Remote image from a mail, fetched by the server so the sender sees the server, not the
    reader. Only for links Sift itself signed while rendering a mail."""
    try:
        url = signing.read("img", t)["u"]
    except signing.BadToken as exc:
        raise HTTPException(403, str(exc)) from exc
    try:
        data, ctype = fetch_image(url)
    except (Refused, httpx.HTTPError) as exc:
        # tiny transparent gif keeps the mail's layout intact
        log.info("image proxy refused: %s", type(exc).__name__ if isinstance(exc, httpx.HTTPError) else exc)
        return Response(_PIXEL, media_type="image/gif", headers={**SAFE_HEADERS, "Cache-Control": "private, max-age=300"})
    return Response(data, media_type=ctype, headers={**SAFE_HEADERS, "Cache-Control": "private, max-age=86400"})


_PIXEL = bytes.fromhex("47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b")


@router.get("/files/{token}")
def attachment(token: str, db: Session = Depends(get_db)) -> Response:
    """Attachment bytes, fetched live from Gmail. Downloads always; images may display inline."""
    try:
        d = signing.read("file", token)
    except signing.BadToken as exc:
        raise HTTPException(403, str(exc)) from exc
    account = db.get(GmailAccount, uuid.UUID(d["a"]))
    if account is None or str(account.user_id) != d["u"]:
        raise HTTPException(404, "not found")
    if account.status != "active":
        raise HTTPException(409, f"account is {account.status}")
    try:
        data = account_service.provider_for(account).get_attachment(d["m"], d["x"])
    except AuthRevoked as exc:
        account_service.mark_auth_failure(account, exc)
        db.commit()
        raise HTTPException(409, f"account is {account.status}") from exc
    except GmailError as exc:
        raise HTTPException(404 if exc.status == 404 else 502, "attachment not available") from exc
    inline = bool(d.get("i")) and d.get("t") in reader.INLINE_IMAGE_TYPES
    name = d.get("n") or "attachment"
    ascii_name = name.encode("ascii", "replace").decode().replace('"', "'").replace("?", "_")
    disposition = f"{'inline' if inline else 'attachment'}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
    media = d["t"] if inline else (d.get("t") or "application/octet-stream")
    return Response(data, media_type=media, headers={**SAFE_HEADERS, "Content-Disposition": disposition, "Cache-Control": "private, max-age=600"})


@router.get("/render/{token}")
def render(token: str, colors: str = Query("dark", pattern="^(dark|original)$"), db: Session = Depends(get_db)) -> Response:
    """One mail's sanitized HTML as its own locked-down document, for a sandboxed frame.
    `colors=original` shows the mail as sent (light); the default matches the app's dark theme."""
    try:
        d = signing.read("render", token)
    except signing.BadToken as exc:
        raise HTTPException(403, str(exc)) from exc
    account = db.get(GmailAccount, uuid.UUID(d["a"]))
    if account is None or str(account.user_id) != d["u"]:
        raise HTTPException(404, "not found")
    if account.status != "active":
        raise HTTPException(409, f"account is {account.status}")
    try:
        msg = account_service.provider_for(account).get_full(d["m"])
    except AuthRevoked as exc:
        account_service.mark_auth_failure(account, exc)
        db.commit()
        raise HTTPException(409, f"account is {account.status}") from exc
    except GmailError as exc:
        raise HTTPException(404 if exc.status == 404 else 502, "mail not available") from exc
    out = reader.render_message(msg, user_id=d["u"], account_id=d["a"], base="", images=bool(d.get("i")))
    body = reader.document(out["html"] or f'<div style="white-space:pre-wrap">{html_escape(out["text"])}</div>', colors)
    headers = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
               "Content-Security-Policy": reader.RENDER_CSP, "Cache-Control": "private, max-age=600"}
    return Response(body, media_type="text/html; charset=utf-8", headers=headers)


FONT_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts"


@router.get("/reader-fonts/{name}", include_in_schema=False)
def reader_font(name: str) -> Response:
    """The app's text font for the mail reader document (its policy allows fonts from 'self' only)."""
    if name not in reader.READER_FONTS:
        raise HTTPException(404, "not found")
    return Response((FONT_DIR / name).read_bytes(), media_type="font/woff2",
                    headers={"Cache-Control": "public, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"})

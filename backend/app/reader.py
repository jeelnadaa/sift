"""Thread reader (Phase 3a, brief sections 14 and 15).

A conversation is fetched live from Gmail and turned into something safe to show:
- HTML is sanitized here (nh3: no scripts, event handlers, forms, frames, <base>, <meta> or
  external stylesheets) and the clients show it in a sandbox as well (defence in depth).
- Remote images are blocked by default. With images on, each http(s) image becomes a link to
  our image proxy, so the sender never sees the reader's IP address or that the mail was opened
  at all from their own server logs (only the proxy fetch).
- Inline images (cid:) and attachments become signed, short-lived links to our server.
Nothing here is stored or logged.
"""
import base64
import re
from dataclasses import dataclass, field
from email.utils import getaddresses, parsedate_to_datetime

import nh3

from app import signing
from app.mail.message import html_to_text

IMAGE_TTL = 6 * 3600
FILE_TTL = 30 * 60
INLINE_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp", "image/avif"}

# Mail HTML relies on old-fashioned layout tags and attributes; allow those, nothing active.
TAGS = {
    "a", "abbr", "address", "article", "b", "bdi", "bdo", "big", "blockquote", "br", "caption", "center", "cite",
    "code", "col", "colgroup", "dd", "del", "details", "dfn", "div", "dl", "dt", "em", "figcaption", "figure",
    "font", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "i", "img", "ins", "kbd", "li", "main",
    "mark", "ol", "p", "pre", "q", "s", "samp", "section", "small", "span", "strike", "strong", "style", "sub",
    "summary", "sup", "table", "tbody", "td", "tfoot", "th", "thead", "time", "tr", "tt", "u", "ul", "var", "wbr",
}
COMMON_ATTRS = {"style", "class", "id", "dir", "lang", "title", "align", "valign", "width", "height", "bgcolor", "color"}
ATTRS = {
    "*": COMMON_ATTRS,
    "a": {"href", "name"},
    "img": {"src", "alt", "border", "hspace", "vspace"},
    "table": {"border", "cellpadding", "cellspacing", "background", "role"},
    "td": {"colspan", "rowspan", "nowrap", "background"},
    "th": {"colspan", "rowspan", "nowrap", "scope"},
    "col": {"span"}, "colgroup": {"span"},
    "font": {"face", "size"},
    "ol": {"start", "type"}, "li": {"value"},
    "time": {"datetime"},
}
URL_SCHEMES = {"http", "https", "mailto", "tel", "cid"}

_IMG_SRC = re.compile(r'(<img\b[^>]*?\bsrc=")([^"]*)(")', re.I)
_BG_ATTR = re.compile(r'(\bbackground=")(https?:[^"]*)(")', re.I)
_CSS_URL = re.compile(r"url\(\s*(['\"]?)(https?:[^)'\"]+)\1\s*\)", re.I)


@dataclass
class Attachment:
    filename: str
    mime: str
    size: int
    attachment_id: str
    content_id: str | None = None


@dataclass
class Parts:
    plain: list[str] = field(default_factory=list)
    html: list[str] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)


def _charset(part: dict) -> str:
    for h in part.get("headers") or []:
        if h.get("name", "").lower() == "content-type":
            m = re.search(r'charset="?([\w.:-]+)"?', h.get("value", ""), re.I)
            if m:
                return m.group(1)
    return "utf-8"


def _decode(part: dict) -> str:
    data = part.get("body", {}).get("data") or ""
    raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    try:
        return raw.decode(_charset(part), errors="replace")
    except LookupError:  # unknown charset name
        return raw.decode("utf-8", errors="replace")


def _header(part: dict, name: str) -> str | None:
    for h in part.get("headers") or []:
        if h.get("name", "").lower() == name:
            return h.get("value")
    return None


def walk(payload: dict) -> Parts:
    out = Parts()

    def visit(part: dict, in_alternative: bool):
        mime = (part.get("mimeType") or "").lower()
        body = part.get("body") or {}
        if body.get("attachmentId") and (part.get("filename") or not mime.startswith("text/")):
            cid = (_header(part, "content-id") or "").strip("<> ") or None
            out.attachments.append(Attachment(part.get("filename") or "attachment", mime or "application/octet-stream",
                                              int(body.get("size") or 0), body["attachmentId"], cid))
            return
        if mime == "text/plain" and body.get("data"):
            out.plain.append(_decode(part))
        elif mime == "text/html" and body.get("data"):
            out.html.append(_decode(part))
        for child in part.get("parts") or []:
            visit(child, in_alternative or mime == "multipart/alternative")

    visit(payload, False)
    return out


def sanitize(raw_html: str) -> str:
    return nh3.clean(
        raw_html, tags=TAGS, clean_content_tags={"script", "noscript", "iframe", "object", "embed", "template", "title", "head"},
        attributes=ATTRS, url_schemes=URL_SCHEMES, link_rel="noopener noreferrer nofollow",
        set_tag_attribute_values={"a": {"target": "_blank"}}, strip_comments=True,
    )


def image_proxy_url(base: str, url: str) -> str:
    return f"{base}/api/v1/img?t={signing.make('img', {'u': url}, IMAGE_TTL)}"


def file_url(base: str, user_id: str, account_id: str, gmail_id: str, a: Attachment, inline: bool) -> str:
    token = signing.make("file", {"u": user_id, "a": account_id, "m": gmail_id, "x": a.attachment_id,
                                  "n": a.filename[:200], "t": a.mime, "i": inline}, FILE_TTL)
    return f"{base}/api/v1/files/{token}"


def rewrite_images(html: str, images: bool, base: str, cid_urls: dict[str, str]) -> tuple[str, int]:
    """cid: images -> signed links; remote images -> proxy links when `images`, else blocked.
    Returns (html, number of remote images blocked)."""
    blocked = 0

    def src(m: re.Match) -> str:
        nonlocal blocked
        url = m.group(2)
        if url.lower().startswith("cid:"):
            return m.group(1) + cid_urls.get(url[4:].strip("<>"), "") + m.group(3)
        if url.lower().startswith(("http:", "https:")):
            if images:
                return m.group(1) + image_proxy_url(base, url) + m.group(3)
            blocked += 1
            return m.group(1) + m.group(3) + ' data-blocked="1"'
        return m.group(1) + m.group(3)

    html = _IMG_SRC.sub(src, html)
    # background images in attributes and CSS: proxied too, or dropped
    html = _BG_ATTR.sub(lambda m: (m.group(1) + image_proxy_url(base, m.group(2)) + m.group(3)) if images else "", html)
    html = _CSS_URL.sub(lambda m: f"url('{image_proxy_url(base, m.group(2))}')" if images else "none", html)
    return html, blocked


def _addresses(value: str | None) -> list[dict]:
    return [{"name": n, "email": e.lower()} for n, e in getaddresses([value or ""]) if e]


def render_url(base: str, user_id: str, account_id: str, gmail_id: str, images: bool) -> str:
    token = signing.make("render", {"u": user_id, "a": account_id, "m": gmail_id, "i": images}, IMAGE_TTL)
    return f"{base}/api/v1/render/{token}"


# The mail's own document, shown in a sandboxed frame. Its policy allows the mail's inline styles
# and images from our own server only (proxy and cid links); nothing can run.
RENDER_CSP = ("default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; font-src data:; "
              "base-uri 'none'; form-action 'none'; frame-ancestors 'self'")


def document(html: str) -> str:
    return ("<!doctype html><html><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<base target=\"_blank\">"
            "<style>html,body{margin:0;background:#fff;color:#1a1a1a;font:15px/1.5 -apple-system,'Segoe UI',Roboto,Arial,sans-serif;"
            "overflow-wrap:anywhere}body{padding:16px}img{max-width:100%;height:auto}table{max-width:100%}"
            "img[data-blocked]{display:inline-block;min-width:16px;min-height:16px;background:#eee}</style></head>"
            f"<body>{html}</body></html>")


def render_message(msg: dict, *, user_id: str, account_id: str, base: str, images: bool) -> dict:
    payload = msg.get("payload") or {}
    parts = walk(payload)
    cid_urls = {a.content_id: file_url(base, user_id, account_id, msg["id"], a, True)
                for a in parts.attachments if a.content_id and a.mime in INLINE_IMAGE_TYPES}
    html, blocked = (None, 0)
    if parts.html:
        html, blocked = rewrite_images(sanitize("\n".join(parts.html)), images, base, cid_urls)
    text = "\n".join(parts.plain) if parts.plain else (html_to_text("\n".join(parts.html)) if parts.html else msg.get("snippet", ""))
    inline_ids = set(cid_urls) if html else set()
    date = _header(payload, "date")
    try:
        when = parsedate_to_datetime(date).isoformat() if date else None
    except (TypeError, ValueError):
        when = None
    sender = _addresses(_header(payload, "from"))
    return {
        "gmail_id": msg["id"], "labels": msg.get("labelIds") or [], "snippet": msg.get("snippet", ""),
        "from": sender[0] if sender else None, "to": _addresses(_header(payload, "to")), "cc": _addresses(_header(payload, "cc")),
        "subject": _header(payload, "subject") or "", "date": when,
        "unread": "UNREAD" in (msg.get("labelIds") or []),
        "text": text.strip()[:200_000], "html": html, "images_blocked": blocked,
        "html_url": render_url(base, user_id, account_id, msg["id"], images) if html else None,
        "attachments": [
            {"filename": a.filename, "mime": a.mime, "size": a.size,
             "url": file_url(base, user_id, account_id, msg["id"], a, False),
             "view_url": file_url(base, user_id, account_id, msg["id"], a, True) if a.mime in INLINE_IMAGE_TYPES else None}
            for a in parts.attachments if a.content_id not in inline_ids
        ],
    }


def render_thread(thread: dict, *, user_id: str, account_id: str, base: str, images: bool) -> list[dict]:
    """Messages oldest first; drafts are left out (Phase 4)."""
    msgs = [m for m in thread.get("messages") or [] if "DRAFT" not in (m.get("labelIds") or [])]
    msgs.sort(key=lambda m: int(m.get("internalDate") or 0))
    return [render_message(m, user_id=user_id, account_id=account_id, base=base, images=images) for m in msgs]

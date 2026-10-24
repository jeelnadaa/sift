"""Parsing Gmail API messages into what the pipeline needs.

Nothing here logs content. Bodies are only held in memory for one pipeline run.
"""
import base64
import html
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import getaddresses, parseaddr
from html.parser import HTMLParser

METADATA_HEADERS = [
    "From", "To", "Cc", "Subject", "Date", "Message-ID", "List-Id", "List-Unsubscribe",
    "Precedence", "Auto-Submitted", "Authentication-Results", "Content-Type",
]
BODY_LIMIT = 1500


@dataclass
class MailMeta:
    gmail_id: str
    thread_id: str
    labels: list[str]
    snippet: str
    received_at: datetime | None
    headers: dict[str, str]  # lowercase name -> value (first occurrence)
    sender: str  # address, lowercase
    sender_name: str
    sender_domain: str
    authenticated_domain: str | None  # sender_domain only when DKIM/SPF/DMARC passed for it
    subject: str
    message_id: str | None
    list_id: str | None
    has_attachment: bool
    recipients: list[str] = field(default_factory=list)

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())


def _domain(address: str) -> str:
    return address.rsplit("@", 1)[-1].lower() if "@" in address else ""


def _aligned(a: str, b: str) -> bool:
    """Relaxed alignment: same domain, or one is a subdomain of the other."""
    a, b = a.lower().strip("."), b.lower().strip(".")
    return bool(a and b) and (a == b or a.endswith("." + b) or b.endswith("." + a))


def authenticated_domain(auth_results: list[str], from_domain: str) -> str | None:
    """Trust only the Authentication-Results header Gmail itself added (authserv-id mx.google.com).
    Returns the From domain when DMARC passed, or DKIM/SPF passed for an aligned domain."""
    if not from_domain:
        return None
    for value in auth_results:
        if not value.strip().lower().startswith("mx.google.com"):
            continue  # added by an earlier hop; could be forged
        v = value.lower()
        if re.search(r"\bdmarc=pass\b[^;]*header\.from=([^\s;]+)", v) and any(
            _aligned(d, from_domain) for d in re.findall(r"\bdmarc=pass\b[^;]*header\.from=([^\s;]+)", v)
        ):
            return from_domain
        for d in re.findall(r"\bdkim=pass\b[^;]*header\.(?:i=@?|d=)([^\s;]+)", v):
            if _aligned(_domain("x@" + d.lstrip("@")), from_domain):
                return from_domain
        for d in re.findall(r"\bspf=pass\b[^;]*smtp\.mailfrom=([^\s;]+)", v):
            if _aligned(_domain(d) or d, from_domain):
                return from_domain
        return None
    return None


def parse_metadata(msg: dict) -> MailMeta:
    payload = msg.get("payload", {})
    headers: dict[str, str] = {}
    auth_results: list[str] = []
    for h in payload.get("headers", []):
        name = h.get("name", "").lower()
        if name == "authentication-results":
            auth_results.append(h.get("value", ""))
        headers.setdefault(name, h.get("value", ""))
    name, address = parseaddr(headers.get("from", ""))
    address = address.lower()
    domain = _domain(address)
    content_type = (headers.get("content-type") or payload.get("mimeType") or "").lower()
    internal = msg.get("internalDate")
    return MailMeta(
        gmail_id=msg["id"],
        thread_id=msg.get("threadId", msg["id"]),
        labels=list(msg.get("labelIds", [])),
        snippet=html.unescape(msg.get("snippet", "")),
        received_at=datetime.fromtimestamp(int(internal) / 1000, UTC) if internal else None,
        headers=headers,
        sender=address,
        sender_name=name.strip(),
        sender_domain=domain,
        authenticated_domain=authenticated_domain(auth_results, domain),
        subject=headers.get("subject", "").strip(),
        message_id=(headers.get("message-id") or "").strip() or None,
        list_id=(headers.get("list-id") or "").strip() or None,
        has_attachment="multipart/mixed" in content_type,
        recipients=[a.lower() for _, a in getaddresses([headers.get("to", ""), headers.get("cc", "")]) if a],
    )


# ---- body ----------------------------------------------------------------------

class _Text(HTMLParser):
    SKIP = {"script", "style", "head", "title"}
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table", "section"}

    def __init__(self):
        super().__init__()
        self.out: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")
        if tag == "a":
            href = dict(attrs).get("href")
            if href and href.startswith("http"):
                self.out.append(f" <{href}> ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.out.append(data)


def html_to_text(raw: str) -> str:
    p = _Text()
    p.feed(raw)
    return "".join(p.out)


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def extract_body(payload: dict) -> tuple[str, list[str]]:
    """Returns (plain text, attachment filenames). Prefers text/plain over text/html."""
    plain: list[str] = []
    rich: list[str] = []
    files: list[str] = []

    def walk(part: dict):
        mime = part.get("mimeType", "")
        if part.get("filename"):
            files.append(part["filename"])
            return
        data = part.get("body", {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            rich.append(html_to_text(_decode(data)))
        for child in part.get("parts", []) or []:
            walk(child)

    walk(payload)
    return ("\n".join(plain) if plain else "\n".join(rich)), files


_QUOTE_START = re.compile(r"^(on .{5,200} wrote:|-----\s*original message\s*-----|from:\s.+@.+)$", re.I)


def clean_body(text: str, limit: int = BODY_LIMIT) -> str:
    """Drop quoted replies and signatures, collapse whitespace, truncate."""
    lines = []
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if stripped == "--" or stripped == "-- " or _QUOTE_START.match(stripped):
            break
        if stripped.startswith(">"):
            continue
        lines.append(stripped)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    text = re.sub(r"[ \t ]{2,}", " ", text).strip()
    return text[:limit]

"""Writing mail (Phase 4): building and reading RFC 822 messages, and filling in replies and
forwards.

The mail being written lives only in a Gmail draft (seen and editable in Gmail too). Sift builds
the message here, uploads it as the draft, and reads it back from Gmail when the composer opens
it again or an attachment is added; nothing of the text or attachments is stored by Sift.

Messages are sent as text/plain with a text/html alternative made from the same text (escaped,
links made clickable, "> " quotes as blockquotes), so replies look right in every mail client.
Headers are built with the standard library's strict SMTP policy, which refuses line breaks in
header values (no header injection from a subject or a name).
"""
import html
import mimetypes
import re
from dataclasses import dataclass, field
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses, make_msgid, parsedate_to_datetime

from app import reader
from app.mail.message import html_to_text

MAX_TOTAL_BYTES = 25 * 1024 * 1024  # Gmail's limit for a sent message's attachments
MAX_RECIPIENTS = 100
MAX_BODY_CHARS = 200_000
MAX_SUBJECT_CHARS = 998
QUOTE_CHARS = 20_000
_EMAIL = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")
_URL = re.compile(r"\bhttps?://[^\s<>\"']+[^\s<>\"'.,;:!?)\]]", re.I)


class ComposeError(ValueError):
    pass


@dataclass
class Attachment:
    filename: str
    mime: str
    data: bytes


@dataclass
class Draft:
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    subject: str = ""
    body: str = ""
    in_reply_to: str | None = None
    references: str | None = None
    attachments: list[Attachment] = field(default_factory=list)


def addresses(values: list[str] | str | None) -> list[str]:
    """Parses "Name <a@x.com>, b@y.com" (or a list of them) into checked, formatted addresses."""
    if not values:
        return []
    raw = [values] if isinstance(values, str) else list(values)
    out: list[str] = []
    seen: set[str] = set()
    for name, addr in getaddresses([v.replace("\r", " ").replace("\n", " ") for v in raw]):
        addr = addr.strip()
        if not addr and not name.strip():
            continue
        if not _EMAIL.match(addr):
            raise ComposeError(f"Not an email address: {(addr or name).strip()[:80]}")
        if addr.lower() in seen:
            continue
        seen.add(addr.lower())
        out.append(formataddr((name.strip(), addr)) if name.strip() else addr)
    return out


def bare(address: str) -> str:
    return (getaddresses([address])[0][1] or address).lower()


def text_to_html(text: str) -> str:
    """Plain text -> safe HTML: escaped, links clickable, "> " lines as blockquotes."""
    out: list[str] = []
    depth = 0
    for line in text.split("\n"):
        level = len(re.match(r"^(>\s?)*", line).group(0).replace(" ", ""))
        line = re.sub(r"^(>\s?)+", "", line)
        while depth < level:
            out.append('<blockquote style="margin:0 0 0 .8ex;border-left:1px solid #ccc;padding-left:1ex">')
            depth += 1
        while depth > level:
            out.append("</blockquote>")
            depth -= 1
        escaped = html.escape(line)
        escaped = _URL.sub(lambda m: f'<a href="{m.group(0)}">{m.group(0)}</a>', escaped)
        out.append(escaped + "<br>")
    out.extend("</blockquote>" for _ in range(depth))
    return '<div dir="auto">' + "\n".join(out) + "</div>"


def _check(d: Draft) -> None:
    if len(d.to) + len(d.cc) + len(d.bcc) > MAX_RECIPIENTS:
        raise ComposeError(f"At most {MAX_RECIPIENTS} recipients")
    if len(d.subject) > MAX_SUBJECT_CHARS:
        raise ComposeError("Subject is too long")
    if len(d.body) > MAX_BODY_CHARS:
        raise ComposeError("Message is too long")
    if sum(len(a.data) for a in d.attachments) > MAX_TOTAL_BYTES:
        raise ComposeError("Attachments add up to more than 25 MB, Gmail's limit")


def build(from_email: str, from_name: str, d: Draft) -> bytes:
    _check(d)
    msg = EmailMessage(policy=policy.SMTP)
    try:
        msg["From"] = formataddr((from_name.strip(), from_email)) if from_name.strip() else from_email
        if d.to:
            msg["To"] = ", ".join(d.to)
        if d.cc:
            msg["Cc"] = ", ".join(d.cc)
        if d.bcc:
            msg["Bcc"] = ", ".join(d.bcc)  # Gmail removes Bcc from what recipients get
        msg["Subject"] = " ".join(d.subject.split())
        msg["Date"] = formatdate(localtime=False)
        msg["Message-ID"] = make_msgid(domain=from_email.rsplit("@", 1)[-1])
        if d.in_reply_to:
            msg["In-Reply-To"] = " ".join(d.in_reply_to.split())[:998]
        if d.references:
            msg["References"] = " ".join(d.references.split())[-4000:]
    except ValueError as exc:  # a header value with a line break, or similar
        raise ComposeError("Invalid characters in a header") from exc
    body = d.body.replace("\r\n", "\n")
    msg.set_content(body, subtype="plain", charset="utf-8")
    msg.add_alternative(text_to_html(body), subtype="html", charset="utf-8")
    for a in d.attachments:
        maintype, _, subtype = (a.mime if "/" in a.mime else "application/octet-stream").partition("/")
        msg.add_attachment(a.data, maintype=maintype, subtype=subtype, filename=safe_filename(a.filename))
    return msg.as_bytes()


def safe_filename(name: str) -> str:
    name = re.sub(r"[\x00-\x1f\x7f/\\]", "_", name or "").strip(" .")
    return (name or "attachment")[:200]


def guess_mime(filename: str, given: str | None) -> str:
    if given and re.match(r"^[\w.+-]+/[\w.+-]+$", given) and given != "application/octet-stream":
        return given.lower()
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def parse(raw: bytes) -> Draft:
    """A draft's message back into fields (for the composer and for rebuilding)."""
    m = message_from_bytes(raw, policy=policy.default)
    d = Draft(
        to=[formataddr(a) for a in getaddresses(m.get_all("To", []))],
        cc=[formataddr(a) for a in getaddresses(m.get_all("Cc", []))],
        bcc=[formataddr(a) for a in getaddresses(m.get_all("Bcc", []))],
        subject=str(m.get("Subject", "")), in_reply_to=m.get("In-Reply-To"), references=m.get("References"),
    )
    part = m.get_body(preferencelist=("plain", "html"))
    if part is not None:
        content = part.get_content()
        d.body = content if part.get_content_type() == "text/plain" else html_to_text(content)
    d.body = d.body.replace("\r\n", "\n").rstrip("\n")
    for a in m.iter_attachments():
        data = a.get_payload(decode=True) or b""
        d.attachments.append(Attachment(a.get_filename() or "attachment", a.get_content_type(), data))
    return d


# ---- replies and forwards ----------------------------------------------------------------------

def _header(msg: dict, name: str) -> str | None:
    for h in (msg.get("payload") or {}).get("headers") or []:
        if h.get("name", "").lower() == name:
            return h.get("value")
    return None


def _prefixed(subject: str, prefix: str) -> str:
    s = subject.strip()
    if re.match(rf"^{prefix}:", s, re.I):
        return s
    return f"{prefix}: {s}" if s else f"{prefix}:"


def _when(date: str | None) -> str:
    try:
        return parsedate_to_datetime(date).strftime("%a, %d %b %Y at %H:%M") if date else ""
    except (TypeError, ValueError):
        return date or ""


def _plain(msg: dict) -> str:
    parts = reader.walk(msg.get("payload") or {})
    if parts.plain:
        return "\n".join(parts.plain)
    if parts.html:
        return html_to_text("\n".join(parts.html))
    return msg.get("snippet", "")


def context(msg: dict, mode: str, me: str) -> dict:
    """Fields for a reply ("reply", "reply_all") or "forward" of a Gmail message (format=full).
    `me` is the account's address, left out of reply-all recipients."""
    me = me.lower()
    sender = _header(msg, "from") or ""
    reply_to = _header(msg, "reply-to")
    to = addresses_loose(_header(msg, "to"))
    cc = addresses_loose(_header(msg, "cc"))
    subject = _header(msg, "subject") or ""
    msgid = (_header(msg, "message-id") or "").strip() or None
    refs = " ".join(filter(None, [(_header(msg, "references") or "").strip(), msgid])) or None
    text = _plain(msg).replace("\r\n", "\n").strip()
    date = _when(_header(msg, "date"))
    out = {"to": [], "cc": [], "subject": "", "body": "", "in_reply_to": None, "references": None,
           "thread_id": msg.get("threadId"), "forward_gmail_id": None}
    if mode == "forward":
        head = ["---------- Forwarded message ---------", f"From: {sender}", f"Date: {date}", f"Subject: {subject}"]
        if to:
            head.append("To: " + ", ".join(to))
        if cc:
            head.append("Cc: " + ", ".join(cc))
        out.update(subject=_prefixed(subject, "Fwd"), body="\n\n" + "\n".join(head) + "\n\n" + text[:QUOTE_CHARS],
                   thread_id=None, forward_gmail_id=msg.get("id"))
        return out
    from_me = bare(sender) == me
    primary = addresses_loose(reply_to) or addresses_loose(sender)
    if from_me:  # replying to my own message: write to the people I wrote to
        primary = to or primary
    recipients_to = [a for a in primary if bare(a) != me] or primary
    recipients_cc: list[str] = []
    if mode == "reply_all":
        taken = {bare(a) for a in recipients_to} | {me}
        for a in (to if not from_me else []) + cc:
            if bare(a) not in taken:
                recipients_cc.append(a)
                taken.add(bare(a))
    quoted = "\n".join("> " + line if line else ">" for line in text[:QUOTE_CHARS].split("\n"))
    name = getaddresses([sender])[0][0] or bare(sender)
    out.update(to=recipients_to, cc=recipients_cc, subject=_prefixed(subject, "Re"),
               body=f"\n\nOn {date}, {name} <{bare(sender)}> wrote:\n{quoted}" if text else "",
               in_reply_to=msgid, references=refs)
    return out


def addresses_loose(value: str | None) -> list[str]:
    """Addresses from a received header, skipping anything malformed instead of failing."""
    out = []
    for name, addr in getaddresses([value or ""]):
        if _EMAIL.match(addr or ""):
            out.append(formataddr((name, addr)) if name else addr)
    return out


def forward_attachments(provider, msg: dict) -> list[Attachment]:
    """The original's attachments (fetched live) to carry into a forward."""
    out = []
    for a in reader.walk(msg.get("payload") or {}).attachments:
        if a.content_id and a.mime in reader.INLINE_IMAGE_TYPES:
            continue  # inline pictures of the original's HTML; the forward is plain text
        out.append(Attachment(a.filename, a.mime, provider.get_attachment(msg["id"], a.attachment_id)))
    if sum(len(a.data) for a in out) > MAX_TOTAL_BYTES:
        raise ComposeError("The original's attachments are over 25 MB; forward without them")
    return out

"""Deciding a Gmail-syntax query on one stored message, without asking Gmail.

Used when Gmail can't answer well: a mail that just arrived (Gmail's index lags), and searches
that also carry Sift filters (their matches are always mail Sift stored, so checking them
here is exact and fast). Anything this can't decide raises Unknown and the caller asks Gmail.
"""
import re
from datetime import UTC, datetime, timedelta

from app.models import Message
from app.search.query import tokenize

CATEGORY_LABELS = {"primary": "CATEGORY_PERSONAL", "social": "CATEGORY_SOCIAL", "promotions": "CATEGORY_PROMOTIONS",
                   "updates": "CATEGORY_UPDATES", "forums": "CATEGORY_FORUMS"}
_SPAN = re.compile(r"^(\d+)([dmy])$")


class Unknown(Exception):
    """The query uses something only Gmail can decide."""


def _span(value: str) -> timedelta:
    m = _SPAN.match(value)
    if not m:
        raise Unknown(value)
    n, unit = int(m.group(1)), m.group(2)
    return timedelta(days=n * {"d": 1, "m": 30, "y": 365}[unit])


def _date(value: str) -> datetime:
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    if value.isdigit():  # Gmail also takes seconds since the epoch
        return datetime.fromtimestamp(int(value), UTC)
    raise Unknown(value)


def _terms(gmail: str) -> list[list[str]]:
    """Gmail's own reading: terms are ANDed, and OR joins the terms on either side of it
    ("from:a from:b OR from:c" = from:a AND (from:b OR from:c)). Parentheses are left to Gmail."""
    out: list[list[str]] = []
    join = False
    for tok in tokenize(gmail):
        if tok.upper() == "OR":
            if not out or join:
                raise Unknown(tok)
            join = True
            continue
        if join:
            out[-1].append(tok)
            join = False
        else:
            out.append([tok])
    if join:
        raise Unknown("OR")
    return out


def gmail_match(gmail: str, m: Message, now: datetime | None = None) -> bool:
    return all(any(_term(tok, m, now or datetime.now(UTC)) for tok in alternatives) for alternatives in _terms(gmail))


def _term(tok: str, m: Message, now: datetime) -> bool:
    when = m.received_at or m.created_at
    hay = " ".join(x for x in (m.subject, m.snippet, m.sender, m.sender_name) if x).lower()
    labels = [x.upper() for x in (m.labels or [])]
    neg = tok.startswith("-")
    body = tok[1:] if neg else tok
    if body.upper() in ("AROUND", "AND") or body.startswith(("(", "{")):
        raise Unknown(tok)
    key, sep, value = body.partition(":")
    key, value = key.lower(), value.strip('"').lower()
    if not sep:
        ok = body.strip('"').lower() in hay
    elif key == "from":
        ok = value in (m.sender or "").lower() or value in (m.sender_name or "").lower()
    elif key == "subject":
        ok = value in (m.subject or "").lower()
    elif key == "has" and value == "attachment":
        ok = bool(m.has_attachment)
    elif key == "category" and value in CATEGORY_LABELS:
        ok = CATEGORY_LABELS[value] in labels
    elif key in ("label", "in") and value in ("inbox", "unread", "starred", "important"):
        ok = value.upper() in labels
    elif key == "is" and value in ("unread", "read", "starred", "important"):
        ok = ("UNREAD" not in labels) if value == "read" else value.upper() in labels
    elif key in ("newer_than", "older_than"):
        if when is None:
            return False
        ok = (when >= now - _span(value)) if key == "newer_than" else (when < now - _span(value))
    elif key in ("after", "newer", "before", "older"):
        if when is None:
            return False
        ok = when >= _date(value) if key in ("after", "newer") else when < _date(value)
    else:
        raise Unknown(tok)
    return ok != neg

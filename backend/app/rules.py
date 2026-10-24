"""Rule engine v1 (brief section 8). Pure functions over a MailContext, no I/O except the
lazy body loader, so everything that decides what is ignored or notified is unit-testable.

Condition tree (JSON):
  {"all": [c, ...]}  {"any": [c, ...]}  {"not": c}
  {"field": "sender",         "op": "is"|"in"|"contains", "value": ...}  # authenticated senders only
  {"field": "sender_domain",  "op": "is"|"in", "value": ...}             # authenticated domain, subdomains match
  {"field": "subject",        "op": "contains"|"contains_any"|"matches", "value": ...}
  {"field": "body",           "op": "contains_any", "value": [...]}      # fetches the body
  {"field": "label",          "op": "has", "value": "CATEGORY_UPDATES"}
  {"field": "header",         "op": "present", "value": "List-Unsubscribe"}
  {"field": "has_attachment", "op": "is", "value": true}
  {"field": "time",           "op": "between", "value": ["22:00", "07:00"]}  # user's local time
  {"field": "account",        "op": "in", "value": ["<account id>", ...]}
  {"field": "amount",         "op": "gt"|"gte"|"lt"|"lte", "value": 2000}  # first ₹ amount in subject, else snippet

Action (JSON): {"type": "ignore"|"silent"|"digest"|"notify_normal"|"notify_urgent"|"llm",
                "category"?: str, "folder_id"?: str, "tag"?: str, "mark_read"?: bool, "star"?: bool}
"""
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, time
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

ACTION_TYPES = ("ignore", "silent", "digest", "notify_normal", "notify_urgent", "llm")
FIELDS = ("sender", "sender_domain", "subject", "body", "label", "header", "has_attachment", "time", "account", "amount")
AMOUNT_OPS = ("gt", "gte", "lt", "lte")
# Security mail must never be quieted by a broad rule: quieting rules made by Sift (first scan,
# plain English) always carry an exception for these subject words.
SECURITY_WORDS = ["fraud", "scam", "blocked", "suspicious", "unauthori", "security alert", "password",
                  "verification code", "otp", "login attempt", "sign-in"]
SECURITY_LEAF = {"field": "subject", "op": "contains_any", "value": SECURITY_WORDS}


def has_security_exception(exceptions: dict | None) -> bool:
    """True when some single-condition exception already covers fraud and suspicious activity."""
    for item in (exceptions or {}).get("any", []) if isinstance(exceptions, dict) else []:
        if item.get("field") == "subject" and item.get("op") == "contains_any":
            words = " ".join(str(v).lower() for v in (item.get("value") or []))
            if "fraud" in words and ("suspicious" in words or "scam" in words):
                return True
    return False
MAX_REGEX = 300
# ₹ 1,180.50 / Rs. 240 / INR 5000 / 2,000 rupees
_AMOUNT = re.compile(
    r"(?:₹|\brs\.?|\binr)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)|([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:rupees|rs\b|inr\b)", re.I)


def find_amount(*texts: str) -> float | None:
    """First rupee amount in the first text that has one (subject before snippet)."""
    for text in texts:
        m = _AMOUNT.search(text or "")
        if m:
            try:
                return float((m.group(1) or m.group(2)).replace(",", ""))
            except ValueError:
                continue
    return None


class RuleError(ValueError):
    pass


@dataclass
class MailContext:
    account_id: str
    sender: str
    authenticated_domain: str | None
    subject: str
    labels: list[str]
    headers: dict[str, str]  # lowercase names
    has_attachment: bool
    received_at: datetime
    timezone: str = "Asia/Kolkata"
    snippet: str = ""  # Gmail's short preview text (stored), used for amounts
    body_loader: Callable[[], str] | None = None
    _body: str | None = field(default=None, repr=False)

    @property
    def authenticated(self) -> bool:
        return bool(self.authenticated_domain)

    def body(self) -> str:
        if self._body is None:
            self._body = (self.body_loader() if self.body_loader else "") or ""
        return self._body


@dataclass(frozen=True)
class RuleView:
    """What the engine needs from a Rule row (keeps it independent of the ORM)."""
    id: Any
    position: int
    enabled: bool
    conditions: dict
    action: dict
    exceptions: dict | None = None
    account_scope: list | None = None


@dataclass(frozen=True)
class Match:
    rule_id: Any
    action: dict


# ---- validation ------------------------------------------------------------------

def validate_condition(c: Any, depth: int = 0) -> None:
    if depth > 8 or not isinstance(c, dict):
        raise RuleError("condition must be an object (max depth 8)")
    if "all" in c or "any" in c:
        items = c.get("all", c.get("any"))
        if not isinstance(items, list) or not items:
            raise RuleError("all/any needs a non-empty list")
        for item in items:
            validate_condition(item, depth + 1)
        return
    if "not" in c:
        validate_condition(c["not"], depth + 1)
        return
    if c.get("field") not in FIELDS:
        raise RuleError(f"unknown field {c.get('field')!r}")
    if c["field"] in ("subject",) and c.get("op") == "matches":
        pattern = c.get("value")
        if not isinstance(pattern, str) or len(pattern) > MAX_REGEX:
            raise RuleError("regex must be a string up to 300 characters")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise RuleError(f"invalid regex: {exc}") from exc
    if c["field"] == "time":
        v = c.get("value")
        if not (isinstance(v, list) and len(v) == 2 and all(re.fullmatch(r"\d{2}:\d{2}", x or "") for x in v)):
            raise RuleError('time needs ["HH:MM", "HH:MM"]')
    if c["field"] == "amount":
        if c.get("op") not in AMOUNT_OPS:
            raise RuleError(f"amount op must be one of {', '.join(AMOUNT_OPS)}")
        v = c.get("value")
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
            raise RuleError("amount needs a number of rupees")


def validate_action(a: Any) -> None:
    if not isinstance(a, dict) or a.get("type") not in ACTION_TYPES:
        raise RuleError(f"action.type must be one of {', '.join(ACTION_TYPES)}")


# ---- evaluation ---------------------------------------------------------------------

def _as_list(v) -> list:
    return v if isinstance(v, list) else [v]


def _domain_match(domain: str, wanted: str) -> bool:
    wanted = wanted.lower().lstrip("@").strip(".")
    return domain == wanted or domain.endswith("." + wanted)


@lru_cache(maxsize=512)
def _regex(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.I)


def _local_time(ctx: MailContext) -> time:
    return ctx.received_at.astimezone(ZoneInfo(ctx.timezone)).time()


def _leaf(c: dict, ctx: MailContext) -> bool:
    f, op, v = c["field"], c.get("op"), c.get("value")
    if f == "sender":
        if not ctx.authenticated:
            return False  # spoofed or unauthenticated senders never match sender rules
        values = [str(x).lower() for x in _as_list(v)]
        if op == "contains":
            return any(x in ctx.sender for x in values)
        return ctx.sender in values
    if f == "sender_domain":
        return ctx.authenticated and any(_domain_match(ctx.authenticated_domain, str(x)) for x in _as_list(v))
    if f == "subject":
        subject = ctx.subject.lower()
        if op == "matches":
            return bool(_regex(v).search(ctx.subject))
        return any(str(x).lower() in subject for x in _as_list(v))
    if f == "body":
        body = ctx.body().lower()
        return any(str(x).lower() in body for x in _as_list(v))
    if f == "label":
        return any(x in ctx.labels for x in _as_list(v))
    if f == "header":
        return any(str(x).lower() in ctx.headers for x in _as_list(v))
    if f == "has_attachment":
        return ctx.has_attachment == bool(v)
    if f == "time":
        start, end = (time.fromisoformat(x) for x in v)
        now = _local_time(ctx)
        return start <= now < end if start <= end else (now >= start or now < end)  # overnight windows
    if f == "account":
        return ctx.account_id in [str(x) for x in _as_list(v)]
    if f == "amount":
        amount = find_amount(ctx.subject, ctx.snippet)
        if amount is None:
            return False  # no amount found: never "above" or "below" anything
        return {"gt": amount > v, "gte": amount >= v, "lt": amount < v, "lte": amount <= v}[op]
    return False


def matches(c: dict, ctx: MailContext) -> bool:
    if "all" in c:
        return all(matches(x, ctx) for x in c["all"])
    if "any" in c:
        return any(matches(x, ctx) for x in c["any"])
    if "not" in c:
        return not matches(c["not"], ctx)
    return _leaf(c, ctx)


def needs_body(c: dict | None) -> bool:
    if not c:
        return False
    if "all" in c or "any" in c:
        return any(needs_body(x) for x in c.get("all", c.get("any", [])))
    if "not" in c:
        return needs_body(c["not"])
    return c.get("field") == "body"


def evaluate(rules: list[RuleView], ctx: MailContext) -> Match | None:
    """Ordered, first match wins. A rule matches when it is enabled, in scope for this account,
    its conditions match and its exceptions do not."""
    for rule in sorted(rules, key=lambda r: r.position):
        if not rule.enabled:
            continue
        if rule.account_scope and ctx.account_id not in [str(x) for x in rule.account_scope]:
            continue
        if not matches(rule.conditions, ctx):
            continue
        if rule.exceptions and matches(rule.exceptions, ctx):
            continue
        return Match(rule.id, rule.action)
    return None

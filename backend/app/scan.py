"""Onboarding scan (brief section 8): the last 30 days of a new account, headers only.
No bodies are fetched, nothing is stored per mail, and the LLM is never used: the result is a
list of top senders with counts and a suggested action, which the user assigns in bulk.

Quota: messages.get(metadata) costs 20 units and Gmail allows 6,000 per user per minute, so the
scan paces itself at ~200 mails a minute (leaving room for live mail) and backs off on 429.
"""
import logging
import time
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import heuristics
from app.accounts import mark_auth_failure, provider_for
from app.db import get_sessionmaker
from app.mail.base import AuthRevoked
from app.mail.gmail import GmailError
from app.mail.message import parse_metadata
from app.models import GmailAccount, OnboardingScan
from app.opportunities import GENERIC_DOMAINS
from app.rule_tools import save_rule

log = logging.getLogger(__name__)
QUERY = "newer_than:30d -in:sent -in:drafts -in:chats"
MAX_MAILS = 1500
TOP_SENDERS = 100
PER_MINUTE = 200
ACTIONS = ("silent", "digest", "notify_normal", "notify_urgent", "keep")
SECURITY_WORDS = ["fraud", "blocked", "suspicious", "unauthori", "security alert", "password", "verification code", "otp", "login attempt", "sign-in"]
SECURITY_EXCEPTION = {"any": [{"field": "subject", "op": "contains_any", "value": SECURITY_WORDS}]}


def suggest(hints: set[str]) -> str:
    if "promotions" in hints:
        return "silent"
    if hints & {"social", "bulk", "no_reply"}:
        return "digest"
    return "keep"


def aggregate(metas: list) -> list[dict]:
    groups: dict[str, dict] = defaultdict(lambda: {"count": 0, "names": Counter(), "hints": set(), "latest": None, "subject": None})
    for meta in metas:
        domain = meta.authenticated_domain
        if domain and domain not in GENERIC_DOMAINS:
            key, kind = domain, "domain"
        elif domain:
            key, kind = meta.sender, "sender"
        else:
            key, kind = meta.sender or "(unknown)", "unverified"  # spoofable: shown, but no rule can be made
        g = groups[f"{kind}:{key}"]
        g["kind"], g["key"] = kind, key
        g["count"] += 1
        if meta.sender_name:
            g["names"][meta.sender_name] += 1
        labels = set(meta.labels)
        if "CATEGORY_PROMOTIONS" in labels:
            g["hints"].add("promotions")
        if "CATEGORY_SOCIAL" in labels:
            g["hints"].add("social")
        s = heuristics.suggest(meta)
        if s and s.reason == "bulk_headers":
            g["hints"].add("bulk")
        if s and s.reason == "no_reply_sender":
            g["hints"].add("no_reply")
        if g["latest"] is None or (meta.received_at and meta.received_at > g["latest"]):
            g["latest"], g["subject"] = meta.received_at, meta.subject
    out = []
    for g in sorted(groups.values(), key=lambda g: -g["count"])[:TOP_SENDERS]:
        hints = sorted(g["hints"])
        out.append({
            "key": g["key"], "kind": g["kind"], "name": g["names"].most_common(1)[0][0] if g["names"] else None,
            "count": g["count"], "sample_subject": g["subject"], "hints": hints,
            "suggested": "keep" if g["kind"] == "unverified" else suggest(set(hints)),
        })
    return out


def run(scan_id: uuid.UUID | str) -> None:
    with get_sessionmaker()() as db:
        scan = db.get(OnboardingScan, uuid.UUID(str(scan_id)))
        if scan is None or scan.status in ("done", "running"):
            return
        account = db.get(GmailAccount, scan.account_id)
        scan.status = "running"
        db.commit()
        try:
            provider = provider_for(account)
            ids = provider.list_message_ids(QUERY, MAX_MAILS)
            metas, started = [], time.monotonic()
            for i, mid in enumerate(ids, start=1):
                for attempt in range(4):
                    try:
                        metas.append(parse_metadata(provider.get_metadata(mid)))
                        break
                    except GmailError as exc:
                        if exc.status == 404:
                            break  # deleted meanwhile
                        if exc.status in (429, 500, 503) and attempt < 3:
                            time.sleep(15 * (attempt + 1))
                            continue
                        raise
                # pacing: never faster than PER_MINUTE
                ahead = i / PER_MINUTE * 60 - (time.monotonic() - started)
                if ahead > 0:
                    time.sleep(ahead)
                if i % 50 == 0:
                    scan.scanned = i
                    db.commit()
            scan.senders = aggregate(metas)
            scan.scanned, scan.status, scan.finished_at = len(metas), "done", datetime.now(UTC)
        except AuthRevoked as exc:
            mark_auth_failure(account, exc)
            scan.status, scan.error = "failed", "account needs to reconnect"
        except Exception as exc:
            log.exception("onboarding scan %s failed", scan.id)
            scan.status, scan.error = "failed", type(exc).__name__
        db.commit()


def start(db: Session, account: GmailAccount) -> OnboardingScan:
    """Queue a scan unless one is already queued or running for the account."""
    running = db.scalar(select(OnboardingScan).where(OnboardingScan.account_id == account.id, OnboardingScan.status.in_(("queued", "running"))))
    if running:
        return running
    scan = OnboardingScan(user_id=account.user_id, account_id=account.id)
    db.add(scan)
    db.flush()
    return scan


def apply(db: Session, scan: OnboardingScan, assignments: dict[str, str]) -> list:
    """assignments: sender key -> action. One rule per chosen action, listing its senders."""
    by_key = {s["key"]: s for s in scan.senders or []}
    grouped: dict[str, dict[str, list]] = defaultdict(lambda: {"domain": [], "sender": []})
    for key, action in assignments.items():
        s = by_key.get(key)
        if action not in ACTIONS:
            raise ValueError(f"unknown action {action}")
        if s is None or action == "keep" or s["kind"] == "unverified":
            continue
        grouped[action][s["kind"]].append(key)
    rules = []
    labels = {"silent": "silent", "digest": "digest", "notify_normal": "normal", "notify_urgent": "urgent"}
    for action, kinds in grouped.items():
        leaves = []
        if kinds["domain"]:
            leaves.append({"field": "sender_domain", "op": "in", "value": kinds["domain"]})
        if kinds["sender"]:
            leaves.append({"field": "sender", "op": "in", "value": kinds["sender"]})
        quieting = action in ("silent", "digest")
        draft = {"name": f"From first scan: {labels[action]} ({len(kinds['domain']) + len(kinds['sender'])} senders)",
                 "conditions": {"any": leaves}, "action": {"type": action},
                 # a broad sender rule must never swallow security mail from the same sender
                 "exceptions": SECURITY_EXCEPTION if quieting else None, "account_scope": None}
        rules.append(save_rule(db, scan.user_id, draft, origin="scan"))
    scan.applied_at = datetime.now(UTC)
    return rules

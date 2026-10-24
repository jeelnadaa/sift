"""Processing pipeline for one new message (brief section 7, steps 3-12).

Order: metadata -> dedupe -> user rules (first match wins, ends processing) -> heuristics ->
fingerprint -> body + LLM (only if still undecided and AI is on) -> priority -> notification.

Guarantees:
- Idempotent: a message row is created once per (account, gmail id); the LLM result is stored
  on it and the notification is unique per message, so re-processing never double-notifies
  or double-spends tokens.
- Read-only: nothing here changes mail in Gmail.
- Never hides uncertain mail: anything undecided or failing is delivered as normal priority.
- Never logs subjects, bodies or addresses.
"""
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import heuristics, notify, rules, user_settings
from app.fingerprint import fingerprint, normalize_subject
from app.llm import service as llm
from app.mail.base import AuthRevoked, MailProvider
from app.mail.gmail import GmailError
from app.mail.message import clean_body, extract_body, parse_metadata
from app.models import Fingerprint, Folder, FolderItem, GmailAccount, MailTag, Message, Rule, Tag
from app.redact import redact

log = logging.getLogger(__name__)
SILENT_ACTIONS = {"ignore": "ignored", "silent": "silenced"}
PRIORITY_ACTIONS = {"digest": "digest", "notify_normal": "normal", "notify_urgent": "urgent"}


@dataclass
class Outcome:
    message_id: uuid.UUID | None
    priority: str | None
    decided_by: str  # rule | fingerprint | heuristic | llm | default | duplicate | existing | error
    notified: bool = False
    llm_called: bool = False


def _rule_views(db: Session, user_id: uuid.UUID) -> list[rules.RuleView]:
    rows = db.scalars(select(Rule).where(Rule.user_id == user_id, Rule.enabled.is_(True)))
    return [rules.RuleView(r.id, r.position, r.enabled, r.conditions, r.action, r.exceptions, r.account_scope) for r in rows]


def _apply_extras(db: Session, msg: Message, action: dict) -> list[str]:
    """Category, tag and folder from a rule. mark_read/star need the Gmail modify scope
    (phases 3-4); they are recorded as pending, never executed with the read-only scope."""
    if action.get("category"):
        msg.category = str(action["category"])[:80]
    if action.get("tag"):
        name = str(action["tag"])[:80]
        tag = db.scalar(select(Tag).where(Tag.user_id == msg.user_id, Tag.name == name))
        if tag is None:
            tag = Tag(user_id=msg.user_id, name=name)
            db.add(tag)
            db.flush()
        db.execute(insert(MailTag).values(tag_id=tag.id, message_id=msg.id).on_conflict_do_nothing())
    if action.get("folder_id"):
        try:
            folder = db.get(Folder, uuid.UUID(str(action["folder_id"])))
        except ValueError:
            folder = None
        if folder and folder.user_id == msg.user_id and folder.saved_search_id is None:
            db.execute(insert(FolderItem).values(folder_id=folder.id, account_id=msg.account_id, thread_id=msg.thread_id).on_conflict_do_nothing())
    return [k for k in ("mark_read", "star") if action.get(k)]


def _touch_fingerprint(db: Session, user_id: uuid.UUID, fp: str, template: str, action: str | None, source: str | None) -> Fingerprint:
    stmt = insert(Fingerprint).values(user_id=user_id, hash=fp, sample_subject=template[:300], seen_count=1, last_seen_at=datetime.now(UTC))
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "hash"],
        set_={"seen_count": Fingerprint.seen_count + 1, "last_seen_at": datetime.now(UTC)},
    ).returning(Fingerprint.id)
    row = db.get(Fingerprint, db.execute(stmt).scalar_one())
    if action:
        row.last_action, row.last_action_source = action, source
    return row


def process_message(db: Session, account: GmailAccount, provider: MailProvider, gmail_id: str) -> Outcome:
    existing = db.scalar(select(Message).where(Message.account_id == account.id, Message.gmail_id == gmail_id))
    if existing is not None and existing.status != "processing":
        return Outcome(existing.id, existing.priority, "existing")

    meta = parse_metadata(provider.get_metadata(gmail_id))  # transient Gmail errors propagate -> check retried
    user_id = account.user_id

    if existing is None:
        duplicate = bool(meta.message_id) and db.scalar(
            select(Message.id).where(Message.user_id == user_id, Message.message_id_header == meta.message_id, Message.account_id != account.id)
        )
        stmt = insert(Message).values(
            user_id=user_id, account_id=account.id, gmail_id=meta.gmail_id, thread_id=meta.thread_id,
            message_id_header=meta.message_id, sender=meta.sender[:320], sender_name=meta.sender_name[:200],
            authenticated_domain=meta.authenticated_domain, subject=meta.subject, snippet=meta.snippet[:300],
            received_at=meta.received_at, labels=meta.labels, list_id=meta.list_id[:320] if meta.list_id else None,
            has_attachment=meta.has_attachment, status="duplicate" if duplicate else "processing",
            priority="silent" if duplicate else None,
        ).on_conflict_do_nothing(index_elements=["account_id", "gmail_id"]).returning(Message.id)
        message_id = db.execute(stmt).scalar()
        db.commit()  # the row exists from here on: a crash leaves it "processing" and the next check resumes it
        if message_id is None:
            return Outcome(None, None, "existing")  # another worker got there first
        if duplicate:
            # Same mail delivered to two of my addresses: stored, notified once (for the first copy).
            return Outcome(message_id, "silent", "duplicate")
        msg = db.get(Message, message_id)
    else:
        msg = existing

    try:
        outcome = _classify(db, account, provider, meta, msg)
    except (AuthRevoked, GmailError, httpx.HTTPError):
        db.rollback()  # row stays "processing"; the whole check is retried from the same cursor
        raise
    except Exception:
        log.exception("classification failed for message %s; delivering as normal", msg.id)
        db.rollback()
        msg = db.get(Message, msg.id)
        msg.priority, msg.category, msg.status = "normal", msg.category or "other", "processed"
        outcome = Outcome(msg.id, "normal", "error")

    if notify.notify_message(db, msg, account):
        outcome.notified = True
    db.commit()
    return outcome


def _classify(db: Session, account: GmailAccount, provider: MailProvider, meta, msg: Message) -> Outcome:
    user_id = account.user_id
    settings = user_settings.get(db, user_id, account.id)
    body_cache: dict = {}

    def load_body() -> str:
        if "text" not in body_cache:
            full = provider.get_full(meta.gmail_id)
            text, files = extract_body(full.get("payload", {}))
            body_cache["text"] = text
            if files:
                msg.has_attachment = True
        return body_cache["text"]

    ctx = rules.MailContext(
        account_id=str(account.id), sender=meta.sender, authenticated_domain=meta.authenticated_domain,
        subject=meta.subject, labels=meta.labels, headers=meta.headers, has_attachment=meta.has_attachment,
        received_at=meta.received_at or datetime.now(UTC), timezone=settings["timezone"], body_loader=load_body,
    )
    extras: dict = {}

    # 5. user rules: first match wins and ends processing
    match = rules.evaluate(_rule_views(db, user_id), ctx)
    fp = template = None
    if meta.authenticated_domain:
        template = normalize_subject(meta.subject)
        fp = fingerprint(meta.authenticated_domain, meta.subject)
        msg.fingerprint = fp

    if match:
        db.execute(update(Rule).where(Rule.id == match.rule_id).values(hit_count=Rule.hit_count + 1, last_hit_at=datetime.now(UTC)))
        msg.matched_rule_id = match.rule_id
        pending = _apply_extras(db, msg, match.action)
        if pending:
            extras["pending_gmail_actions"] = pending
        kind = match.action["type"]
        if fp:
            _touch_fingerprint(db, user_id, fp, template, kind if kind in SILENT_ACTIONS else None, "rule")
        if kind in SILENT_ACTIONS:
            msg.status, msg.priority = SILENT_ACTIONS[kind], "silent"
            msg.extraction = extras or None
            return Outcome(msg.id, "silent", "rule")
        if kind in PRIORITY_ACTIONS:
            msg.priority, msg.status = PRIORITY_ACTIONS[kind], "processed"
            msg.category = msg.category or "other"
            msg.extraction = extras or None
            return Outcome(msg.id, msg.priority, "rule")
        # kind == "llm": fall through to the LLM step, skipping heuristics and fingerprints

    # 6. heuristics (suggest only)
    suggestion = None if match else heuristics.suggest(meta)

    # 7. fingerprint: a template a rule or the user silenced before is silenced again
    if fp and not match:
        row = _touch_fingerprint(db, user_id, fp, template, None, None)
        if row.last_action in SILENT_ACTIONS and row.last_action_source in ("rule", "user"):
            msg.status, msg.priority, msg.category = SILENT_ACTIONS[row.last_action], "silent", "other"
            return Outcome(msg.id, "silent", "fingerprint")

    if suggestion and suggestion.strength == "strong":
        msg.priority, msg.status, msg.category = "digest", "processed", "other"
        msg.extraction = {"heuristic": suggestion.reason}
        return Outcome(msg.id, "digest", "heuristic")

    # 8-9. body + LLM, only when AI is on (the gate is checked before any body fetch)
    llm_called = False
    extraction = None
    if msg.extraction and msg.extraction.get("source") == "llm":
        extraction = msg.extraction  # cached from an interrupted earlier run: never pay twice
    elif llm.ai_enabled(db, user_id) and llm.under_cap(db, user_id):
        body = redact(clean_body(load_body()))
        extraction = llm.extract(db, user_id, account.id, meta.sender, meta.subject, body)
        llm_called = extraction is not None and extraction.get("source") == "llm"
        if llm_called:
            msg.extraction = extraction
            db.commit()  # cache the result (and its token usage) before anything else can fail
        if extraction and extraction.get("error") == "key_invalid":
            cred = llm.credential(db, user_id)
            if cred and not cred.invalid_notified:
                notify.send_system(db, user_id, "Your AI key stopped working", "Sift keeps running without AI. Update the key in Settings.")
                cred.invalid_notified = True

    # 11. decide priority
    if extraction and extraction.get("source") == "llm":
        priority = extraction["priority"]
        if priority == "digest" and extraction["confidence"] < 0.4:
            priority = "normal"  # uncertain -> normal
        msg.category = extraction["category"]
        decided = "llm"
    else:
        priority, decided = "normal", "default"  # AI off or failed: normal / other, never hidden
        msg.category = "other"
    msg.priority, msg.status = priority, "processed"
    msg.extraction = {**(extraction or {}), **extras, **({"heuristic": suggestion.reason} if suggestion else {})} or None
    return Outcome(msg.id, priority, decided, llm_called=llm_called)

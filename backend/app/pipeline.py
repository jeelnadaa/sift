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

Late mail (the server was off, see app.accounts catch-up): mail older than AI_MAX_AGE, and every
imported mail, is handled by rules only: no AI, no push. Mail older than LATE_AGE still gets the AI
but only urgent mail pushes on its own; the rest is "held" and summed up in one push by the caller.
"""
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import folder_ai, grouping, heuristics, notify, opportunities, outbox, places, rules, todos, user_settings, vip
from app.fingerprint import fingerprint, normalize_subject
from app.llm import service as llm
from app.mail.base import AuthRevoked, MailProvider
from app.mail.gmail import GmailError
from app.mail.message import clean_body, extract_body, parse_metadata
from app.models import Fingerprint, Folder, FolderItem, GmailAccount, MailTag, Message, Opportunity, Rule, Tag
from app.redact import redact
from app import snooze as snooze_service
from app.search import alerts, semantic

log = logging.getLogger(__name__)
SILENT_ACTIONS = {"ignore": "ignored", "silent": "silenced"}
PRIORITY_ACTIONS = {"digest": "digest", "notify_normal": "normal", "notify_urgent": "urgent"}
LATE_AGE = timedelta(minutes=30)  # live mail lands within seconds; older means Sift was off
AI_MAX_AGE = timedelta(hours=72)  # older mail is never sent to the AI (no backfilling with tokens)


@dataclass
class Outcome:
    message_id: uuid.UUID | None
    priority: str | None
    decided_by: str  # rule | fingerprint | heuristic | llm | default | duplicate | existing | gone | error
    notified: bool = False
    llm_called: bool = False
    held: bool = False  # late mail whose push was left for the caller's one summary push
    quiet: bool = False  # imported or too old: rules only, no push


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


def _run_gmail_actions(account: GmailAccount, provider: MailProvider, msg: Message, actions: list[str]) -> list[str]:
    """Rule extras mark_read / star, done in Gmail when the user gave this account write access
    (Phase 3c). Returns what is still pending (no write access, or Gmail refused)."""
    from app.accounts import can_modify

    if not can_modify(account) or not hasattr(provider, "modify_message"):
        return actions
    add = ["STARRED"] if "star" in actions else []
    remove = ["UNREAD"] if "mark_read" in actions else []
    try:
        provider.modify_message(msg.gmail_id, add, remove)
    except Exception:
        log.warning("rule's Gmail actions failed for message %s; left pending", msg.id)
        return actions
    labels = [x for x in (msg.labels or []) if x not in remove]
    msg.labels = labels + [x for x in add if x not in labels]
    return []


def _touch_fingerprint(db: Session, user_id: uuid.UUID, fp: str, template: str, action: str | None, source: str | None, domain: str | None = None) -> Fingerprint:
    stmt = insert(Fingerprint).values(user_id=user_id, hash=fp, domain=domain, sample_subject=template[:300], seen_count=1, last_seen_at=datetime.now(UTC))
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "hash"],
        set_={"seen_count": Fingerprint.seen_count + 1, "last_seen_at": datetime.now(UTC)},
    ).returning(Fingerprint.id)
    row = db.get(Fingerprint, db.execute(stmt).scalar_one())
    if action:
        row.last_action, row.last_action_source = action, source
    return row


def process_message(db: Session, account: GmailAccount, provider: MailProvider, gmail_id: str, mode: str = "live") -> Outcome:
    """`mode` is live (change detection, including catch-up after downtime) or import (a new
    account's recent mail): imported mail is stored and sorted by rules, never sent to the AI or pushed."""
    existing = db.scalar(select(Message).where(Message.account_id == account.id, Message.gmail_id == gmail_id))
    if existing is not None and existing.status != "processing":
        return Outcome(existing.id, existing.priority, "existing")

    try:
        meta = parse_metadata(provider.get_metadata(gmail_id))  # transient Gmail errors propagate -> check retried
    except GmailError as exc:
        if exc.status != 404:
            raise
        # Gone from Gmail before we got to it (deleted, or a draft that was sent). Skip it: retrying
        # can never succeed, and it would hold up every mail after it.
        log.info("message %s no longer exists in Gmail; skipped", gmail_id)
        if existing is not None:
            existing.status, existing.priority = "processed", existing.priority or "normal"
            db.commit()
        return Outcome(existing.id if existing else None, None, "gone")
    user_id = account.user_id

    if existing is None:
        if meta.message_id:
            db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"msgid:{user_id}:{meta.message_id}"})
        duplicate = bool(meta.message_id) and db.scalar(
            select(Message.id).where(Message.user_id == user_id, Message.message_id_header == meta.message_id, Message.account_id != account.id)
        )
        stmt = insert(Message).values(
            user_id=user_id, account_id=account.id, gmail_id=meta.gmail_id, thread_id=meta.thread_id,
            message_id_header=meta.message_id, sender=meta.sender[:320], sender_name=meta.sender_name[:200],
            authenticated_domain=meta.authenticated_domain, subject=meta.subject, snippet=meta.snippet[:300],
            received_at=meta.received_at, labels=meta.labels, list_id=meta.list_id[:320] if meta.list_id else None,
            has_attachment=meta.has_attachment, header_names=sorted(meta.headers), status="duplicate" if duplicate else "processing",
            unsubscribe_url=meta.unsubscribe_url, unsubscribe_mailto=meta.unsubscribe_mailto, unsubscribe_post=meta.unsubscribe_post,
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

    age = datetime.now(UTC) - (meta.received_at or datetime.now(UTC))
    quiet = mode == "import" or age > AI_MAX_AGE
    late = not quiet and age > LATE_AGE
    try:
        outcome = _classify(db, account, provider, meta, msg, ai_allowed=not quiet)
    except (AuthRevoked, GmailError, httpx.HTTPError):
        db.rollback()  # row stays "processing"; the whole check is retried from the same cursor
        raise
    except Exception:
        log.exception("classification failed for message %s; delivering as normal", msg.id)
        db.rollback()
        msg = db.get(Message, msg.id)
        msg.priority, msg.category, msg.status = "normal", msg.category or "other", "processed"
        outcome = Outcome(msg.id, "normal", "error")

    outcome.quiet = quiet
    if not quiet:
        folder_ai.on_processed(db, msg)  # AI filing and auto-sort into subfolders; never raises
    places.route(db, msg)  # every custom group / folder with criteria it fits (searches only when quiet); never raises
    snooze_service.on_new_mail(db, msg)  # a reply wakes its snoozed conversation
    outbox.on_new_mail(db, msg, account)  # ...and resolves a "remind me if no reply"
    if msg.status == "processed":
        grouping.assign_if_enabled(db, msg)  # display only; before notify so a muted group is known
    if quiet:
        pass
    elif late and msg.priority != "urgent":
        outcome.held = msg.priority in notify.NOTIFY_PRIORITIES and msg.status == "processed"
    elif notify.notify_message(db, msg, account):
        outcome.notified = True
    if not quiet:  # imports announce themselves once per batch (app.accounts)
        from app import events
        events.publish(db, msg.user_id, "new_mail", ids=[msg.id])
    if msg.has_attachment:
        try:
            from app import attachments
            full = provider.get_full(meta.gmail_id)
            attachments.index_attachments(db, msg, account, full.get("payload", {}))
        except Exception:
            log.warning("could not index attachments for message %s", msg.id)
    db.commit()
    if not quiet:
        if not outcome.notified and not late:
            alerts.check_new(db, msg, account, provider)  # saved searches set to notify; never raises
        semantic.index_new(db, msg)  # after the notification is out; uses the user's key, never raises
    return outcome


def _classify(db: Session, account: GmailAccount, provider: MailProvider, meta, msg: Message, ai_allowed: bool = True) -> Outcome:
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
        received_at=meta.received_at or datetime.now(UTC), timezone=settings["timezone"], snippet=meta.snippet, body_loader=load_body,
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
            pending = _run_gmail_actions(account, provider, msg, pending)
        if pending:
            extras["pending_gmail_actions"] = pending
        kind = match.action["type"]
        if fp:
            _touch_fingerprint(db, user_id, fp, template, kind if kind in SILENT_ACTIONS else None, "rule", meta.authenticated_domain)
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

    # VIP sender: elevate priority to urgent and mark processed
    if vip.is_vip(db, user_id, meta.sender):
        msg.priority, msg.status = "urgent", "processed"
        msg.category = msg.category or "other"
        msg.extraction = {**(extras or {}), "vip": True}
        return Outcome(msg.id, "urgent", "vip")

    # 6. heuristics (suggest only)
    suggestion = None if match else heuristics.suggest(meta)

    # 7. fingerprint: a template the USER silenced before is silenced again. Templates learned from
    #    a rule are not applied on their own: the rule (with its exceptions) already decided above,
    #    and a learned copy would override its exceptions (e.g. "unless debit over 2000") and keep
    #    silencing after the user disables the rule. They still feed suggestions and stats.
    if fp and not match:
        row = _touch_fingerprint(db, user_id, fp, template, None, None, meta.authenticated_domain)
        if row.last_action in SILENT_ACTIONS and row.last_action_source == "user":
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
    elif ai_allowed and llm.ai_enabled(db, user_id) and llm.under_cap(db, user_id):
        body = redact(clean_body(load_body()))
        opp_text, opp_keys = opportunities.prompt_list(opportunities.active(db, user_id))
        place_text, place_keys = places.prompt_block(places.load(db, user_id))  # described groups/folders, same call
        extraction = llm.extract(db, user_id, account.id, meta.sender, redact(meta.subject), body, meta.received_at, opp_text, list(opp_keys),
                                 place_text, place_keys)
        llm_called = extraction is not None and extraction.get("source") == "llm"
        if llm_called:
            # the o1/o2 keys the model saw, so a resumed run maps its answer to the same opportunities
            extraction["opportunity_keys"] = {k: str(o.id) for k, o in opp_keys.items()}
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
        if priority == "digest" and (extraction["confidence"] < 0.4 or suggestion is None):
            # Uncertain -> normal. Mail from a real person (no bulk headers, no no-reply sender,
            # not Promotions/Social) is never demoted to digest by the model either.
            priority = "normal"
        msg.category = extraction["category"]
        decided = "llm"
    else:
        priority, decided = "normal", "default"  # AI off or failed: normal / other, never hidden
        msg.category = "other"
    msg.priority, msg.status = priority, "processed"
    merged = {**(extraction or {}), **extras, **({"heuristic": suggestion.reason} if suggestion else {})}
    # 10. opportunity matching, to-dos and deadline reminders (AI only; by hand in AI-off mode)
    if decided == "llm":
        merged = _timeline_and_todos(db, msg, merged)
    msg.extraction = merged or None
    return Outcome(msg.id, priority, decided, llm_called=llm_called)


def _parse_deadline(value: str | None) -> datetime | None:
    try:
        d = datetime.fromisoformat(value or "")
    except ValueError:
        return None
    return d if d.tzinfo else None


def _timeline_and_todos(db: Session, msg: Message, ext: dict, *, timeline_too: bool = True, todos_too: bool = True,
                        force_timeline: bool = False) -> dict:
    """Company timeline, to-do and deadline reminder from the AI's reading of a mail. AI tasks on
    a folder use the flags: only timelines (forced: the user said this folder is about companies)
    or only to-dos."""
    ext = dict(ext)
    kind = opportunities.EVENT_KIND.get(ext.get("category") or "")
    opp = None
    if timeline_too and (kind or ext.get("opportunity") not in (None, "none") or (force_timeline and ext.get("company"))):
        keys = {}
        for k, oid in (ext.get("opportunity_keys") or {}).items():
            o = db.get(Opportunity, uuid.UUID(oid))
            if o is not None and o.user_id == msg.user_id:
                keys[k] = o
        result = opportunities.match(db, msg, ext, keys)
        opp = result.opportunity
        if opp is not None:
            details = {k: ext.get(k) for k in ("deadline", "links", "platform", "summary")}
            opportunities.attach(db, opp, msg, kind or "update", details, result.matched_by)
            ext["opportunity_id"], ext["matched_by"] = str(opp.id), result.matched_by
            ext.pop("company_question", None)
        else:
            # unresolved: the notification asks "which company?" (up to 3 recent drives, or "new")
            ext["company_question"] = [{"id": str(o.id), "name": o.company} for o in result.candidates]

    if not todos_too:
        return ext
    deadline = _parse_deadline(ext.get("deadline"))
    title = (ext.get("summary") or msg.subject or "Mail needs action").strip()
    if opp is not None and opp.company.lower() not in title.lower():
        title = f"{opp.company}: {title}"
    todo = None
    if ext.get("action_needed"):
        todo = todos.ai_todo(db, msg.user_id, msg.id, title, deadline, opp.id if opp else None)
        ext["todo_id"] = str(todo.id)
    if deadline is not None:
        todos.schedule_deadline(db, msg.user_id, f"msg:{msg.id}", title, deadline,
                                message_id=msg.id, opportunity_id=opp.id if opp else None, todo_id=todo.id if todo else None)
    return ext

"""Rule helpers (brief section 8): preview, one-tap "ignore mails like this", repeat-template
suggestions and "not like this". The engine itself is app/rules.py."""
import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import rules as engine
from app import user_settings
from app.fingerprint import fingerprint, normalize_subject
from app.models import Fingerprint, Message, Rule
from app.opportunities import GENERIC_DOMAINS

PREVIEW_LIMIT = 500
SUGGEST_MIN = 5
SUGGEST_WINDOW = timedelta(days=30)
_PLACEHOLDER = re.compile(r"<(url|email|amount|date|time|id|num)>")


class RuleToolError(ValueError):
    pass


# ---- preview -------------------------------------------------------------------------------

def context_for(msg: Message, tz: str) -> engine.MailContext:
    """Stored metadata only. Header values and bodies are never stored, so header conditions
    see presence only and body conditions cannot match in a preview."""
    return engine.MailContext(
        account_id=str(msg.account_id), sender=msg.sender or "", authenticated_domain=msg.authenticated_domain,
        subject=msg.subject or "", labels=list(msg.labels or []), headers={h: "" for h in (msg.header_names or [])},
        has_attachment=msg.has_attachment, received_at=msg.received_at or msg.created_at, timezone=tz, snippet=msg.snippet or "", body_loader=lambda: "",
    )


def preview(db: Session, user_id: uuid.UUID, conditions: dict, exceptions: dict | None = None, account_scope: list | None = None) -> dict:
    engine.validate_condition(conditions)
    if exceptions:
        engine.validate_condition(exceptions)
    tz = user_settings.get(db, user_id)["timezone"]
    view = engine.RuleView("preview", 0, True, conditions, {"type": "silent"}, exceptions, account_scope)
    rows = list(db.scalars(
        select(Message).where(Message.user_id == user_id, Message.status != "duplicate")
        .order_by(Message.received_at.desc().nulls_last()).limit(PREVIEW_LIMIT)
    ))
    hits = [m for m in rows if engine.evaluate([view], context_for(m, tz))]
    important = [m for m in hits if is_important(m)]
    # important matches first, so the user sees what a quieting rule would hide
    ordered = important + [m for m in hits if m not in important]
    return {
        "checked": len(rows),
        "matches": len(hits),
        "important_matches": len(important),
        "samples": [{"id": str(m.id), "sender": m.sender_name or m.sender, "subject": m.subject,
                     "received_at": m.received_at.isoformat() if m.received_at else None, "priority": m.priority,
                     "important": m in important} for m in ordered[:10]],
        "body_not_previewed": engine.needs_body(conditions) or engine.needs_body(exceptions),
    }


IMPORTANT_CATEGORIES = {"placement_announcement", "registration", "assessment_link", "interview", "result", "recruiter", "action_needed"}


def is_important(m: Message) -> bool:
    """Mail a quieting rule should not hide without the user noticing: urgent, needs action,
    hiring-related, or on a company timeline."""
    ext = m.extraction or {}
    return (m.priority == "urgent" or bool(ext.get("action_needed")) or bool(ext.get("opportunity_id"))
            or (m.category or "") in IMPORTANT_CATEGORIES)


# ---- "ignore mails like this" ----------------------------------------------------------------

def template_regex(subject: str) -> str:
    """Regex for the subject's template: literal words kept, variable parts (numbers, amounts,
    dates, ids, links) become wildcards, reply prefixes allowed."""
    template = normalize_subject(subject)
    parts = _PLACEHOLDER.split(template)
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            out.append(".+?")
        elif part:
            out.append(r"\s+".join(re.escape(w) for w in part.split(" ")) if part.strip() else r"\s+")
    body = "".join(out).strip()
    regex = rf"^((re|fwd?|fw)\s*:\s*)*{body}$"
    return regex[: engine.MAX_REGEX]


def sender_condition(msg: Message) -> dict:
    domain = msg.authenticated_domain
    if not domain:
        raise RuleToolError("Sift can't verify who sent this mail, so it won't make a sender rule for it")
    if domain in GENERIC_DOMAINS:
        return {"field": "sender", "op": "is", "value": msg.sender}
    return {"field": "sender_domain", "op": "is", "value": domain}


def like_this(msg: Message, action: str = "silent") -> dict:
    """Draft rule (not saved): same verified sender and same subject template."""
    conditions = {"all": [sender_condition(msg)]}
    if msg.subject and msg.subject.strip():
        regex = template_regex(msg.subject)
        if re.search(regex, msg.subject, re.I):
            conditions["all"].append({"field": "subject", "op": "matches", "value": regex})
    who = msg.sender_name or msg.authenticated_domain or msg.sender
    return {"name": f"{'Silence' if action == 'silent' else action.replace('_', ' ').capitalize()}: {who} · {(msg.subject or '')[:40]}".strip(" ·"),
            "conditions": conditions, "action": {"type": action}, "exceptions": None, "account_scope": None}


def remember_template(db: Session, msg: Message, action: str, source: str = "user") -> None:
    """Teach the fingerprint table directly, so the next copy is handled even before rules run."""
    if not (msg.authenticated_domain and msg.subject):
        return
    fp = fingerprint(msg.authenticated_domain, msg.subject)
    row = db.scalar(select(Fingerprint).where(Fingerprint.user_id == msg.user_id, Fingerprint.hash == fp))
    if row is None:
        row = Fingerprint(user_id=msg.user_id, hash=fp, domain=msg.authenticated_domain, sample_subject=normalize_subject(msg.subject)[:300], seen_count=1, last_seen_at=datetime.now(UTC))
        db.add(row)
    row.last_action, row.last_action_source = action, source


def next_position(db: Session, user_id: uuid.UUID) -> int:
    return (db.scalar(select(func.max(Rule.position)).where(Rule.user_id == user_id)) or 0) + 1


def save_rule(db: Session, user_id: uuid.UUID, draft: dict, origin: str) -> Rule:
    engine.validate_condition(draft["conditions"])
    engine.validate_action(draft["action"])
    if draft.get("exceptions"):
        engine.validate_condition(draft["exceptions"])
    rule = Rule(user_id=user_id, position=next_position(db, user_id), origin=origin, enabled=True,
                name=draft["name"][:200], conditions=draft["conditions"], action=draft["action"],
                exceptions=draft.get("exceptions"), account_scope=draft.get("account_scope"))
    db.add(rule)
    db.flush()
    return rule


# ---- repeat-template suggestions ------------------------------------------------------------------

def suggestions(db: Session, user_id: uuid.UUID, limit: int = 10) -> list[dict]:
    since = datetime.now(UTC) - SUGGEST_WINDOW
    fps = db.scalars(
        select(Fingerprint).where(
            Fingerprint.user_id == user_id, Fingerprint.last_action.is_(None), Fingerprint.domain.is_not(None),
            Fingerprint.seen_count >= SUGGEST_MIN, Fingerprint.last_seen_at >= since,
        ).order_by(Fingerprint.seen_count.desc()).limit(limit * 3)
    )
    out = []
    for fp in fps:
        recent = list(db.scalars(
            select(Message).where(Message.user_id == user_id, Message.fingerprint == fp.hash, Message.received_at >= since)
            .order_by(Message.received_at.desc()).limit(50)
        ))
        if len(recent) < SUGGEST_MIN or any(m.priority == "urgent" for m in recent):
            continue  # never suggest silencing a template that has carried urgent mail
        latest = recent[0]
        out.append({
            "id": str(fp.id), "domain": fp.domain, "template": fp.sample_subject, "count": len(recent),
            "sample_subject": latest.subject, "sender": latest.sender_name or latest.sender, "message_id": str(latest.id),
        })
        if len(out) >= limit:
            break
    return out


def _own_fingerprint(db: Session, user_id: uuid.UUID, fp_id: uuid.UUID) -> Fingerprint:
    fp = db.get(Fingerprint, fp_id)
    if fp is None or fp.user_id != user_id:
        raise RuleToolError("suggestion not found")
    return fp


def accept_suggestion(db: Session, user_id: uuid.UUID, fp_id: uuid.UUID, action: str) -> Rule:
    if action not in ("silent", "digest"):
        raise RuleToolError("action must be silent or digest")
    fp = _own_fingerprint(db, user_id, fp_id)
    latest = db.scalar(select(Message).where(Message.user_id == user_id, Message.fingerprint == fp.hash).order_by(Message.received_at.desc()).limit(1))
    if latest is None:
        raise RuleToolError("no mail left for this suggestion")
    rule = save_rule(db, user_id, {**like_this(latest, action), "account_scope": None}, origin="suggestion")
    fp.last_action, fp.last_action_source = action, "user"
    return rule


def dismiss_suggestion(db: Session, user_id: uuid.UUID, fp_id: uuid.UUID) -> None:
    fp = _own_fingerprint(db, user_id, fp_id)
    fp.last_action, fp.last_action_source = "keep", "user"


# ---- "not like this" -----------------------------------------------------------------------------

def unsilence(db: Session, msg: Message) -> dict:
    """Bring a silenced mail back to the feed. A learned template stops silencing; a rule is
    reported back so the user can edit or disable it (rules are never changed silently)."""
    rule_id = str(msg.matched_rule_id) if msg.matched_rule_id else None
    if msg.authenticated_domain and msg.subject:
        fp = db.scalar(select(Fingerprint).where(Fingerprint.user_id == msg.user_id, Fingerprint.hash == fingerprint(msg.authenticated_domain, msg.subject)))
        if fp is not None and fp.last_action in ("silent", "ignore"):
            fp.last_action, fp.last_action_source = "keep", "user"
    msg.status, msg.priority = "processed", "normal"
    return {"rule_id": rule_id}

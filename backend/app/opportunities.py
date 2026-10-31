"""Opportunities: one company drive, across all of the user's accounts (brief section 10).

Matching a new mail to an opportunity, in order:
  1. name   - the extracted company equals (or fuzzily matches) a company name or alias
  2. ai     - the model picked an active opportunity from the list it was shown
  3. new    - the model says it is a new drive and named the company
  4. thread - another mail in the same Gmail thread is already on an opportunity
  5. domain - the sender's authenticated domain was taught by the user for an opportunity
  6. link   - a link in the mail shares a host with links already on an opportunity
  7. timing - exactly one recently active opportunity is still missing this kind of event
Otherwise the mail is flagged with a "which company?" question; the user's answer is learned as
an alias (if the mail named a company) or a sender domain, so the next mail matches by itself.
All of this runs only with AI on; in AI-off mode opportunities are managed by hand.
"""
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from urllib.parse import urlparse

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Message, Opportunity, OpportunityEvent

# extraction category -> timeline event kind; only these categories belong on a timeline
EVENT_KIND = {
    "placement_announcement": "announcement",
    "registration": "registration",
    "assessment_link": "assessment",
    "interview": "interview",
    "result": "result",
    "recruiter": "update",
}
FUZZY = 0.88
RECENT = timedelta(days=14)
GENERIC_DOMAINS = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "yahoo.com", "yahoo.co.in", "icloud.com", "proton.me", "protonmail.com"}
GENERIC_LINK_HOSTS = {"forms.gle", "docs.google.com", "drive.google.com", "bit.ly", "tinyurl.com", "linkedin.com", "www.linkedin.com", "meet.google.com", "zoom.us", "teams.microsoft.com"}
_SUFFIX = re.compile(
    r"\b(private limited|pvt\.? ltd\.?|pvt|ltd\.?|limited|inc\.?|llc|llp|plc|corp\.?|corporation|co\.?|company|"
    r"technologies|technology|solutions|software|services|systems|labs|india|global|group)\b"
)


def normalize(name: str | None) -> str:
    s = (name or "").lower().replace("&", " and ")
    s = _SUFFIX.sub(" ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def names_of(opp: Opportunity) -> list[str]:
    return [opp.company, *(opp.aliases or [])]


def name_score(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def find_by_name(opps: list[Opportunity], name: str | None) -> Opportunity | None:
    if not normalize(name):
        return None
    best, best_score = None, 0.0
    for opp in opps:
        score = max(name_score(name, n) for n in names_of(opp))
        if score > best_score:
            best, best_score = opp, score
    return best if best_score >= FUZZY else None


def active(db: Session, user_id: uuid.UUID) -> list[Opportunity]:
    return list(db.scalars(select(Opportunity).where(Opportunity.user_id == user_id, Opportunity.status == "active").order_by(Opportunity.updated_at.desc())))


def prompt_list(opps: list[Opportunity], limit: int = 30) -> tuple[str, dict[str, Opportunity]]:
    """Short keys (o1, o2, ...) for the prompt; ids never go to the model."""
    keys = {f"o{i}": opp for i, opp in enumerate(opps[:limit], start=1)}
    lines = [f"- {k}: {o.company}" + (f" (also: {', '.join(o.aliases)})" if o.aliases else "") for k, o in keys.items()]
    return "\n".join(lines) or "(none yet)", keys


def _hosts(links: list[dict] | None) -> set[str]:
    hosts = set()
    for link in links or []:
        host = (urlparse(str(link.get("url", ""))).hostname or "").lower()
        if host and host not in GENERIC_LINK_HOSTS:
            hosts.add(host.removeprefix("www."))
    return hosts


@dataclass
class MatchResult:
    opportunity: Opportunity | None
    matched_by: str | None  # name, ai, new, thread, domain, link, timing
    candidates: list[Opportunity]  # for the "which company?" question when unresolved


def match(db: Session, msg: Message, extraction: dict, keys: dict[str, Opportunity]) -> MatchResult:
    opps = active(db, msg.user_id)
    company = extraction.get("company")
    choice = extraction.get("opportunity")
    kind = EVENT_KIND.get(extraction.get("category") or "")

    if (opp := find_by_name(opps, company)) is not None:
        return MatchResult(opp, "name", [])
    if choice in keys and keys[choice].status == "active":
        return MatchResult(keys[choice], "ai", [])
    if choice == "new" and normalize(company):
        opp = Opportunity(user_id=msg.user_id, company=company.strip()[:200], aliases=[], domains=[])
        db.add(opp)
        db.flush()
        return MatchResult(opp, "new", [])

    # fallbacks for "unsure" (or "new" without a company name)
    thread_opp = db.scalar(
        select(Opportunity).join(OpportunityEvent, OpportunityEvent.opportunity_id == Opportunity.id)
        .join(Message, Message.id == OpportunityEvent.message_id)
        .where(Message.account_id == msg.account_id, Message.thread_id == msg.thread_id, Message.id != msg.id, Opportunity.status == "active")
        .limit(1)
    )
    if thread_opp is not None:
        return MatchResult(thread_opp, "thread", [])

    domain = msg.authenticated_domain
    if domain:
        for opp in opps:
            if any(domain == d or domain.endswith("." + d) for d in (opp.domains or [])):
                return MatchResult(opp, "domain", [])

    hosts = _hosts(extraction.get("links"))
    if hosts:
        for opp in opps:
            event_links = [l for e in db.scalars(select(OpportunityEvent.details).where(OpportunityEvent.opportunity_id == opp.id)) for l in ((e or {}).get("links") or [])]
            if hosts & _hosts(event_links):
                return MatchResult(opp, "link", [])

    if kind in ("registration", "assessment", "interview", "result"):
        since = datetime.now(UTC) - RECENT
        recent = [o for o in opps if o.updated_at >= since]
        missing = [o for o in recent if not db.scalar(select(OpportunityEvent.id).where(OpportunityEvent.opportunity_id == o.id, OpportunityEvent.kind == kind).limit(1))]
        if len(missing) == 1:
            return MatchResult(missing[0], "timing", [])

    return MatchResult(None, None, opps[:3])


def attach(db: Session, opp: Opportunity, msg: Message, kind: str, details: dict, matched_by: str) -> OpportunityEvent | None:
    """Idempotent: a message is on at most one opportunity (unique message_id)."""
    stmt = insert(OpportunityEvent).values(
        opportunity_id=opp.id, message_id=msg.id, kind=kind, details=details, matched_by=matched_by,
        occurred_at=msg.received_at or datetime.now(UTC),
    ).on_conflict_do_nothing(index_elements=["message_id"]).returning(OpportunityEvent.id)
    event_id = db.execute(stmt).scalar()
    refresh_deadline(db, opp)
    opp.updated_at = datetime.now(UTC)
    return db.get(OpportunityEvent, event_id) if event_id else None


def refresh_deadline(db: Session, opp: Opportunity) -> None:
    """The opportunity's deadline is the earliest upcoming deadline among its events."""
    now = datetime.now(UTC)
    upcoming = []
    for details in db.scalars(select(OpportunityEvent.details).where(OpportunityEvent.opportunity_id == opp.id)):
        try:
            d = datetime.fromisoformat((details or {}).get("deadline") or "")
        except ValueError:
            continue
        if d.tzinfo and d > now:
            upcoming.append(d)
    if upcoming:
        opp.deadline = min(upcoming)


def learn(opp: Opportunity, msg: Message, extraction: dict | None) -> str | None:
    """Remember the user's answer: the mail's company name as an alias, else its sender domain."""
    company = (extraction or {}).get("company")
    if normalize(company) and max(name_score(company, n) for n in names_of(opp)) < 1.0:
        opp.aliases = [*(opp.aliases or []), company.strip()[:120]]
        return f"alias:{company}"
    domain = msg.authenticated_domain
    if domain and domain not in GENERIC_DOMAINS and domain not in (opp.domains or []):
        opp.domains = [*(opp.domains or []), domain]
        return f"domain:{domain}"
    return None


def assign(db: Session, opp: Opportunity, msg: Message, kind: str | None = None, learn_too: bool = False) -> str | None:
    """Put a mail on a timeline by hand (moved, never duplicated). Returns what was learned, if asked."""
    db.execute(delete(OpportunityEvent).where(OpportunityEvent.message_id == msg.id))
    ext = dict(msg.extraction or {})
    kind = kind or EVENT_KIND.get(ext.get("category") or "") or "update"
    details = {k: ext.get(k) for k in ("deadline", "links", "platform", "summary")}
    attach(db, opp, msg, kind, details, "user")
    learned = learn(opp, msg, ext) if learn_too else None
    ext.pop("company_question", None)
    ext["opportunity_id"], ext["matched_by"] = str(opp.id), "user"
    msg.extraction = ext
    return learned

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app import opportunities as opp_service
from app.db import get_db
from app.models import EVENT_KINDS, GmailAccount, Message, Opportunity, OpportunityEvent, User
from app.security import current_user

router = APIRouter(prefix="/api/v1")


def _clean_names(values: list[str]) -> list[str]:
    seen, out = set(), []
    for v in values:
        v = v.strip()[:120]
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out[:20]


class OpportunityIn(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    aliases: list[str] = []
    deadline: datetime | None = None

    @field_validator("company")
    @classmethod
    def strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("company is required")
        return v


class OpportunityPatch(BaseModel):
    company: str | None = Field(default=None, min_length=1, max_length=200)
    aliases: list[str] | None = None
    status: str | None = Field(default=None, pattern="^(active|closed)$")
    deadline: datetime | None = None
    clear_deadline: bool = False


def _own(db: Session, user: User, opportunity_id: uuid.UUID) -> Opportunity:
    o = db.get(Opportunity, opportunity_id)
    if o is None or o.user_id != user.id:
        raise HTTPException(404, "opportunity not found")
    return o


def opportunity_json(o: Opportunity, events: int = 0, last_kind: str | None = None) -> dict:
    return {
        "id": str(o.id), "company": o.company, "aliases": o.aliases or [], "domains": o.domains or [],
        "status": o.status, "deadline": o.deadline.isoformat() if o.deadline else None,
        "events": events, "last_kind": last_kind,
        "created_at": o.created_at.isoformat(), "updated_at": o.updated_at.isoformat(),
    }


@router.get("/opportunities")
def list_opportunities(status: str = Query(default="active", pattern="^(active|closed|all)$"),
                       user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    q = select(Opportunity).where(Opportunity.user_id == user.id)
    if status != "all":
        q = q.where(Opportunity.status == status)
    opps = list(db.scalars(q))
    counts = dict(db.execute(select(OpportunityEvent.opportunity_id, func.count()).group_by(OpportunityEvent.opportunity_id)).all())
    last = {}
    for oid, kind in db.execute(select(OpportunityEvent.opportunity_id, OpportunityEvent.kind).order_by(OpportunityEvent.occurred_at)):
        last[oid] = kind
    now = datetime.now(UTC)
    # upcoming deadlines first (soonest on top), then most recently active
    opps.sort(key=lambda o: (o.deadline is None or o.deadline < now, o.deadline or now, -o.updated_at.timestamp()))
    return [opportunity_json(o, counts.get(o.id, 0), last.get(o.id)) for o in opps]


@router.post("/opportunities", status_code=201)
def create_opportunity(body: OpportunityIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    existing = opp_service.find_by_name(opp_service.active(db, user.id), body.company)
    if existing and opp_service.normalize(existing.company) == opp_service.normalize(body.company):
        raise HTTPException(409, f"an active opportunity for {existing.company} already exists")
    o = Opportunity(user_id=user.id, company=body.company, aliases=_clean_names(body.aliases), domains=[], deadline=body.deadline)
    db.add(o)
    db.commit()
    return opportunity_json(o)


@router.get("/opportunities/{opportunity_id}")
def get_opportunity(opportunity_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    o = _own(db, user, opportunity_id)
    rows = db.execute(
        select(OpportunityEvent, Message, GmailAccount)
        .outerjoin(Message, Message.id == OpportunityEvent.message_id)
        .outerjoin(GmailAccount, GmailAccount.id == Message.account_id)
        .where(OpportunityEvent.opportunity_id == o.id)
        .order_by(OpportunityEvent.occurred_at)
    ).all()
    events = [{
        "id": str(e.id), "kind": e.kind, "matched_by": e.matched_by, "occurred_at": e.occurred_at.isoformat(),
        "deadline": (e.details or {}).get("deadline"), "links": (e.details or {}).get("links") or [],
        "platform": (e.details or {}).get("platform"), "summary": (e.details or {}).get("summary"),
        "message_id": str(m.id) if m else None, "subject": m.subject if m else None,
        "title": (e.details or {}).get("title"), "note": (e.details or {}).get("note"), "remind": bool((e.details or {}).get("remind")),
        "manual": e.message_id is None,
        "sender_name": (m.sender_name or m.sender) if m else None, "account": (a.label or a.email) if a else None,
    } for e, m, a in rows]
    return {**opportunity_json(o, len(events), events[-1]["kind"] if events else None), "timeline": events}


@router.patch("/opportunities/{opportunity_id}")
def update_opportunity(opportunity_id: uuid.UUID, body: OpportunityPatch, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    o = _own(db, user, opportunity_id)
    if body.company is not None:
        o.company = body.company.strip()
    if body.aliases is not None:
        o.aliases = _clean_names(body.aliases)
    if body.status is not None:
        o.status = body.status
    if body.clear_deadline:
        o.deadline = None
    elif body.deadline is not None:
        o.deadline = body.deadline
    o.updated_at = datetime.now(UTC)
    db.commit()
    return opportunity_json(o)


@router.delete("/opportunities/{opportunity_id}", status_code=204)
def delete_opportunity(opportunity_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    """Deletes the timeline only; the mail itself stays."""
    opp = _own(db, user, opportunity_id)
    opp_str = str(opp.id)
    event_msg_ids = list(db.scalars(
        select(OpportunityEvent.message_id).where(
            OpportunityEvent.opportunity_id == opp.id,
            OpportunityEvent.message_id.is_not(None)
        )
    ))
    q = select(Message).where(
        Message.user_id == user.id,
        or_(
            Message.id.in_(event_msg_ids),
            Message.extraction["opportunity_id"].astext == opp_str
        )
    ) if event_msg_ids else select(Message).where(
        Message.user_id == user.id,
        Message.extraction["opportunity_id"].astext == opp_str
    )
    affected_ids = []
    for m in db.scalars(q):
        if m.extraction and m.extraction.get("opportunity_id") == opp_str:
            ext = dict(m.extraction)
            ext.pop("opportunity_id", None)
            m.extraction = ext
            affected_ids.append(m.id)

    db.delete(opp)
    if affected_ids:
        from app import events
        events.publish(db, user.id, "mail", ids=affected_ids)
    db.commit()


class AttachIn(BaseModel):
    message_id: uuid.UUID
    kind: str | None = None


def _own_message(db: Session, user: User, message_id: uuid.UUID) -> Message:
    m = db.get(Message, message_id)
    if m is None or m.user_id != user.id:
        raise HTTPException(404, "message not found")
    return m


def _assign(db: Session, opp: Opportunity, msg: Message, kind: str | None, learn: bool) -> dict:
    if kind is not None and kind not in EVENT_KINDS:
        raise HTTPException(422, f"kind must be one of {', '.join(EVENT_KINDS)}")
    learned = opp_service.assign(db, opp, msg, kind, learn_too=learn)
    db.commit()
    return {"opportunity": opportunity_json(opp), "learned": learned}


@router.post("/opportunities/{opportunity_id}/events", status_code=201)
def attach_message(opportunity_id: uuid.UUID, body: AttachIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Attach a mail by hand (works in AI-off mode too)."""
    return _assign(db, _own(db, user, opportunity_id), _own_message(db, user, body.message_id), body.kind, learn=False)


class CompanyAnswer(BaseModel):
    opportunity_id: uuid.UUID | None = None
    new_company: str | None = Field(default=None, max_length=200)


@router.post("/messages/{message_id}/opportunity")
def answer_which_company(message_id: uuid.UUID, body: CompanyAnswer, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """The "which company?" answer (notification button or app). Learned as an alias or sender domain."""
    msg = _own_message(db, user, message_id)
    if body.opportunity_id:
        opp = _own(db, user, body.opportunity_id)
    elif body.new_company and body.new_company.strip():
        opp = opp_service.find_by_name(opp_service.active(db, user.id), body.new_company)
        if opp is None:
            opp = Opportunity(user_id=user.id, company=body.new_company.strip(), aliases=[], domains=[])
            db.add(opp)
            db.flush()
    else:
        raise HTTPException(422, "give opportunity_id or new_company")
    return _assign(db, opp, msg, None, learn=True)


@router.delete("/messages/{message_id}/opportunity", status_code=204)
def detach(message_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    msg = _own_message(db, user, message_id)
    db.execute(delete(OpportunityEvent).where(OpportunityEvent.message_id == msg.id))
    ext = dict(msg.extraction or {})
    ext.pop("opportunity_id", None)
    ext.pop("matched_by", None)
    msg.extraction = ext
    db.commit()


# ---- sections added by hand (owner, 2026-10-24) -------------------------------------------------
# A timeline is ordered by time, so a section lands in its place by its date and time. With
# "remind", a section in the future also counts as a deadline: it can become the company's next
# deadline and gets the usual reminders (24 h and 2 h before).

class SectionIn(BaseModel):
    kind: str = Field(default="update", pattern="^(" + "|".join(EVENT_KINDS) + ")$")
    title: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    at: datetime
    remind: bool = False

    @field_validator("at")
    @classmethod
    def aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("the date and time need a time zone")
        return v


class SectionPatch(BaseModel):
    kind: str | None = Field(default=None, pattern="^(" + "|".join(EVENT_KINDS) + ")$")
    title: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    at: datetime | None = None
    remind: bool | None = None

    @field_validator("at")
    @classmethod
    def aware(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            raise ValueError("the date and time need a time zone")
        return v


def _own_event(db: Session, opp: Opportunity, event_id: uuid.UUID) -> OpportunityEvent:
    e = db.get(OpportunityEvent, event_id)
    if e is None or e.opportunity_id != opp.id:
        raise HTTPException(404, "not on this timeline")
    return e


def _section_reminders(db: Session, opp: Opportunity, e: OpportunityEvent) -> None:
    from app import todos as todo_service
    from app.models import Reminder

    db.execute(delete(Reminder).where(Reminder.user_id == opp.user_id, Reminder.dedupe_key.like(f"section:{e.id}:%"),
                                      Reminder.sent_at.is_(None)))
    details = e.details or {}
    if details.get("remind") and e.occurred_at > datetime.now(UTC):
        title = f"{opp.company}: {details.get('title') or e.kind}"
        todo_service.schedule_deadline(db, opp.user_id, f"section:{e.id}:{e.occurred_at.isoformat()}", title, e.occurred_at,
                                       opportunity_id=opp.id)


def _section_details(e_details: dict | None, title: str, note: str | None, at: datetime, remind: bool) -> dict:
    d = dict(e_details or {})
    d.update({"title": title.strip(), "note": (note or "").strip() or None, "remind": remind})
    if remind:
        d["deadline"] = at.isoformat()
    else:
        d.pop("deadline", None)
    return d


@router.post("/opportunities/{opportunity_id}/sections", status_code=201)
def add_section(opportunity_id: uuid.UUID, body: SectionIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    o = _own(db, user, opportunity_id)
    e = OpportunityEvent(opportunity_id=o.id, kind=body.kind, matched_by="user", occurred_at=body.at,
                         details=_section_details(None, body.title, body.note, body.at, body.remind))
    db.add(e)
    db.flush()
    _section_reminders(db, o, e)
    opp_service.refresh_deadline(db, o)
    o.updated_at = datetime.now(UTC)
    db.commit()
    return get_opportunity(o.id, user, db)


@router.patch("/opportunities/{opportunity_id}/events/{event_id}")
def edit_event(opportunity_id: uuid.UUID, event_id: uuid.UUID, body: SectionPatch, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Edit a section; for a mail on the timeline, only its kind (what stage it is) can change."""
    o = _own(db, user, opportunity_id)
    e = _own_event(db, o, event_id)
    if body.kind is not None:
        e.kind = body.kind
    if e.message_id is None:
        d = e.details or {}
        if body.at is not None:
            e.occurred_at = body.at
        e.details = _section_details(d, body.title if body.title is not None else d.get("title") or e.kind,
                                     body.note if body.note is not None else d.get("note"), e.occurred_at,
                                     body.remind if body.remind is not None else bool(d.get("remind")))
        _section_reminders(db, o, e)
    elif body.title is not None or body.at is not None or body.note is not None:
        raise HTTPException(422, "a mail on the timeline keeps its own subject and time; only its stage can change")
    opp_service.refresh_deadline(db, o)
    o.updated_at = datetime.now(UTC)
    db.commit()
    return get_opportunity(o.id, user, db)


@router.delete("/opportunities/{opportunity_id}/events/{event_id}")
def remove_event(opportunity_id: uuid.UUID, event_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Removes a section, or takes a mail off this timeline (the mail itself stays)."""
    from app.models import Reminder

    o = _own(db, user, opportunity_id)
    e = _own_event(db, o, event_id)
    if e.message_id is not None:
        msg = db.get(Message, e.message_id)
        ext = dict(msg.extraction or {})
        ext.pop("opportunity_id", None)
        ext.pop("matched_by", None)
        msg.extraction = ext
    db.execute(delete(Reminder).where(Reminder.user_id == o.user_id, Reminder.dedupe_key.like(f"section:{e.id}:%"), Reminder.sent_at.is_(None)))
    db.delete(e)
    db.flush()
    if o.deadline is not None:
        o.deadline = None
        opp_service.refresh_deadline(db, o)
    o.updated_at = datetime.now(UTC)
    db.commit()
    return get_opportunity(o.id, user, db)

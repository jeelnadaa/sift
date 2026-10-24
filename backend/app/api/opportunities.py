import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
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
    db.delete(_own(db, user, opportunity_id))
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
    db.execute(delete(OpportunityEvent).where(OpportunityEvent.message_id == msg.id))  # move, never duplicate
    ext = dict(msg.extraction or {})
    kind = kind or opp_service.EVENT_KIND.get(ext.get("category") or "") or "update"
    details = {k: ext.get(k) for k in ("deadline", "links", "platform", "summary")}
    opp_service.attach(db, opp, msg, kind, details, "user")
    learned = opp_service.learn(opp, msg, ext) if learn else None
    ext.pop("company_question", None)
    ext["opportunity_id"], ext["matched_by"] = str(opp.id), "user"
    msg.extraction = ext
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

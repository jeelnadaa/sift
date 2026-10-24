"""Search API (brief section 19): search, query chips, suggestions, recent searches, and
reading conversations Sift never stored (search results from older mail)."""
import csv
import io
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.messages import message_json, thread_json
from app.db import get_db
from app.models import Folder, GmailAccount, Message, SavedSearch, Setting, Tag, User
from app import jobs
from app.search import engine, semantic
from app.search.query import QueryError, parse
from app.security import current_user

router = APIRouter(prefix="/api/v1")
RECENT_LIMIT = 10


def _remember(db: Session, user_id: uuid.UUID, q: str) -> None:
    row = db.scalar(select(Setting).where(Setting.user_id == user_id, Setting.account_id.is_(None)))
    if row is None:
        row = Setting(user_id=user_id, account_id=None, data={})
        db.add(row)
    recent = [x for x in (row.data or {}).get("recent_searches", []) if x != q]
    row.data = {**(row.data or {}), "recent_searches": [q, *recent][:RECENT_LIMIT]}


def _search(db: Session, user: User, q: str, cursor: str | None, limit: int):
    try:
        return engine.run(db, user.id, q, cursor, limit)
    except engine.SearchError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/search")
def search(q: str = Query(min_length=1, max_length=1000), cursor: str | None = Query(default=None, max_length=20000),
           limit: int = Query(default=30, ge=1, le=100), user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Gmail syntax plus Sift filters, across accounts; one row per conversation, newest first."""
    hits, nxt, total, failed, parsed = _search(db, user, q, cursor, limit)
    if not cursor:
        _remember(db, user.id, q.strip())
    db.commit()
    return {
        "items": [engine.hit_json(h, message_json) for h in hits], "next_cursor": nxt,
        "total": total, "estimated": parsed.has_gmail, "failed_accounts": failed,
        "gmail_query": parsed.gmail, "words": parsed.words,
        "chips": [c.__dict__ for c in parsed.chips],
    }


class ParseIn(BaseModel):
    q: str = Field(max_length=1000)


@router.post("/search/parse")
def parse_query(body: ParseIn, user: User = Depends(current_user)) -> dict:
    """The query as chips (and the Gmail part to copy into Gmail). Chips join back into the query."""
    try:
        p = parse(body.q)
    except QueryError as exc:
        return {"error": str(exc), "chips": [], "gmail_query": ""}
    return {"error": None, "chips": [c.__dict__ for c in p.chips], "gmail_query": p.gmail}


@router.get("/search/suggest")
def suggest(q: str = Query(default="", max_length=200), user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Live suggestions: senders, folders, tags, saved and recent searches matching what's typed."""
    term = q.strip().lower()
    like = f"%{term.replace('%', '').replace('_', '')}%"
    senders = db.execute(
        select(Message.sender, func.max(Message.sender_name), func.count()).where(
            Message.user_id == user.id, Message.sender.is_not(None),
            (func.lower(Message.sender).like(like)) | (func.lower(Message.sender_name).like(like)))
        .group_by(Message.sender).order_by(func.count().desc()).limit(6)).all()
    folders = db.scalars(select(Folder.name).where(Folder.user_id == user.id, func.lower(Folder.name).like(like)).order_by(Folder.name).limit(6))
    tags = db.scalars(select(Tag.name).where(Tag.user_id == user.id, func.lower(Tag.name).like(like)).order_by(Tag.name).limit(6))
    saved = db.scalars(select(SavedSearch).where(SavedSearch.user_id == user.id, func.lower(SavedSearch.name).like(like)).order_by(SavedSearch.pinned.desc(), SavedSearch.name).limit(6))
    row = db.scalar(select(Setting).where(Setting.user_id == user.id, Setting.account_id.is_(None)))
    recent = [r for r in (row.data if row else {}).get("recent_searches", []) if term in r.lower()][:6]

    def quote(v: str) -> str:
        return f'"{v}"' if any(c in v for c in ' (){}"') else v

    return {
        "senders": [{"label": n or s, "detail": s, "count": c, "query": f"from:{s}"} for s, n, c in senders],
        "folders": [{"label": f, "query": f"folder:{quote(f)}"} for f in folders],
        "tags": [{"label": t, "query": f"tag:{quote(t)}"} for t in tags],
        "saved": [{"label": s.name, "query": s.query, "id": str(s.id)} for s in saved],
        "recent": [{"label": r, "query": r} for r in recent],
    }


@router.delete("/search/recent", status_code=204)
def clear_recent(user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    row = db.scalar(select(Setting).where(Setting.user_id == user.id, Setting.account_id.is_(None)))
    if row is not None:
        row.data = {k: v for k, v in (row.data or {}).items() if k != "recent_searches"}
        db.commit()


@router.get("/search/export")
def export_csv(q: str = Query(min_length=1, max_length=1000), user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    """The results (up to 500 conversations) as CSV: date, account, sender, subject, Sift priority, in Sift."""
    rows, cursor = [], None
    while len(rows) < 500:
        hits, cursor, _, _, _ = _search(db, user, q, cursor, 100)
        rows += [engine.hit_json(h, message_json) for h in hits]
        if not cursor:
            break
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "account", "sender", "sender_name", "subject", "priority", "category", "in_sift"])
    for r in rows[:500]:
        # neutralize spreadsheet formulas in mail-controlled fields
        safe = [("'" + v) if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v for v in
                (r.get("received_at"), r.get("account"), r.get("sender"), r.get("sender_name"), r.get("subject"), r.get("priority"), r.get("category"))]
        w.writerow([*safe, "yes" if r.get("id") else "no"])
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="sift-search.csv"', "X-Content-Type-Options": "nosniff"})


@router.get("/accounts/{account_id}/threads/{thread_id}")
def account_thread(account_id: uuid.UUID, thread_id: str, images: bool = False,
                   user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Read a conversation Sift never stored (e.g. older mail found by search)."""
    account = db.get(GmailAccount, account_id)
    if account is None or account.user_id != user.id:
        raise HTTPException(404, "account not found")
    if not thread_id.isalnum() or len(thread_id) > 64:
        raise HTTPException(422, "bad conversation id")
    return thread_json(db, user, account, thread_id, images)


@router.get("/search/semantic")
def semantic_search(q: str = Query(min_length=1, max_length=1000), offset: int = Query(default=0, ge=0, le=1000),
                    limit: int = Query(default=30, ge=1, le=100), user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Search by meaning over indexed mail (needs the user's AI key). Sift filters in the
    query still apply; Gmail operators are treated as words."""
    try:
        p = parse(engine.expand_saved(db, user.id, q))
        accounts = engine._accounts(db, user.id)
        conds = engine.conditions(db, user.id, p, accounts)
    except (QueryError, engine.SearchError) as exc:
        raise HTTPException(422, str(exc)) from exc
    text = " ".join(c.text for c in p.chips if c.kind == "gmail").strip()
    if not text:
        raise HTTPException(422, "type what you're looking for")
    chosen = [a.id for a in engine.selected_accounts(p, accounts)]
    res = semantic.search(db, user.id, text, conds, chosen, offset, limit)
    db.commit()  # token usage
    if res is None:
        raise HTTPException(409, "Search by meaning needs a working AI key (Settings), and today's token cap not reached")
    hits, total = res
    by_id = {a.id: a for a in accounts}
    items = [{**message_json(m, by_id.get(m.account_id)), "source": "sift", "score": round(score, 3)} for m, score in hits]
    nxt = offset + limit if offset + limit < total else None
    return {"items": items, "total": total, "next_offset": nxt, "status": semantic.status(db, user.id)}


@router.get("/search/semantic/status")
def semantic_status(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return semantic.status(db, user.id)


@router.post("/search/semantic/index", status_code=202)
def semantic_index(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Index stored mail from the last 90 days (once; already-indexed mail is skipped)."""
    from app.llm import service as llm
    if not llm.ai_enabled(db, user.id):
        raise HTTPException(409, "Add a working AI key in Settings first")
    jobs.enqueue_sync("semantic_backfill", {"user_id": str(user.id)}, dedupe_key=f"semantic:{user.id}")
    return semantic.status(db, user.id)


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)


@router.post("/search/from-text")
def from_text(body: TextIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Plain English -> the same query the chips use ("mails from Walmart last week" ->
    from:walmart newer_than:7d). Needs the user's AI key; the result is checked by the parser."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app import user_settings
    from app.llm import service as llm
    from app.llm.base import LlmError
    from app.models import Opportunity

    known = {
        "folders": list(db.scalars(select(Folder.name).where(Folder.user_id == user.id, Folder.saved_search_id.is_(None)))),
        "tags": list(db.scalars(select(Tag.name).where(Tag.user_id == user.id))),
        "companies": list(db.scalars(select(Opportunity.company).where(Opportunity.user_id == user.id))),
    }
    today = datetime.now(ZoneInfo(user_settings.get(db, user.id)["timezone"])).strftime("%Y-%m-%d (%A)")
    try:
        out = llm.search_from_text(db, user.id, body.text, today, known)
    except LlmError as exc:
        db.commit()
        raise HTTPException(409 if "API key" in str(exc) or "cap" in str(exc) else 422, str(exc)) from exc
    db.commit()
    try:
        p = parse(out["query"])
    except QueryError as exc:
        raise HTTPException(422, "Couldn't turn that into a valid search; try different words") from exc
    return {**out, "chips": [c.__dict__ for c in p.chips], "gmail_query": p.gmail}


class TagIn(BaseModel):
    message_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=80)


@router.post("/search/tag")
def tag_results(body: TagIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Bulk action on search results: tag the chosen mails (mail Sift stored only)."""
    from sqlalchemy.dialects.postgresql import insert

    from app.models import MailTag
    ids = list(db.scalars(select(Message.id).where(Message.user_id == user.id, Message.id.in_(body.message_ids))))
    if len(ids) != len(set(body.message_ids)):
        raise HTTPException(404, "message not found")
    name = " ".join(body.name.split())
    tag = db.scalar(select(Tag).where(Tag.user_id == user.id, Tag.name == name))
    if tag is None:
        tag = Tag(user_id=user.id, name=name)
        db.add(tag)
        db.flush()
    db.execute(insert(MailTag).values([{"tag_id": tag.id, "message_id": i} for i in ids]).on_conflict_do_nothing())
    db.commit()
    return {"tagged": len(ids), "tag": name}

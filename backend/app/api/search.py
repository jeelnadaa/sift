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
from app.search import engine
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

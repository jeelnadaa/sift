"""Semantic search: find mail by meaning ("job offers I haven't answered" finds an
"Offer letter: Software Engineer" mail), Phase 3b, brought forward from Phase 5 by the owner.

- What is embedded: sender name and domain, subject, Gmail's preview text and Sift's own
  summary, with personal identifiers redacted. Never the body.
- With the user's own key only, behind ai_enabled() and the daily token cap (AI-off: the
  feature is off and search keeps working by keywords).
- New mail is embedded right after it is processed (after its notification). On top, one pass
  over stored mail from the last BACKFILL_DAYS (owner's choice, 2026-10-24).
- Search: the query is embedded once, compared (cosine) with the user's stored vectors in
  memory (numpy; tens of thousands of mails is a few milliseconds), best matches first, with
  Sift filters applied in SQL.
"""
import logging
import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.llm import service as llm
from app.models import Message, MessageEmbedding
from app.redact import redact

log = logging.getLogger(__name__)
BACKFILL_DAYS = 90
# Silenced and ignored mail is never sent anywhere: quieting a sender must not cost tokens
# (brief section 9). It stays findable by keyword search.
INDEXED_STATUSES = ("processed",)
# Calibrated on real mail (2026-10-24, gemini-embedding-001 at 768 dims): unrelated mail scores up to
# ~0.52, relevant mail 0.58-0.68 with a clear drop after it. Keep matches above the floor and
# close to the best one.
MIN_SCORE = 0.56
RELATIVE_WINDOW = 0.08
MAX_RESULTS = 200


def doc_text(m: Message) -> str:
    ext = m.extraction or {}
    who = " ".join(x for x in (m.sender_name, (m.authenticated_domain or (m.sender or "").split("@")[-1])) if x)
    parts = [f"from: {who}", f"subject: {m.subject or ''}", m.snippet or ""]
    if ext.get("summary"):
        parts.append(ext["summary"])
    if ext.get("company"):
        parts.append(f"company: {ext['company']}")
    if m.category and m.category != "other":
        parts.append(f"category: {m.category.replace('_', ' ')}")
    return redact(" | ".join(p for p in parts if p))[:2000]


def _pack(v: list[float]) -> bytes:
    a = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(a))
    return (a / n if n else a).astype(np.float32).tobytes()  # stored normalized: cosine = dot product


def index(db: Session, user_id: uuid.UUID, messages: list[Message], purpose: str = "embed") -> int:
    """Embed messages that have no vector yet. Returns how many were indexed (0 when AI is off)."""
    have = set(db.scalars(select(MessageEmbedding.message_id).where(MessageEmbedding.message_id.in_([m.id for m in messages]))))
    todo = [m for m in messages if m.id not in have and m.status in INDEXED_STATUSES]
    if not todo:
        return 0
    vectors = llm.embed(db, user_id, [doc_text(m) for m in todo], "RETRIEVAL_DOCUMENT", purpose)
    if vectors is None:
        return 0
    rows = [{"message_id": m.id, "user_id": user_id, "model": llm.EMBED_MODEL, "dims": llm.EMBED_DIMS, "vector": _pack(v)}
            for m, v in zip(todo, vectors, strict=True)]
    db.execute(insert(MessageEmbedding).values(rows).on_conflict_do_nothing(index_elements=["message_id"]))
    return len(rows)


def index_new(db: Session, msg: Message) -> None:
    """Pipeline hook, after the notification is out. Never raises."""
    if msg.status not in INDEXED_STATUSES or not llm.ai_enabled(db, msg.user_id):
        return
    try:
        index(db, msg.user_id, [msg])
        db.commit()
    except Exception:
        db.rollback()
        log.exception("semantic indexing failed for message %s", msg.id)


def backfill(db: Session, user_id: uuid.UUID, batch: int = 200) -> int:
    """One pass over stored mail from the last BACKFILL_DAYS that has no vector. Stops at the cap."""
    since = datetime.now(UTC) - timedelta(days=BACKFILL_DAYS)
    done = 0
    while llm.ai_enabled(db, user_id) and llm.under_cap(db, user_id):
        missing = list(db.scalars(
            select(Message).where(Message.user_id == user_id, Message.status.in_(INDEXED_STATUSES), Message.received_at >= since,
                                  ~select(MessageEmbedding.message_id).where(MessageEmbedding.message_id == Message.id).exists())
            .order_by(Message.received_at.desc()).limit(batch)))
        if not missing:
            break
        n = index(db, user_id, missing, purpose="embed_backfill")
        db.commit()
        if n == 0:
            break
        done += n
    return done


def status(db: Session, user_id: uuid.UUID) -> dict:
    since = datetime.now(UTC) - timedelta(days=BACKFILL_DAYS)
    indexed = db.scalar(select(func.count()).select_from(MessageEmbedding).where(MessageEmbedding.user_id == user_id)) or 0
    recent = db.scalar(select(func.count()).select_from(Message).where(
        Message.user_id == user_id, Message.status.in_(INDEXED_STATUSES), Message.received_at >= since)) or 0
    return {"ai_enabled": llm.ai_enabled(db, user_id), "indexed": indexed, "recent_total": recent, "backfill_days": BACKFILL_DAYS}


def search(db: Session, user_id: uuid.UUID, text: str, conds: list, account_ids: list[uuid.UUID], offset: int, limit: int):
    """Returns ([(message, score)], total above the threshold) or None when AI is off / cap reached."""
    q = llm.embed(db, user_id, [redact(text)[:2000]], "RETRIEVAL_QUERY", purpose="embed_query")
    if q is None:
        return None
    qv = np.frombuffer(_pack(q[0]), dtype=np.float32)
    rows = db.execute(
        select(MessageEmbedding.message_id, MessageEmbedding.vector).join(Message, Message.id == MessageEmbedding.message_id)
        .where(MessageEmbedding.user_id == user_id, MessageEmbedding.model == llm.EMBED_MODEL, MessageEmbedding.dims == llm.EMBED_DIMS,
               Message.status.in_(INDEXED_STATUSES), Message.account_id.in_(account_ids), *conds)).all()
    if not rows:
        return [], 0
    ids = [r[0] for r in rows]
    matrix = np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32).reshape(len(rows), llm.EMBED_DIMS)
    scores = matrix @ qv
    best = float(scores.max())
    cutoff = max(MIN_SCORE, best - RELATIVE_WINDOW)
    order = [i for i in np.argsort(-scores) if scores[i] >= cutoff][:MAX_RESULTS]
    page = order[offset:offset + limit]
    by_id = {m.id: m for m in db.scalars(select(Message).where(Message.id.in_([ids[i] for i in page])))}
    return [(by_id[ids[i]], float(scores[i])) for i in page if ids[i] in by_id], len(order)

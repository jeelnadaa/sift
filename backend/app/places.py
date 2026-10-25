"""Places: the user's own groups and folders with criteria, and new mail going to every one it fits.

A place is a **custom group** (Groups → New group) or a **folder with criteria** (a folder's AI card:
"mail matching a search" and/or "mail described as"). Each place can have:
- a search (`query`, Sift search syntax: `from:nvidia`, `folder:Placements`, `type:assessment_link`...),
  checked by Sift itself for free;
- a description (`instruction`, plain words: "internship offers"), checked by the AI.
With both, mail must match the search and fit the description. A mail goes to **every** place it
fits, next to whatever else happens to it (company timeline, automatic group, other folders).

Cost: descriptions ride along with the AI's one reading of each new mail (a short list "p1: ...",
and the answer is a list of keys), so routing never adds an AI call. Mail the AI doesn't read (AI
off, settled by a rule, too old) is routed by searches only. Filling a place with mail that is
already in Sift is an AI task ("fill"), batched 25 mails per small call (folder_ai.run_fill).
Never raises into the pipeline.
"""
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Folder, FolderItem, GroupMember, MailGroup, Message

log = logging.getLogger(__name__)
MAX_PLACES = 25  # descriptions sent with each mail (each ~20 tokens)
MAX_INSTRUCTION = 200


@dataclass
class Place:
    key: str  # p1, p2... (only for places with a description)
    kind: str  # group | folder
    id: uuid.UUID
    name: str
    query: str | None
    instruction: str | None


def load(db: Session, user_id: uuid.UUID) -> list[Place]:
    out: list[Place] = []
    for g in db.scalars(select(MailGroup).where(MailGroup.user_id == user_id, MailGroup.kind == "custom").order_by(MailGroup.created_at)):
        if g.query or g.instruction:
            out.append(Place("", "group", g.id, g.title, g.query, g.instruction))
    for f in db.scalars(select(Folder).where(Folder.user_id == user_id, Folder.saved_search_id.is_(None)).order_by(Folder.position)):
        rule = f.ai_rule or {}
        if rule.get("query") or rule.get("describe"):
            out.append(Place("", "folder", f.id, f.name, rule.get("query"), rule.get("describe")))
    n = 0
    for p in out:
        if p.instruction and n < MAX_PLACES:
            n += 1
            p.key = f"p{n}"
    return out


def prompt_block(places: list[Place]) -> tuple[str | None, list[str]]:
    """The lines added to the AI's reading of a new mail, and the keys it may answer."""
    described = [p for p in places if p.key]
    if not described:
        return None, []
    lines = [f'{p.key}: {p.kind} "{" ".join(p.name.split())[:60]}": {" ".join((p.instruction or "").split())[:MAX_INSTRUCTION]}' for p in described]
    return "\n".join(lines), [p.key for p in described]


def query_matches(db: Session, user_id: uuid.UUID, query: str, msg: Message) -> bool:
    from app.search.engine import SearchError, message_matches
    try:
        return message_matches(db, user_id, query, msg)
    except SearchError:
        return False  # a search that no longer works (a deleted folder) matches nothing


def fits(db: Session, p: Place, msg: Message, picked: set[str] | None) -> bool:
    """Search (if any) must match; description (if any) must have been picked by the AI."""
    if p.query and not query_matches(db, msg.user_id, p.query, msg):
        return False
    if p.instruction:
        return picked is not None and p.key in picked
    return bool(p.query)


def add(db: Session, p_kind: str, p_id: uuid.UUID, msg: Message, by: str = "system") -> bool:
    """Puts the mail (its conversation, for folders) in the place. False when it was already
    there, or the user took it out of that group before."""
    if p_kind == "group":
        existing = db.get(GroupMember, {"group_id": p_id, "message_id": msg.id})
        if existing is not None:
            return False
        db.add(GroupMember(group_id=p_id, message_id=msg.id, account_id=msg.account_id, added_by=by))
        g = db.get(MailGroup, p_id)
        if msg.received_at and (g.last_activity_at is None or msg.received_at > g.last_activity_at):
            g.last_activity_at = msg.received_at
        return True
    done = db.execute(insert(FolderItem).values(folder_id=p_id, account_id=msg.account_id, thread_id=msg.thread_id)
                      .on_conflict_do_nothing().returning(FolderItem.folder_id)).first() is not None
    if done:
        from app import folder_ai
        f = db.get(Folder, p_id)
        if f is not None and f.auto_sort:
            folder_ai.sort_if_needed(db, f, msg)
    return done


def route(db: Session, msg: Message) -> list[str]:
    """Pipeline hook after classification: every place this mail fits. Returns their names."""
    if msg.status != "processed":
        return []
    try:
        places = load(db, msg.user_id)
        if not places:
            return []
        ext = msg.extraction or {}
        picked = set(ext.get("places") or []) if ext.get("source") == "llm" and "places" in ext else None
        names = []
        with db.begin_nested():
            for p in places:
                if fits(db, p, msg, picked) and add(db, p.kind, p.id, msg):
                    names.append(p.name)
            db.flush()
        return names
    except Exception:  # noqa: BLE001  (routing must never cost the mail its notification)
        log.exception("routing failed for message %s", msg.id)
        return []


def check_query(db: Session, user_id: uuid.UUID, query: str | None) -> str | None:
    """Validates a place's search; returns it cleaned, or raises ValueError with the reason."""
    from app.search.engine import SearchError, stored_matches
    q = " ".join((query or "").split())[:500]
    if not q:
        return None
    try:
        stored_matches(db, user_id, q, 1)
    except SearchError as exc:
        raise ValueError(f"search: {exc}") from exc
    return q


def check_instruction(text: str | None) -> str | None:
    t = " ".join((text or "").split())
    if len(t) > MAX_INSTRUCTION:
        raise ValueError(f"keep the description under {MAX_INSTRUCTION} characters")
    return t or None

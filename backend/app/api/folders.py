"""Folders API (brief sections 13 and 18)."""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import folders, rule_tools
from app.api.messages import message_json
from app.db import get_db
from app.models import GmailAccount, Message, User
from app.security import current_user

router = APIRouter(prefix="/api/v1/folders")
COLOR = r"^#[0-9a-fA-F]{6}$"


def _folder(db: Session, user: User, folder_id: uuid.UUID):
    try:
        return folders.own(db, user.id, folder_id)
    except folders.FolderError as exc:
        raise HTTPException(404, str(exc)) from exc


def _run(db: Session, fn, *args, **kwargs):
    """Run a folder operation, commit, and turn FolderError into a 422 with its message."""
    try:
        out = fn(*args, **kwargs)
    except folders.FolderError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    return out


def _messages(db: Session, user: User, ids: list[uuid.UUID]) -> list[Message]:
    rows = list(db.scalars(select(Message).where(Message.user_id == user.id, Message.id.in_(ids))))
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "message not found")
    return rows


@router.get("")
def tree(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return folders.tree_json(db, user.id)


class FolderIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parent_id: uuid.UUID | None = None
    color: str | None = Field(default=None, pattern=COLOR)
    icon: str | None = Field(default=None, max_length=40)


@router.post("", status_code=201)
def create(body: FolderIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    f = _run(db, folders.create, db, user.id, body.name, body.parent_id, body.color, body.icon)
    return folders.folder_json(f)


class FolderPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    color: str | None = Field(default=None, pattern=COLOR)
    icon: str | None = Field(default=None, max_length=40)
    pinned: bool | None = None
    notify_mode: str | None = Field(default=None, pattern="^(default|always|mute)$")
    clear_color: bool = False
    clear_icon: bool = False


@router.patch("/{folder_id}")
def edit(folder_id: uuid.UUID, body: FolderPatch, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    f = _folder(db, user, folder_id)
    clear = tuple(k for k, on in (("color", body.clear_color), ("icon", body.clear_icon)) if on)
    _run(db, folders.edit, f, name=body.name, color=body.color, icon=body.icon, pinned=body.pinned,
         notify_mode=body.notify_mode, clear=clear)
    return folders.folder_json(f)


class MoveIn(BaseModel):
    parent_id: uuid.UUID | None = None  # None = top level
    position: int | None = Field(default=None, ge=0)


@router.post("/{folder_id}/move")
def move(folder_id: uuid.UUID, body: MoveIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    f = _folder(db, user, folder_id)
    _run(db, folders.move, db, user.id, f, body.parent_id, body.position)
    return folders.tree_json(db, user.id)


class ReorderIn(BaseModel):
    parent_id: uuid.UUID | None = None
    ids: list[uuid.UUID] = Field(max_length=500)


@router.post("/reorder")
def reorder(body: ReorderIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    _run(db, folders.reorder, db, user.id, body.parent_id, body.ids)
    return folders.tree_json(db, user.id)


class MergeIn(BaseModel):
    target_id: uuid.UUID


@router.post("/{folder_id}/merge")
def merge(folder_id: uuid.UUID, body: MergeIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    source, target = _folder(db, user, folder_id), _folder(db, user, body.target_id)
    if source.id == target.id:
        raise HTTPException(422, "pick a different folder to merge into")
    return _run(db, folders.merge, db, user.id, source, target)


@router.delete("/{folder_id}")
def remove(folder_id: uuid.UUID, subfolders: str = Query(default="move_up", pattern="^(delete|move_up)$"),
           user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Removes the folder and its filing only; mail is never deleted."""
    f = _folder(db, user, folder_id)
    return _run(db, folders.remove, db, user.id, f, subfolders)


@router.get("/{folder_id}/threads")
def threads(folder_id: uuid.UUID, include_subfolders: bool = False, q: str | None = Query(default=None, max_length=200),
            before: datetime | None = None, limit: int = Query(default=50, ge=1, le=200),
            user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    f = _folder(db, user, folder_id)
    rows, path = folders.thread_rows(db, user.id, f, include_subfolders, q, before, limit)
    counts = folders.mark_thread_counts(db, user.id, rows)
    accounts = {a.id: a for a in db.scalars(select(GmailAccount).where(GmailAccount.user_id == user.id))}
    items = []
    for m in rows:
        n, unread = counts.get((m.account_id, m.thread_id), (1, 0))
        items.append({**message_json(m, accounts.get(m.account_id)), "thread_count": n, "thread_unread": unread})
    return {
        "folder": folders.folder_json(f),
        "path": [{"id": str(p.id), "name": p.name} for p in path],
        "items": items,
        "next_before": rows[-1].received_at.isoformat() if len(rows) == limit and rows[-1].received_at else None,
    }


class FileIn(BaseModel):
    message_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)  # each files its whole thread


@router.post("/last-used/threads")
def file_last_used(body: FileIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """One-tap "Move to last used folder"."""
    f = folders.last_used(db, user.id)
    if f is None:
        raise HTTPException(409, "no folder used yet")
    return _file(db, user, f, body)


@router.post("/{folder_id}/threads")
def file_mail(folder_id: uuid.UUID, body: FileIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return _file(db, user, _folder(db, user, folder_id), body)


def _file(db: Session, user: User, f, body: FileIn) -> dict:
    msgs = _messages(db, user, body.message_ids)

    def run():
        threads = {(m.account_id, m.thread_id) for m in msgs}
        return sum(folders.file_thread(db, user.id, f, a, t) for a, t in threads)

    return {"filed": _run(db, run), "folder_id": str(f.id)}


@router.post("/{folder_id}/threads/remove")
def unfile_mail(folder_id: uuid.UUID, body: FileIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    f = _folder(db, user, folder_id)
    msgs = _messages(db, user, body.message_ids)
    removed = sum(folders.unfile_thread(db, f, a, t) for a, t in {(m.account_id, m.thread_id) for m in msgs})
    db.commit()
    return {"removed": removed}


@router.get("/for-message/{message_id}")
def for_message(message_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    m = _messages(db, user, [message_id])[0]
    return [folders.folder_json(f) for f in folders.folders_for_thread(db, m.account_id, m.thread_id) if f.user_id == user.id]


class LikeThisHereIn(BaseModel):
    message_id: uuid.UUID
    save: bool = False


@router.post("/{folder_id}/rule-from-message")
def rule_from_message(folder_id: uuid.UUID, body: LikeThisHereIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """"File mail like this here": same verified sender and subject template, classified as
    usual (notifications unchanged), filed into this folder."""
    f = _folder(db, user, folder_id)
    if f.saved_search_id is not None:
        raise HTTPException(422, "rules can't file mail into a smart folder")
    m = _messages(db, user, [body.message_id])[0]
    try:
        draft = rule_tools.like_this(m, "llm")
    except rule_tools.RuleToolError as exc:
        raise HTTPException(422, str(exc)) from exc
    who = m.sender_name or m.authenticated_domain or m.sender
    draft["name"] = f"File in {f.name}: {who}"[:200]
    draft["action"] = {"type": "llm", "folder_id": str(f.id)}
    result = {"draft": draft, "preview": rule_tools.preview(db, user.id, draft["conditions"])}
    if body.save:
        rule = rule_tools.save_rule(db, user.id, draft, origin="one_tap")
        folders.file_thread(db, user.id, f, m.account_id, m.thread_id)
        db.commit()
        result["rule_id"] = str(rule.id)
    return result

"""Saved searches (brief section 19): name a query, pin it, get notified of new matches, or show
it as a smart folder in the folder tree (it updates itself; nothing can be filed into it)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import folders
from app.db import get_db
from app.models import Folder, SavedSearch, User
from app.search.query import QueryError, parse
from app.security import current_user

router = APIRouter(prefix="/api/v1/saved-searches")
MAX_SAVED = 100


def saved_json(s: SavedSearch, folder: Folder | None) -> dict:
    return {"id": str(s.id), "name": s.name, "query": s.query, "pinned": s.pinned, "notify": s.notify,
            "smart_folder_id": str(folder.id) if folder else None, "created_at": s.created_at.isoformat()}


def _folder_of(db: Session, s: SavedSearch) -> Folder | None:
    return db.scalar(select(Folder).where(Folder.saved_search_id == s.id))


def _own(db: Session, user: User, sid: uuid.UUID) -> SavedSearch:
    s = db.get(SavedSearch, sid)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "saved search not found")
    return s


def _check(db: Session, user: User, name: str, query: str, exclude: uuid.UUID | None = None) -> tuple[str, str]:
    name, query = " ".join(name.split()), " ".join(query.split())
    if not name or not query:
        raise HTTPException(422, "give the search a name and a query")
    try:
        p = parse(query)
    except QueryError as exc:
        raise HTTPException(422, str(exc)) from exc
    if any(f.key == "saved" for f in p.filters):
        raise HTTPException(422, "a saved search can't use another saved search")
    clash = db.scalar(select(SavedSearch.id).where(SavedSearch.user_id == user.id, func.lower(SavedSearch.name) == name.lower(),
                                                   SavedSearch.id != (exclude or uuid.uuid4())))
    if clash:
        raise HTTPException(409, f"you already have a saved search called {name}")
    return name, query


def _set_smart_folder(db: Session, user: User, s: SavedSearch, on: bool) -> None:
    f = _folder_of(db, s)
    if on and f is None:
        tree = folders.load_tree(db, user.id)
        db.add(Folder(user_id=user.id, name=s.name[:120], saved_search_id=s.id, icon="search",
                      position=max((x.position for x in tree.children(None)), default=-1) + 1))
    elif not on and f is not None:
        db.delete(f)
    elif f is not None:
        f.name = s.name[:120]


@router.get("")
def list_saved(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(SavedSearch).where(SavedSearch.user_id == user.id).order_by(SavedSearch.pinned.desc(), SavedSearch.name))
    return [saved_json(s, _folder_of(db, s)) for s in rows]


class SavedIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    query: str = Field(min_length=1, max_length=1000)
    pinned: bool = False
    notify: bool = False
    smart_folder: bool = False


@router.post("", status_code=201)
def create(body: SavedIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if (db.scalar(select(func.count()).select_from(SavedSearch).where(SavedSearch.user_id == user.id)) or 0) >= MAX_SAVED:
        raise HTTPException(422, f"you can keep {MAX_SAVED} saved searches at most")
    name, query = _check(db, user, body.name, body.query)
    s = SavedSearch(user_id=user.id, name=name, query=query, pinned=body.pinned, notify=body.notify)
    db.add(s)
    db.flush()
    _set_smart_folder(db, user, s, body.smart_folder)
    db.commit()
    return saved_json(s, _folder_of(db, s))


class SavedPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    query: str | None = Field(default=None, min_length=1, max_length=1000)
    pinned: bool | None = None
    notify: bool | None = None
    smart_folder: bool | None = None


@router.patch("/{sid}")
def edit(sid: uuid.UUID, body: SavedPatch, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    s = _own(db, user, sid)
    if body.name is not None or body.query is not None:
        s.name, s.query = _check(db, user, body.name or s.name, body.query or s.query, exclude=s.id)
    if body.pinned is not None:
        s.pinned = body.pinned
    if body.notify is not None:
        s.notify = body.notify
    _set_smart_folder(db, user, s, body.smart_folder if body.smart_folder is not None else _folder_of(db, s) is not None)
    db.commit()
    return saved_json(s, _folder_of(db, s))


@router.delete("/{sid}", status_code=204)
def remove(sid: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    """Removes the saved search and its smart folder. Mail is untouched."""
    db.delete(_own(db, user, sid))
    db.commit()

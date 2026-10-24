"""Custom categories (brief section 8): a name plus a plain-English definition the model uses."""
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.llm.service import BUILTIN_CATEGORIES
from app.models import Category, GmailAccount, User
from app.security import current_user

router = APIRouter(prefix="/api/v1/categories")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{1,39}$")


class CategoryIn(BaseModel):
    name: str
    definition: str = Field(min_length=5, max_length=300)
    account_scope: list[uuid.UUID] | None = None

    @field_validator("name")
    @classmethod
    def valid_name(cls, v: str) -> str:
        v = re.sub(r"\s+", " ", v.strip())
        if not NAME.match(v):
            raise ValueError("2-40 characters: letters, digits, spaces, - and _")
        return v

    @field_validator("definition")
    @classmethod
    def clean_definition(cls, v: str) -> str:
        return re.sub(r"\s+", " ", v.strip())


def _key(name: str) -> str:
    return re.sub(r"[\s-]+", "_", name.strip().lower())


def category_json(c: Category) -> dict:
    return {"id": str(c.id), "name": c.name, "definition": c.definition, "account_scope": c.account_scope, "builtin": False}


def _check(db: Session, user: User, body: CategoryIn, exclude: uuid.UUID | None = None) -> None:
    if _key(body.name) in BUILTIN_CATEGORIES:
        raise HTTPException(409, f"{body.name} is a built-in category")
    for c in db.scalars(select(Category).where(Category.user_id == user.id)):
        if c.id != exclude and _key(c.name) == _key(body.name):
            raise HTTPException(409, f"you already have a category called {c.name}")
    for aid in body.account_scope or []:
        a = db.get(GmailAccount, aid)
        if a is None or a.user_id != user.id:
            raise HTTPException(404, "account not found")


@router.get("")
def list_categories(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    builtin = [{"id": None, "name": c, "definition": None, "account_scope": None, "builtin": True} for c in BUILTIN_CATEGORIES]
    return builtin + [category_json(c) for c in db.scalars(select(Category).where(Category.user_id == user.id).order_by(Category.name))]


@router.post("", status_code=201)
def create_category(body: CategoryIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    _check(db, user, body)
    c = Category(user_id=user.id, name=body.name, definition=body.definition,
                 account_scope=[str(a) for a in body.account_scope] if body.account_scope else None)
    db.add(c)
    db.commit()
    return category_json(c)


def _own(db: Session, user: User, category_id: uuid.UUID) -> Category:
    c = db.get(Category, category_id)
    if c is None or c.user_id != user.id:
        raise HTTPException(404, "category not found")
    return c


@router.put("/{category_id}")
def update_category(category_id: uuid.UUID, body: CategoryIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    c = _own(db, user, category_id)
    _check(db, user, body, exclude=c.id)
    c.name, c.definition = body.name, body.definition
    c.account_scope = [str(a) for a in body.account_scope] if body.account_scope else None
    db.commit()
    return category_json(c)


@router.delete("/{category_id}", status_code=204)
def delete_category(category_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    """Mail already in this category keeps the label; new mail is no longer sorted into it."""
    db.delete(_own(db, user, category_id))
    db.commit()

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import create_token, current_user, verify_password

router = APIRouter(prefix="/api/v1")


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "wrong email or password")
    return {"token": create_token(user), "user": {"id": str(user.id), "email": user.email}}


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"id": str(user.id), "email": user.email}

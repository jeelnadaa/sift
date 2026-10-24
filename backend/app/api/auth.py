from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import throttle
from app.config import get_settings
from app.db import get_db
from app.models import User
from app.security import create_token, current_user, verify_password

router = APIRouter(prefix="/api/v1")


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/auth/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)) -> dict:
    email = body.email.strip().lower()
    keys = [f"email:{email}", f"ip:{throttle.client_address(request)}"]
    wait = throttle.retry_after(keys, get_settings().login_attempts)
    if wait:
        raise HTTPException(429, f"too many failed sign-ins, try again in {wait // 60 + 1} min", headers={"Retry-After": str(wait)})
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(body.password, user.password_hash):
        throttle.record_failure(keys)
        raise HTTPException(401, "wrong email or password")
    throttle.reset(keys[0])
    return {"token": create_token(user), "user": {"id": str(user.id), "email": user.email}}


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"id": str(user.id), "email": user.email}

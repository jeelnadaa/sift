import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import throttle
from app.config import get_settings
from app.db import get_db
from app.models import User
from app.security import create_token, current_user, hash_password, verify_password

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


EMAIL = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]{2,}$")
REGISTER_PER_ADDRESS = 5  # new accounts per network address in the throttle window


@router.get("/auth/options")
def options() -> dict:
    """What the sign-in screen offers (e.g. whether to show "Create an account")."""
    return {"registration": get_settings().registration == "open"}


class RegisterIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)


@router.post("/auth/register", status_code=201)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)) -> dict:
    if get_settings().registration != "open":
        raise HTTPException(403, "Sign-ups are closed on this server. Ask its owner for an account.")
    keys = [f"register:{throttle.client_address(request)}"]
    wait = throttle.retry_after(keys, REGISTER_PER_ADDRESS)
    if wait:
        raise HTTPException(429, f"too many new accounts from this network, try again in {wait // 60 + 1} min", headers={"Retry-After": str(wait)})
    email = body.email.strip().lower()
    if not EMAIL.match(email):
        raise HTTPException(422, "Enter a valid email address")
    problem = password_problem(body.password, email)
    if problem:
        raise HTTPException(422, problem)
    throttle.record_failure(keys)  # counts every sign-up attempt from this address
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")
    user = User(email=email, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    from app import starter
    starter.setup(db, user)
    db.commit()
    return {"token": create_token(user), "user": {"id": str(user.id), "email": user.email}}


def password_problem(password: str, email: str) -> str | None:
    if len(password) < 10:
        return "Use at least 10 characters for the password"
    if len(set(password)) < 4 or password.lower() in email.lower() or email.split("@")[0].lower() in password.lower():
        return "That password is too easy to guess; pick another"
    return None


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"id": str(user.id), "email": user.email}

"""Passwords (scrypt, stdlib) and app sign-in tokens (JWT HS256 signed with APP_SECRET)."""
import base64
import hashlib
import hmac
import os
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User

_N, _R, _P = 2**14, 8, 1  # scrypt cost; ~50 ms per check


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        return False
    _, salt, digest = stored.split("$")
    check = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=_N, r=_R, p=_P)
    return hmac.compare_digest(check, base64.b64decode(digest))


def _secret() -> str:
    secret = get_settings().app_secret
    if not secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "APP_SECRET is not set")
    return secret


def create_token(user: User) -> str:
    now = datetime.now(UTC)
    payload = {"sub": str(user.id), "iat": now, "exp": now + timedelta(days=get_settings().jwt_days)}
    return jwt.encode(payload, _secret(), algorithm="HS256")


def current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sign in required")
    try:
        claims = jwt.decode(authorization.removeprefix("Bearer "), _secret(), algorithms=["HS256"])
        user = db.get(User, uuid.UUID(claims["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        user = None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired sign-in")
    return user


def user_id_from_header(authorization: str | None = Header(default=None)) -> uuid.UUID:
    """Like current_user, for long-lived responses (live streams): checks the sign-in with a
    short session and returns only the id, so no database connection stays checked out."""
    from app.db import get_sessionmaker

    with get_sessionmaker()() as db:
        return current_user(authorization, db).id

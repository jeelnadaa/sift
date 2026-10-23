import hmac

from fastapi import Header, HTTPException, status

from app.config import get_settings


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """Temporary guard for Phase 0 endpoints. JWT user auth replaces it in Phase 1."""
    expected = get_settings().admin_token
    if not expected or not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "admin token required")

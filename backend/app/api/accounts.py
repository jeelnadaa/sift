import html
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts import ConnectError, connect_account
from app.api.deps import require_admin
from app.db import get_db
from app.mail import google_oauth
from app.mail.base import AuthRevoked
from app.models import GmailAccount, User

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/accounts")


@router.get("/connect-url", dependencies=[Depends(require_admin)])
def connect_url(user_email: str, login_hint: str | None = None) -> dict:
    try:
        return {"auth_url": google_oauth.authorization_url(user_email.lower(), login_hint)}
    except google_oauth.OAuthError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("", dependencies=[Depends(require_admin)])
def list_accounts(user_email: str, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(GmailAccount).join(User).where(User.email == user_email.lower()).order_by(GmailAccount.created_at))
    return [
        {"id": str(a.id), "email": a.email, "status": a.status, "status_detail": a.status_detail, "label": a.label,
         "watch_expires_at": a.watch_expires_at.isoformat() if a.watch_expires_at else None}
        for a in rows
    ]


@router.get("/oauth/callback", response_class=HTMLResponse)
def oauth_callback(state: str = "", code: str = "", error: str = "", db: Session = Depends(get_db)) -> HTMLResponse:
    """Google redirects here. Public endpoint: the signed state proves the request started in Sift."""
    try:
        user_email = google_oauth.read_state(state)
    except google_oauth.OAuthError as exc:
        return _page("Link expired", f"{exc}. Start the connection again.", ok=False, status=400)
    if error:
        if error in google_oauth.BLOCKED_ERRORS:
            return _page("Account blocked", "This account may be blocked by its administrator (common for college or work accounts).", ok=False)
        return _page("Not connected", "Google access was not granted.", ok=False)
    try:
        account = connect_account(db, user_email, code)
    except AuthRevoked as exc:
        msg = "This account may be blocked by its administrator (common for college or work accounts)." if exc.blocked else "Google rejected the sign-in. Try again."
        return _page("Not connected", msg, ok=False)
    except (ConnectError, google_oauth.OAuthError) as exc:
        return _page("Not connected", str(exc), ok=False, status=400)
    return _page("Connected", f"{account.email} is connected. New mail will be picked up within seconds. You can close this tab.")


def _page(title: str, message: str, ok: bool = True, status: int = 200) -> HTMLResponse:
    color = "#c8ff3d" if ok else "#ff5a3c"
    body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sift · {html.escape(title)}</title>
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#0a0a0b;color:#f4f3ee;font:15px/1.5 system-ui,sans-serif}}
.c{{max-width:420px;padding:28px;border:1px solid #26262b;border-radius:10px;background:#151518}}
h1{{margin:0 0 8px;font-size:24px;color:{color}}}p{{margin:0;color:#a9a9b1}}</style></head>
<body><div class="c"><h1>{html.escape(title)}</h1><p>{html.escape(message)}</p></div></body></html>"""
    return HTMLResponse(body, status_code=status)

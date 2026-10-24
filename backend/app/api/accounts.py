import html
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import accounts as account_service
from app import intake
from app.accounts import ConnectError, connect_account
from app.db import get_db
from app.mail import google_oauth
from app.mail.base import AuthRevoked
from app.models import GmailAccount, User
from app.security import current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/accounts")


def account_json(a: GmailAccount) -> dict:
    return {
        "id": str(a.id), "email": a.email, "status": a.status, "status_detail": a.status_detail,
        "label": a.label, "color": a.color,
        "watch_expires_at": a.watch_expires_at.isoformat() if a.watch_expires_at else None,
        "can_modify": account_service.can_modify(a),
        **intake.health_json(a),
    }


@router.get("")
def list_accounts(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(GmailAccount).where(GmailAccount.user_id == user.id).order_by(GmailAccount.created_at))
    return [account_json(a) for a in rows]


@router.get("/connect-url")
def connect_url(login_hint: str | None = None, user: User = Depends(current_user)) -> dict:
    try:
        return {"auth_url": google_oauth.authorization_url(user.email, login_hint)}
    except google_oauth.OAuthError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/{account_id}/write-access-url")
def write_access_url(account_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Google's page asking to let Sift change mail in this one account (archive, labels, read
    state, star, trash, snooze). Asked only when the user first wants such an action."""
    account = db.get(GmailAccount, account_id)
    if account is None or account.user_id != user.id:
        raise HTTPException(404, "account not found")
    try:
        return {"auth_url": google_oauth.authorization_url(user.email, account.email, write=True), "email": account.email}
    except google_oauth.OAuthError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.delete("/{account_id}", status_code=204)
def remove_account(account_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    """Stops the Gmail watch (push mode), deletes the tokens and all stored mail of the account."""
    account = db.get(GmailAccount, account_id)
    if account is None or account.user_id != user.id:
        raise HTTPException(404, "account not found")
    if account.watch_expires_at and account.encrypted_refresh_token:
        try:
            account_service.provider_for(account).stop_watch()
        except Exception:
            log.warning("could not stop watch for account %s; it lapses within 7 days", account.id)
    account_service._token_cache.pop(account.id, None)
    db.delete(account)  # cascades to messages, notifications, folder items, group members
    db.commit()


@router.get("/oauth/callback", response_class=HTMLResponse)
def oauth_callback(state: str = "", code: str = "", error: str = "", db: Session = Depends(get_db)) -> HTMLResponse:
    """Google redirects here. Public endpoint: the signed state proves the request started in Sift."""
    try:
        st = google_oauth.read_state_data(state)
        user_email, intent = st["u"], st["x"]
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
    if intent.get("intent") == "write":
        if not account_service.can_modify(account):
            return _page("Still read-only", f"Google didn't grant write access for {account.email}. Sift keeps reading it as before.", ok=False)
        if intent.get("account") and intent["account"].lower() != account.email:
            return _page("Different account", f"You signed in as {account.email}, which now has write access. {intent['account']} is unchanged.", ok=False)
        return _page("Write access granted", f"Sift can now archive, label, mark read, star and snooze mail in {account.email}. Go back to Sift and try again.")
    return _page("Connected", f"{account.email} is connected. New mail will be picked up within seconds. You can close this tab.")


def _page(title: str, message: str, ok: bool = True, status: int = 200) -> HTMLResponse:
    color = "#c8ff3d" if ok else "#ff5a3c"
    body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sift · {html.escape(title)}</title>
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#0a0a0b;color:#f4f3ee;font:15px/1.5 system-ui,sans-serif}}
.c{{max-width:420px;padding:28px;border:1px solid #26262b;border-radius:10px;background:#151518}}
h1{{margin:0 0 8px;font-size:24px;color:{color}}}p{{margin:0;color:#a9a9b1}}</style></head>
<body><div class="c"><h1>{html.escape(title)}</h1><p>{html.escape(message)}</p>
<p style="margin-top:16px"><a href="/app/accounts" style="color:#c8ff3d;font-weight:700;text-decoration:none">Back to Sift →</a></p></div></body></html>"""
    return HTMLResponse(body, status_code=status)

"""Gmail accounts: connect, check for new mail, keep watches alive.

check_account() is the single entry point for "something may have changed in this
mailbox". Poll mode calls it on a timer; push mode calls it when Pub/Sub pings.
Everything after it (the Phase 1 pipeline) is the same in both modes.
"""
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import crypto
from app.config import get_settings
from app.db import get_sessionmaker
from app.mail import google_oauth
from app.mail.base import AuthRevoked, CursorExpired, MailProvider
from app.mail.gmail import GmailProvider
from app.models import GmailAccount, User

log = logging.getLogger(__name__)

_token_cache: dict[uuid.UUID, tuple[str, float]] = {}  # account id -> (access token, expiry epoch)


class ConnectError(Exception):
    pass


def provider_factory(access_token: str) -> MailProvider:
    return GmailProvider(access_token)


def _access_token(account: GmailAccount) -> str:
    cached = _token_cache.get(account.id)
    if cached and cached[1] > time.time() + 60:
        return cached[0]
    try:
        refresh_token = crypto.decrypt(account.encrypted_refresh_token)
    except InvalidToken as exc:  # ENCRYPTION_KEYS changed or lost: only a reconnect can fix it
        raise AuthRevoked("stored token unreadable (ENCRYPTION_KEYS changed?)") from exc
    token, expires_in = google_oauth.refresh_access_token(refresh_token)
    _token_cache[account.id] = (token, time.time() + expires_in)
    return token


def provider_for(account: GmailAccount) -> MailProvider:
    return provider_factory(_access_token(account))


def mark_auth_failure(account: GmailAccount, exc: AuthRevoked) -> None:
    _token_cache.pop(account.id, None)
    account.status = "blocked" if exc.blocked else "needs_reconnect"
    account.status_detail = str(exc)[:200]
    log.warning("account %s is now %s", account.id, account.status)


# ---- connect -----------------------------------------------------------------

def connect_account(db: Session, user_email: str, code: str) -> GmailAccount:
    user = db.scalar(select(User).where(User.email == user_email))
    if user is None:
        raise ConnectError("unknown user")
    tokens = google_oauth.exchange_code(code)
    if "refresh_token" not in tokens:
        raise ConnectError("Google returned no refresh token; remove Sift's access at myaccount.google.com/permissions and retry")
    provider = provider_factory(tokens["access_token"])
    profile = provider.profile()

    account = db.scalar(select(GmailAccount).where(GmailAccount.email == profile.email))
    if account is not None and account.user_id != user.id:
        raise ConnectError("this Gmail address is connected to another Sift user")
    if account is None:
        account = GmailAccount(user_id=user.id, email=profile.email, label=profile.email.split("@")[0])
        db.add(account)
        account.history_id = profile.cursor  # new account: start from now, never backfill
    # Reconnect keeps the old cursor so mail that arrived while disconnected is still caught.
    account.encrypted_refresh_token = crypto.encrypt(tokens["refresh_token"])
    account.status, account.status_detail = "active", None
    db.flush()
    _token_cache[account.id] = (tokens["access_token"], time.time() + int(tokens.get("expires_in", 3600)))

    if get_settings().change_detection == "push":
        _start_watch(account, provider)
    db.commit()
    log.info("connected account %s", account.id)
    return account


# ---- change detection ----------------------------------------------------------

def on_new_messages(db: Session, account: GmailAccount, provider: MailProvider, message_ids: list[str]) -> None:
    """Run the pipeline for each new message, oldest first. A transient error stops here and the
    check is retried from the same cursor; already processed messages are skipped then."""
    from app.pipeline import process_message

    log.info("account %s: %d new message(s)", account.id, len(message_ids))
    for gmail_id in message_ids:
        with get_sessionmaker()() as mdb:
            acc = mdb.get(GmailAccount, account.id)
            outcome = process_message(mdb, acc, provider, gmail_id)
            if outcome.decided_by != "existing":
                log.info("message %s: %s by %s%s", outcome.message_id, outcome.priority, outcome.decided_by, ", notified" if outcome.notified else "")


def check_account(account_id: uuid.UUID | str) -> int:
    """List changes since the stored cursor, hand new mail on, then save the cursor.
    The row lock serializes concurrent checks of one account (a poll and a push at once).
    Returns the number of new messages."""
    with get_sessionmaker()() as db:
        # FOR NO KEY UPDATE, not FOR UPDATE: the pipeline inserts messages that reference this row
        # from another connection, and FOR UPDATE would block those inserts (self-deadlock).
        account = db.scalar(
            select(GmailAccount).where(GmailAccount.id == uuid.UUID(str(account_id))).with_for_update(skip_locked=True, key_share=True)
        )
        if account is None or account.status != "active" or not account.encrypted_refresh_token:
            return 0  # missing, paused, or another worker is already checking it
        try:
            provider = provider_for(account)
            if account.history_id is None:
                account.history_id = provider.profile().cursor
                db.commit()
                return 0
            try:
                changes = provider.list_changes(account.history_id)
            except CursorExpired:
                # Down for over a week. Phase 1 adds a catch-up scan of recent mail here.
                log.warning("account %s: history cursor expired, restarting from now", account.id)
                account.history_id = provider.profile().cursor
                db.commit()
                return 0
            if changes.message_ids:
                on_new_messages(db, account, provider, changes.message_ids)
            account.history_id = changes.cursor  # only after successful processing
            db.commit()
            return len(changes.message_ids)
        except AuthRevoked as exc:
            mark_auth_failure(account, exc)
            db.commit()
            return 0


def active_account_ids(db: Session) -> list[uuid.UUID]:
    return list(db.scalars(select(GmailAccount.id).where(GmailAccount.status == "active", GmailAccount.encrypted_refresh_token.is_not(None))))


# ---- Pub/Sub watch (push mode) ----------------------------------------------------

def _start_watch(account: GmailAccount, provider: MailProvider) -> None:
    topic = get_settings().pubsub_topic
    if not topic:
        raise ConnectError("CHANGE_DETECTION=push needs PUBSUB_TOPIC")
    watch = provider.start_watch(topic)
    account.watch_expires_at = datetime.fromtimestamp(watch.expires_at_ms / 1000, UTC)
    # Keep our own cursor: the watch's historyId is "now" and would skip unprocessed mail.


def renew_watches() -> int:
    """Daily (Google recommends renewing once a day; watches lapse after 7 days)."""
    renewed = 0
    soon = datetime.now(UTC) + timedelta(days=1)
    with get_sessionmaker()() as db:
        accounts = db.scalars(select(GmailAccount).where(GmailAccount.status == "active", GmailAccount.encrypted_refresh_token.is_not(None)))
        for account in accounts:
            if account.watch_expires_at and account.watch_expires_at > soon:
                continue
            try:
                _start_watch(account, provider_for(account))
                renewed += 1
            except AuthRevoked as exc:
                mark_auth_failure(account, exc)
            except Exception:
                log.exception("watch renewal failed for account %s", account.id)
            db.commit()
    return renewed

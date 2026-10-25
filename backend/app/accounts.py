"""Gmail accounts: connect, check for new mail, keep watches alive.

check_account() is the single entry point for "something may have changed in this
mailbox". Poll mode calls it on a timer; push mode calls it when Pub/Sub pings.
Everything after it (the Phase 1 pipeline) is the same in both modes.

Healing after downtime (the server is a laptop that gets switched off):
- Off for less than about a week: Gmail still lists the changes since our stored cursor, so the
  next check processes every missed mail. Only urgent mail pushes on its own; the rest of the
  late mail is summed up in one push ("12 mails arrived while Sift was off").
- Off for longer (the cursor expired): a catch_up job lists inbox mail since the last good check
  (up to CATCH_UP_DAYS / CATCH_UP_MAX) and runs it through the same pipeline. Mail older than
  pipeline.AI_MAX_AGE is sorted by rules only, never sent to the AI.
- A newly connected account imports its last IMPORT_DAYS of inbox mail, rules only, silently,
  so the feed is not empty on day one.
"""
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

from cryptography.fernet import InvalidToken
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import crypto, intake
from app.config import get_settings
from app.db import get_sessionmaker
from app.mail import google_oauth
from app.mail.base import AuthRevoked, CursorExpired, MailProvider
from app.mail.gmail import GmailProvider
from app.models import GmailAccount, Message, User

log = logging.getLogger(__name__)

_token_cache: dict[uuid.UUID, tuple[str, float]] = {}  # account id -> (access token, expiry epoch)


CATCH_UP_DAYS = 30  # a longer outage is caught up for its last 30 days
CATCH_UP_MAX = 500
IMPORT_DAYS = 7
IMPORT_MAX = 300
# mail Sift itself sends or drafts is not new mail; Gmail's list already leaves out spam and trash
CATCH_UP_QUERY = "-in:sent -in:drafts -in:chats"


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
    from app import demo  # demo accounts have no Gmail token; their mail is read from the samples

    if demo.is_demo(account) and not account.encrypted_refresh_token:
        return demo.DemoReader()
    return provider_factory(_access_token(account))


def can_modify(account: GmailAccount) -> bool:
    """Whether the user gave Sift write access to this account (archive, labels, read state…).
    The demo account has no Gmail: its actions only change Sift's copy (see demo.DemoReader)."""
    from app import demo

    if demo.is_demo(account) and not account.encrypted_refresh_token:
        return True
    return google_oauth.MODIFY_SCOPE in (account.scopes or [])


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
    is_new = account is None
    if account is None:
        account = GmailAccount(user_id=user.id, email=profile.email, label=profile.email.split("@")[0])
        db.add(account)
        account.history_id = profile.cursor  # new account: start from now, never backfill
    # Reconnect keeps the old cursor so mail that arrived while disconnected is still caught.
    account.encrypted_refresh_token = crypto.encrypt(tokens["refresh_token"])
    account.scopes = sorted(set((tokens.get("scope") or google_oauth.READONLY_SCOPE).split()))
    account.status, account.status_detail = "active", None
    db.flush()
    _token_cache[account.id] = (tokens["access_token"], time.time() + int(tokens.get("expires_in", 3600)))

    if get_settings().change_detection == "push":
        _start_watch(account, provider)
    scan_id = None
    if is_new:
        from app import scan

        scan_id = scan.start(db, account).id  # headers-only look at the last 30 days
    db.commit()
    if scan_id is not None:
        from app import jobs

        jobs.enqueue_sync("onboarding_scan", {"scan_id": str(scan_id)}, dedupe_key=f"scan:{scan_id}")
        # the feed starts with the last week of mail, not empty (rules only, no AI, no pushes)
        since = datetime.now(UTC) - timedelta(days=IMPORT_DAYS)
        jobs.enqueue_sync("catch_up", {"account_id": str(account.id), "since": since.isoformat(), "mode": "import"},
                          dedupe_key=f"catch_up:{account.id}")
    log.info("connected account %s", account.id)
    return account


# ---- change detection ----------------------------------------------------------

def on_new_messages(db: Session, account: GmailAccount, provider: MailProvider, message_ids: list[str], mode: str = "live") -> int:
    """Run the pipeline for each new message, oldest first. A transient error stops here and the
    check is retried from the same cursor; already processed messages are skipped then.
    Late mail that was not pushed on its own gets one summary push at the end.
    Returns how many messages were new to Sift."""
    from app import events, notify
    from app.locks import user_lock
    from app.pipeline import process_message

    log.info("account %s: %d new message(s)%s", account.id, len(message_ids), f" ({mode})" if mode != "live" else "")
    new = held = 0
    quiet_ids: list[uuid.UUID] = []

    def announce() -> None:  # quietly sorted mail reaches open apps in batches, not one by one
        if quiet_ids:
            with get_sessionmaker()() as edb:
                events.publish(edb, account.user_id, "new_mail", ids=list(quiet_ids))
                edb.commit()
            quiet_ids.clear()

    try:
        for gmail_id in message_ids:
            # one mail at a time per user, across accounts and AI tasks (see app.locks)
            with user_lock(account.user_id), get_sessionmaker()() as mdb:
                acc = mdb.get(GmailAccount, account.id)
                outcome = process_message(mdb, acc, provider, gmail_id, mode=mode)
            if outcome.decided_by in ("existing", "gone"):
                continue
            new += 1
            # late mail not pushed on its own; too-old mail counts too (but not imports or silenced mail)
            if outcome.held or (outcome.quiet and mode == "live" and outcome.priority not in (None, "silent")):
                held += 1
            if outcome.quiet and outcome.message_id:
                quiet_ids.append(outcome.message_id)
                if len(quiet_ids) >= 25:
                    announce()
            log.info("message %s: %s by %s%s", outcome.message_id, outcome.priority, outcome.decided_by, ", notified" if outcome.notified else "")
    finally:
        announce()
        if held:
            with get_sessionmaker()() as ndb:
                n = f"{held} mail{'s' if held != 1 else ''}"
                notify.send_system(ndb, account.user_id, "Caught up on missed mail",
                                   f"{n} arrived in {account.email} while Sift was off. They're in your feed.")
                ndb.commit()
    return new


def catch_up(account_id: uuid.UUID | str, since: datetime, mode: str = "live") -> int:
    """List inbox mail since `since` and run it through the pipeline, oldest first: after an
    outage too long for the change cursor, or as a new account's import. Idempotent: mail
    already in Sift is skipped, so a retry or an overlapping regular check costs nothing extra."""
    with get_sessionmaker()() as db:
        account = db.get(GmailAccount, uuid.UUID(str(account_id)))
        if account is None or account.status != "active" or not account.encrypted_refresh_token:
            return 0
        days, limit = (IMPORT_DAYS, IMPORT_MAX) if mode == "import" else (CATCH_UP_DAYS, CATCH_UP_MAX)
        since = max(since, datetime.now(UTC) - timedelta(days=days))
        try:
            provider = provider_for(account)
            ids = provider.list_message_ids(f"after:{int(since.timestamp())} {CATCH_UP_QUERY}", limit)
            ids.reverse()  # Gmail lists newest first; process oldest first, like live mail
            new = on_new_messages(db, account, provider, ids, mode=mode)
        except AuthRevoked as exc:
            mark_auth_failure(account, exc)
            db.commit()
            return 0
        log.info("account %s: caught up %d of %d listed message(s) (%s)", account.id, new, len(ids), mode)
        return new


PUSH_MISS_AGE = timedelta(seconds=90)  # Gmail's push normally lands ~20 s after a mail arrives


def _push_missed(db: Session, account: GmailAccount, message_ids: list[str]) -> bool:
    """A safety check found mail old enough that its push should already have arrived."""
    from app.models import Message

    oldest = db.scalar(select(func.min(Message.received_at)).where(Message.account_id == account.id, Message.gmail_id.in_(message_ids)))
    return oldest is not None and oldest < datetime.now(UTC) - PUSH_MISS_AGE


def check_account(account_id: uuid.UUID | str, source: str = "poll") -> int:
    """List changes since the stored cursor, hand new mail on, then save the cursor.
    The row lock serializes concurrent checks of one account (a poll and a push at once).
    `source` is poll, push or safety. When a safety check in push mode finds mail that push
    never announced, the account's watch is cleared: the scheduler then polls it at poll
    speed until the hourly renewal re-establishes push.
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
                intake.record_ok(db, account)
                db.commit()
                return 0
            try:
                changes = provider.list_changes(account.history_id)
            except CursorExpired:
                # Down for over a week: restart the cursor from now and fetch the gap by search.
                since = account.last_check_ok_at or (datetime.now(UTC) - timedelta(days=CATCH_UP_DAYS))
                log.warning("account %s: history cursor expired, catching up by search", account.id)
                account.history_id = provider.profile().cursor
                intake.record_ok(db, account)
                db.commit()
                from app import jobs

                jobs.enqueue_sync("catch_up", {"account_id": str(account.id), "since": since.isoformat(), "mode": "live"},
                                  dedupe_key=f"catch_up:{account.id}")
                return 0
            if changes.message_ids:
                on_new_messages(db, account, provider, changes.message_ids)
                if source == "safety" and get_settings().change_detection == "push" and _push_missed(db, account, changes.message_ids):
                    log.warning("account %s: push missed new mail; polling it until the watch is renewed", account.id)
                    account.watch_expires_at = None
            if changes.label_changes:
                apply_label_changes(db, account, changes.label_changes)
            account.history_id = changes.cursor  # only after successful processing
            intake.record_ok(db, account)
            db.commit()
            return len(changes.message_ids)
        except AuthRevoked as exc:
            mark_auth_failure(account, exc)
            db.commit()
            return 0
        except Exception as exc:
            db.rollback()
            intake.record_failure(account_id, exc)  # visible in the app; alerts after 15 minutes
            raise


def apply_label_changes(db: Session, account: GmailAccount, changes: list[tuple[str, list[str], list[str]]]) -> None:
    """Keep stored labels (read/unread, starred) in step with Gmail, for unread counts.
    Mail Sift never stored is skipped."""
    from app import events

    ids = {c[0] for c in changes}
    rows = {m.gmail_id: m for m in db.scalars(select(Message).where(Message.account_id == account.id, Message.gmail_id.in_(ids)))}
    changed = []
    for gmail_id, added, removed in changes:
        m = rows.get(gmail_id)
        if m is not None:
            labels = [label for label in (m.labels or []) if label not in removed]
            new = labels + [label for label in added if label not in labels]
            if set(new) != set(m.labels or []):
                m.labels = new
                changed.append(m.id)
    if changed:  # read, starred or archived in Gmail itself: open apps update live
        events.mail_changed(db, account.user_id, changed)


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

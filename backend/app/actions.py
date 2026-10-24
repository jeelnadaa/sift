"""Changing mail in Gmail (Phase 3c): archive, read/unread, star, labels, trash, spam.

Every action works on whole conversations, like Gmail's own buttons. It needs write access
(gmail.modify) for the account, which the user grants per account on first use; without it the
action is refused with the list of accounts that need it, so the app can ask. Nothing is ever
deleted for good: trash is Gmail's trash (undo with untrash; Gmail empties it after 30 days).
Sift's stored copy of the labels is updated at once, so unread counts move immediately; Gmail's
history sync confirms it shortly after.
"""
import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import accounts as account_service
from app.mail.base import AuthRevoked
from app.mail.gmail import GmailError
from app.models import GmailAccount, Message

log = logging.getLogger(__name__)

# action -> (labels to add, labels to remove); "trash"/"untrash" use their own Gmail calls
LABEL_CHANGES: dict[str, tuple[list[str], list[str]]] = {
    "archive": ([], ["INBOX"]),
    "unarchive": (["INBOX"], []),
    "read": ([], ["UNREAD"]),
    "unread": (["UNREAD"], []),
    "star": (["STARRED"], []),
    "unstar": ([], ["STARRED"]),
    "important": (["IMPORTANT"], []),
    "unimportant": ([], ["IMPORTANT"]),
    "spam": (["SPAM"], ["INBOX"]),
    "notspam": (["INBOX"], ["SPAM"]),
}
ACTIONS = (*LABEL_CHANGES, "trash", "untrash", "label", "unlabel")
SYSTEM_LABELS = {"INBOX", "UNREAD", "STARRED", "IMPORTANT", "SPAM", "TRASH", "SENT", "DRAFT", "CHAT"}


class NeedsWriteAccess(Exception):
    def __init__(self, accounts: list[GmailAccount]):
        super().__init__("write access needed")
        self.accounts = accounts


class ActionError(ValueError):
    pass


@dataclass
class Result:
    done: int = 0
    failed: list[str] = field(default_factory=list)  # account emails that failed (others still applied)


def _label_id(provider, name: str, create: bool) -> str:
    """A user label's id by name (case-insensitive); created when missing and `create`."""
    name = " ".join(name.split())[:225]
    if not name:
        raise ActionError("give a label name")
    if name.upper() in SYSTEM_LABELS:
        return name.upper()
    for label in provider.list_labels():
        if label.get("name", "").lower() == name.lower():
            return label["id"]
    if not create:
        raise ActionError(f"no label called {name}")
    return provider.create_label(name)["id"]


def _apply_local(db: Session, account_id: uuid.UUID, thread_id: str, add: list[str], remove: list[str]) -> None:
    for m in db.scalars(select(Message).where(Message.account_id == account_id, Message.thread_id == thread_id)):
        labels = [x for x in (m.labels or []) if x not in remove]
        m.labels = labels + [x for x in add if x not in labels]


def apply(db: Session, user_id: uuid.UUID, threads: list[tuple[uuid.UUID, str]], action: str, label: str | None = None) -> Result:
    """`threads`: (account id, Gmail thread id) pairs. Raises NeedsWriteAccess (nothing changed)
    when any account involved hasn't granted write access."""
    if action not in ACTIONS:
        raise ActionError(f"unknown action {action}")
    if action in ("label", "unlabel") and not label:
        raise ActionError("give a label name")
    by_account: dict[uuid.UUID, list[str]] = {}
    for a_id, t_id in threads:
        by_account.setdefault(a_id, [])
        if t_id not in by_account[a_id]:
            by_account[a_id].append(t_id)
    accounts = {a.id: a for a in db.scalars(select(GmailAccount).where(GmailAccount.id.in_(list(by_account)), GmailAccount.user_id == user_id))}
    if len(accounts) != len(by_account):
        raise ActionError("account not found")
    missing = [a for a in accounts.values() if not account_service.can_modify(a)]
    if missing:
        raise NeedsWriteAccess(missing)

    out = Result()
    for a_id, thread_ids in by_account.items():
        account = accounts[a_id]
        if account.status != "active":
            out.failed.append(account.email)
            continue
        try:
            provider = account_service.provider_for(account)
            if action in ("label", "unlabel"):
                lid = _label_id(provider, label or "", create=action == "label")
                add, remove = ([lid], []) if action == "label" else ([], [lid])
            elif action == "trash":
                add, remove = ["TRASH"], ["INBOX"]
            elif action == "untrash":
                add, remove = ["INBOX"], ["TRASH"]
            else:
                add, remove = LABEL_CHANGES[action]
            for t_id in thread_ids:
                if action == "trash":
                    provider.trash_thread(t_id)
                elif action == "untrash":
                    provider.untrash_thread(t_id)
                else:
                    provider.modify_thread(t_id, add, remove)
                _apply_local(db, a_id, t_id, add, remove)
                out.done += 1
        except AuthRevoked as exc:
            account_service.mark_auth_failure(account, exc)
            out.failed.append(account.email)
        except GmailError as exc:
            if exc.status == 403:  # write access revoked at Google since it was granted
                account.scopes = [s for s in (account.scopes or []) if s != account_service.google_oauth.MODIFY_SCOPE]
            log.warning("action %s failed for account %s: %s", action, account.id, exc.status)
            out.failed.append(account.email)
    db.flush()
    return out

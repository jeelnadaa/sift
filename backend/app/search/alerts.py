"""Saved searches that notify on new matches (brief section 19).

Checked once per new mail, right after the pipeline. Gmail's search index can lag behind a mail
that just arrived, so common operators are evaluated on the mail itself; anything else falls back
to asking Gmail (`rfc822msgid:` narrows the search to this one mail).
A mail that already notified is never notified twice (one notification per message).
"""
import logging
import re

from sqlalchemy import select, true
from sqlalchemy.orm import Session

from app import notify
from app.models import GmailAccount, Message, Notification, SavedSearch
from app.search import engine
from app.search.local import Unknown, gmail_match
from app.search.query import QueryError, parse

log = logging.getLogger(__name__)
def matches(db: Session, m: Message, s: SavedSearch, provider) -> bool:
    try:
        p = parse(s.query)
        conds = engine.conditions(db, m.user_id, p, engine._accounts(db, m.user_id))
    except (QueryError, engine.SearchError):
        return False
    if (conds or p.filters) and db.scalar(select(true()).where(Message.id == m.id, *conds)) is None:
        return False
    if any(f.key == "account" for f in p.filters) and m.account_id not in [a.id for a in engine.selected_accounts(p, engine._accounts(db, m.user_id))]:
        return False
    if not p.has_gmail:
        return True
    try:
        return gmail_match(p.gmail, m)
    except Unknown:
        if not m.message_id_header or not hasattr(provider, "search"):
            return False
        mid = re.sub(r"[<>\s\"]", "", m.message_id_header)
        try:
            ids, _, _ = provider.search(f"({p.gmail}) rfc822msgid:{mid}", None, 1)
        except Exception:
            log.info("saved-search check via Gmail failed for message %s", m.id)
            return False
        return bool(ids)


def check_new(db: Session, m: Message, account: GmailAccount, provider) -> str | None:
    """Notify for the first notifying saved search the new mail matches. Returns its name.
    Never raises: a saved search must not get in the way of the pipeline."""
    try:
        searches = list(db.scalars(select(SavedSearch).where(SavedSearch.user_id == m.user_id, SavedSearch.notify.is_(True))
                                   .order_by(SavedSearch.pinned.desc(), SavedSearch.name)))
        if not searches or m.status == "duplicate":
            return None
        if db.scalar(select(Notification.id).where(Notification.message_id == m.id)) is not None:
            return None  # it already notified on its own
        for s in searches:
            if matches(db, m, s, provider):
                if notify.notify_match(db, m, account, s.name):
                    db.commit()
                return s.name
    except Exception:
        db.rollback()
        log.exception("saved-search alerts failed for message %s", m.id)
    return None

"""What a new account starts with, and a clean restart for an existing one.

Starter setup (new users, and after a reset):
- the bank rule (the brief's own example; `demo.BANK_RULE`);
- a pinned **Placements** folder with an AI rule (mail the AI reads as a placement drive,
  registration, test, interview, result or recruiter mail, or that joined a company timeline,
  is filed there) and auto-sort by company (one subfolder per company, created as needed).
Both are ordinary settings the user can change or delete.

`reset(user)` clears everything Sift learned and stored for the user (mail copies, timelines,
to-dos, folders, rules, tags, notifications, token history…) and keeps what the user set up:
sign-in, connected Gmail accounts (new mail keeps arriving from where it is), the AI key,
phones, and settings. Demo accounts are removed. Nothing in Gmail is touched.
"""
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import demo, folders
from app.models import (
    AiTask, Category, Fingerprint, Folder, FollowUp, GmailAccount, GroupPreference, MailGroup, MailNote, Message,
    Notification, OnboardingScan, Opportunity, Outbox, Reminder, Rule, SavedSearch, Snooze, Tag, Todo, TokenUsage, User,
)

PLACEMENT_FOLDER = "Placements"
PLACEMENT_CATEGORIES = ["placement_announcement", "registration", "assessment_link", "interview", "result", "recruiter"]


def setup(db: Session, user: User) -> None:
    """Safe to call more than once: nothing is added twice."""
    demo.ensure_starter_rules(db, user)
    existing = db.scalar(select(Folder).where(Folder.user_id == user.id, Folder.parent_id.is_(None), Folder.name == PLACEMENT_FOLDER))
    if existing is None:
        f = folders.create(db, user.id, PLACEMENT_FOLDER, None, "#c8ff3d", None)
        f.pinned = True
        f.ai_rule = {"categories": PLACEMENT_CATEGORIES, "timeline": True}
        f.auto_sort = "company"
    db.flush()


# Order matters only for readability: every table here is the user's own data.
_CLEARED = (TokenUsage, AiTask, FollowUp, Outbox, Snooze, Reminder, Todo, Notification, MailNote, Opportunity,
            MailGroup, GroupPreference, Fingerprint, Tag, Folder, SavedSearch, Rule, Category, OnboardingScan, Message)


def reset(db: Session, user_id: uuid.UUID) -> dict:
    counts = {}
    for model in _CLEARED:
        counts[model.__tablename__] = db.execute(delete(model).where(model.user_id == user_id)).rowcount
    demo_accounts = list(db.scalars(select(GmailAccount).where(GmailAccount.user_id == user_id,
                                                               GmailAccount.email.like(f"%@{demo.DEMO_EMAIL_DOMAIN}"))))
    for a in demo_accounts:
        db.delete(a)
    counts["demo_accounts"] = len(demo_accounts)
    db.flush()
    setup(db, db.get(User, user_id))
    return counts

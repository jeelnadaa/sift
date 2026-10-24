"""Database schema (brief section 12). Postgres only.

Conventions:
- UUID primary keys, timezone-aware timestamps.
- Gmail message and thread IDs are unique only within an account, so mail is
  keyed by (account_id, gmail_id).
- Enum-like columns are strings guarded by CHECK constraints, which keeps
  migrations simple when values are added.
- Secrets (refresh tokens, LLM keys) are stored only as Fernet ciphertext.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ACCOUNT_STATUSES = ("active", "needs_reconnect", "blocked")
PRIORITIES = ("urgent", "normal", "digest", "silent")
LLM_KEY_STATUSES = ("unvalidated", "valid", "invalid", "quota_exceeded")
GROUPING_MODES = ("always", "never")
JOB_STATUSES = ("queued", "running", "done", "failed")
OPPORTUNITY_STATUSES = ("active", "closed")
EVENT_KINDS = ("announcement", "registration", "assessment", "interview", "result", "update")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    pass


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def user_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = created()


class GmailAccount(Base):
    __tablename__ = "gmail_accounts"
    __table_args__ = (CheckConstraint(_in("status", ACCOUNT_STATUSES), name="status_valid"),)
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    # Unique across the system: Pub/Sub pushes carry only the address, so it must route to one row.
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text)
    history_id: Mapped[int | None] = mapped_column(BigInteger)
    watch_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active", nullable=False)
    status_detail: Mapped[str | None] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(String(60))
    color: Mapped[str | None] = mapped_column(String(9))
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    fcm_token: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(20), default="android", server_default="android", nullable=False)
    label: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = created()
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Rule(Base):
    __tablename__ = "rules"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    conditions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    action: Mapped[dict] = mapped_column(JSONB, nullable=False)
    exceptions: Mapped[dict | None] = mapped_column(JSONB)
    account_scope: Mapped[list | None] = mapped_column(JSONB)  # null = all accounts, else list of account ids
    origin: Mapped[str] = mapped_column(String(20), default="editor", server_default="editor", nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created()


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("user_id", "name"),)
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    definition: Mapped[str | None] = mapped_column(Text)
    account_scope: Mapped[list | None] = mapped_column(JSONB)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("account_id", "gmail_id"),
        Index("ix_messages_user_msgid", "user_id", "message_id_header"),
        Index("ix_messages_user_received", "user_id", "received_at"),
        Index("ix_messages_account_thread", "account_id", "thread_id"),
        CheckConstraint(f"priority IS NULL OR {_in('priority', PRIORITIES)}", name="priority_valid"),
    )
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gmail_accounts.id", ondelete="CASCADE"), nullable=False)
    gmail_id: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    message_id_header: Mapped[str | None] = mapped_column(Text)
    sender: Mapped[str | None] = mapped_column(String(320))
    sender_name: Mapped[str | None] = mapped_column(String(200))
    authenticated_domain: Mapped[str | None] = mapped_column(String(253))
    subject: Mapped[str | None] = mapped_column(Text)
    snippet: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    labels: Mapped[list | None] = mapped_column(JSONB)
    list_id: Mapped[str | None] = mapped_column(String(320))
    # Lowercased names of the metadata headers present (not their values), for rule previews.
    header_names: Mapped[list | None] = mapped_column(JSONB)
    has_attachment: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    category: Mapped[str | None] = mapped_column(String(80))
    priority: Mapped[str | None] = mapped_column(String(10))
    matched_rule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rules.id", ondelete="SET NULL"))
    fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    extraction: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="new", server_default="new", nullable=False)
    created_at: Mapped[datetime] = created()


class Opportunity(Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        CheckConstraint(_in("status", OPPORTUNITY_STATUSES), name="status_valid"),
        Index("ix_opportunities_user_status", "user_id", "status"),
    )
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    company: Mapped[str] = mapped_column(String(200), nullable=False)
    aliases: Mapped[list | None] = mapped_column(JSONB)
    # Sender domains learned from the user's "which company?" answers (e.g. a careers subdomain).
    domains: Mapped[list | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active", nullable=False)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class OpportunityEvent(Base):
    __tablename__ = "opportunity_events"
    __table_args__ = (CheckConstraint(_in("kind", EVENT_KINDS), name="kind_valid"),)
    id: Mapped[uuid.UUID] = pk()
    opportunity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), index=True, nullable=False)
    # A message belongs to at most one opportunity.
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"), unique=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB)  # deadline, links, platform, summary
    matched_by: Mapped[str] = mapped_column(String(20), default="user", server_default="user", nullable=False)  # name, ai, thread, domain, timing, user
    occurred_at: Mapped[datetime] = created()


class Fingerprint(Base):
    __tablename__ = "fingerprints"
    __table_args__ = (UniqueConstraint("user_id", "hash"),)
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(253))  # authenticated sender domain
    sample_subject: Mapped[str | None] = mapped_column(Text)  # the normalized template, not a real subject
    seen_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    # silent / ignore: applied to the next mail; keep: the user declined a suggestion
    last_action: Mapped[str | None] = mapped_column(String(20))
    last_action_source: Mapped[str | None] = mapped_column(String(20))  # rule or user
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created()


class OnboardingScan(Base):
    """Headers-only scan of an account's last 30 days (brief section 8): top senders, no bodies, no LLM."""
    __tablename__ = "onboarding_scans"
    __table_args__ = (CheckConstraint("status IN ('queued', 'running', 'done', 'failed')", name="status_valid"),)
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gmail_accounts.id", ondelete="CASCADE"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="queued", server_default="queued", nullable=False)
    scanned: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    senders: Mapped[list | None] = mapped_column(JSONB)  # [{key, kind, name, count, sample_subject, hints, suggested}]
    error: Mapped[str | None] = mapped_column(Text)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (CheckConstraint(_in("priority", PRIORITIES), name="priority_valid"),)
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    # Unique: processing a message twice must never produce two notifications.
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), unique=True)
    priority: Mapped[str] = mapped_column(String(10), nullable=False)
    mail_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resend_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = created()


class Todo(Base):
    """Action-needed items: created from AI extraction (source "ai") or by hand from any mail or free text."""
    __tablename__ = "todos"
    __table_args__ = (Index("ix_todos_user_done_due", "user_id", "done", "due_at"),)
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("opportunities.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(10), default="manual", server_default="manual", nullable=False)  # ai | manual
    created_at: Mapped[datetime] = created()


class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = (UniqueConstraint("user_id", "dedupe_key"),)
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"))
    todo_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("todos.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20), default="custom", server_default="custom", nullable=False)  # deadline_24h, deadline_2h, custom
    dedupe_key: Mapped[str | None] = mapped_column(String(200))  # same deadline twice never schedules twice
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created()


class TokenUsage(Base):
    __tablename__ = "token_usage"
    __table_args__ = (Index("ix_token_usage_user_day", "user_id", "day"),)
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("gmail_accounts.id", ondelete="SET NULL"))
    day: Mapped[date] = mapped_column(Date, nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    purpose: Mapped[str] = mapped_column(String(40), default="extract", server_default="extract", nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = created()


class LlmCredential(Base):
    __tablename__ = "llm_credentials"
    __table_args__ = (CheckConstraint(_in("status", LLM_KEY_STATUSES), name="status_valid"),)
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    key_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="unvalidated", server_default="unvalidated", nullable=False)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalid_notified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)


class Folder(Base):
    __tablename__ = "folders"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("folders.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    color: Mapped[str | None] = mapped_column(String(9))
    icon: Mapped[str | None] = mapped_column(String(40))
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    notify: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    saved_search_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("saved_searches.id", ondelete="CASCADE"))  # set = smart folder
    created_at: Mapped[datetime] = created()


class FolderItem(Base):
    __tablename__ = "folder_items"
    __table_args__ = (UniqueConstraint("folder_id", "account_id", "thread_id"),)
    id: Mapped[uuid.UUID] = pk()
    folder_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("folders.id", ondelete="CASCADE"), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gmail_accounts.id", ondelete="CASCADE"), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    added_at: Mapped[datetime] = created()


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("user_id", "name"),)
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    color: Mapped[str | None] = mapped_column(String(9))


class MailTag(Base):
    __tablename__ = "mail_tags"
    tag_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    added_at: Mapped[datetime] = created()


class MailNote(Base):
    __tablename__ = "mail_notes"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class SavedSearch(Base):
    __tablename__ = "saved_searches"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    notify: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    created_at: Mapped[datetime] = created()


class MailGroup(Base):
    __tablename__ = "mail_groups"
    __table_args__ = (Index("ix_mail_groups_user_key", "user_id", "kind", "key"),)
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # thread, opportunity, list, template, similar, ai
    key: Mapped[str] = mapped_column(String(320), nullable=False)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created()


class GroupMember(Base):
    __tablename__ = "group_members"
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mail_groups.id", ondelete="CASCADE"), primary_key=True)
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gmail_accounts.id", ondelete="CASCADE"), nullable=False)
    added_by: Mapped[str] = mapped_column(String(10), default="system", server_default="system", nullable=False)
    added_at: Mapped[datetime] = created()


class GroupPreference(Base):
    __tablename__ = "group_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "sender_or_domain"),
        CheckConstraint(_in("mode", GROUPING_MODES), name="mode_valid"),
    )
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    sender_or_domain: Mapped[str] = mapped_column(String(320), nullable=False)
    mode: Mapped[str] = mapped_column(String(10), nullable=False)


class Setting(Base):
    """Per-user settings (account_id null) and per-account overrides, as JSON."""
    __tablename__ = "settings"
    __table_args__ = (UniqueConstraint("user_id", "account_id", postgresql_nulls_not_distinct=True),)
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("gmail_accounts.id", ondelete="CASCADE"))
    data: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Job(Base):
    """Work queue for QUEUE_BACKEND=postgres (the 1 GB host without Redis)."""
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(_in("status", JOB_STATUSES), name="status_valid"),
        Index("ix_jobs_ready", "status", "run_at"),
        # Dedupe only among pending jobs, so a recurring job (check:<account>) can run again once done.
        Index("ix_jobs_dedupe_pending", "dedupe_key", unique=True, postgresql_where=text("status IN ('queued', 'running')")),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(10), default="queued", server_default="queued", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created()

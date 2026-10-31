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
    LargeBinary,
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
    # OAuth scopes Google granted for this account. Read-only until the user first asks Sift to
    # change mail in it (Phase 3c: write access is requested per account, on first use).
    scopes: Mapped[list | None] = mapped_column(JSONB)
    # Mail-check health (2026-10-24 incident): when a check last succeeded, since when checks
    # have been failing and why (error type and HTTP status only, never content), and whether
    # the user was already alerted about it.
    last_check_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_failing_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_check_error: Mapped[str | None] = mapped_column(String(200))
    intake_alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
        Index("ix_messages_user_pinned", "user_id", "pinned"),
        Index("ix_messages_user_sender", "user_id", "sender"),
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
    unsubscribe_url: Mapped[str | None] = mapped_column(Text)
    unsubscribe_mailto: Mapped[str | None] = mapped_column(Text)
    unsubscribe_post: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    # Lowercased names of the metadata headers present (not their values), for rule previews.
    header_names: Mapped[list | None] = mapped_column(JSONB)
    has_attachment: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    category: Mapped[str | None] = mapped_column(String(80))
    priority: Mapped[str | None] = mapped_column(String(10))
    matched_rule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rules.id", ondelete="SET NULL"))
    fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    extraction: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="new", server_default="new", nullable=False)
    created_at: Mapped[datetime] = created()


class MessageAttachment(Base):
    __tablename__ = "message_attachments"
    __table_args__ = (
        Index("ix_message_attachments_user_received", "user_id", "received_at"),
        Index("ix_message_attachments_user_mime", "user_id", "mime"),
        Index("ix_message_attachments_user_filename", "user_id", "filename"),
        Index("ix_message_attachments_message", "message_id"),
    )
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gmail_accounts.id", ondelete="CASCADE"), nullable=False)
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    gmail_id: Mapped[str] = mapped_column(String(64), nullable=False)
    attachment_id: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime: Mapped[str] = mapped_column(String(120), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0", nullable=False)
    content_id: Mapped[str | None] = mapped_column(String(255))
    sender: Mapped[str | None] = mapped_column(String(320))
    sender_name: Mapped[str | None] = mapped_column(String(200))
    subject: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ai_tasks.id", ondelete="SET NULL"), index=True)  # set = spent by an explicit AI task
    assistant_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assistant_runs.id", ondelete="SET NULL"), index=True)  # set = spent by Sift AI
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
    base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fallback_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    fallback_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    fallback_base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encrypted_fallback_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    fallback_key_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)


class Folder(Base):
    __tablename__ = "folders"
    __table_args__ = (CheckConstraint("notify_mode IN ('default', 'always', 'mute')", name="notify_mode_valid"),)
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("folders.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    color: Mapped[str | None] = mapped_column(String(9))
    icon: Mapped[str | None] = mapped_column(String(40))
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    # default: mail filed here notifies as usual; always: notify even digest mail; mute: never notify
    notify_mode: Mapped[str] = mapped_column(String(10), default="default", server_default="default", nullable=False)
    saved_search_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("saved_searches.id", ondelete="CASCADE"))  # set = smart folder
    # AI filing: after the AI reads a new mail, it is filed here when its category is in
    # {"categories": [...]} or (with "timeline": true) when it joined a company timeline.
    ai_rule: Mapped[dict | None] = mapped_column(JSONB)
    # Sort mail filed here into subfolders, created as needed: company, sender, or ai (by
    # `auto_sort_instruction`, e.g. "one folder per course").
    auto_sort: Mapped[str | None] = mapped_column(String(10))
    auto_sort_instruction: Mapped[str | None] = mapped_column(Text)
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


class ReplyTemplate(Base):
    """Reusable text template (canned reply) for compose and replies."""
    __tablename__ = "reply_templates"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    shortcut: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class VipSender(Base):
    """Senders whose incoming mail is marked VIP/urgent and exempt from silent filters."""
    __tablename__ = "vip_senders"
    __table_args__ = (
        UniqueConstraint("user_id", "email", name="uq_vip_sender_user_email"),
        Index("ix_vip_senders_user_email", "user_id", "email"),
    )
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    sender_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = created()


class MutedThread(Base):
    """Conversation threads whose push notifications are suppressed."""
    __tablename__ = "muted_threads"
    __table_args__ = (
        UniqueConstraint("user_id", "thread_id", name="uq_muted_thread_user_thread"),
        Index("ix_muted_threads_user_thread", "user_id", "thread_id"),
    )
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    thread_id: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = created()


class MailNote(Base):
    __tablename__ = "mail_notes"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Snooze(Base):
    """A conversation hidden until a time (Phase 3c). With write access it is also archived in
    Gmail and put back in the inbox when it wakes; without, it is hidden in Sift only."""
    __tablename__ = "snoozes"
    __table_args__ = (
        Index("ix_snoozes_due", "done", "until"),
        Index("uq_snoozes_active_thread", "account_id", "thread_id", unique=True, postgresql_where=text("NOT done")),
    )
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gmail_accounts.id", ondelete="CASCADE"), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    archived_in_gmail: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    woke_reason: Mapped[str | None] = mapped_column(String(20))  # time, reply, cancelled
    created_at: Mapped[datetime] = created()


class MessageEmbedding(Base):
    """Semantic-search vector of one message (Phase 3b): float32 values, normalized, from the
    user's own key. Made from sender, subject, preview and Sift's summary; never the body."""
    __tablename__ = "message_embeddings"
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    dims: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = created()


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
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # thread, opportunity, list, template, similar, sender, custom
    key: Mapped[str] = mapped_column(String(320), nullable=False)
    # custom groups (made by the user): new mail joins when it matches the search and/or the AI
    # says it fits the description (app/places.py)
    query: Mapped[str | None] = mapped_column(Text)
    instruction: Mapped[str | None] = mapped_column(Text)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    muted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    collapsed: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    created_at: Mapped[datetime] = created()


class GroupMember(Base):
    __tablename__ = "group_members"
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mail_groups.id", ondelete="CASCADE"), primary_key=True)
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gmail_accounts.id", ondelete="CASCADE"), nullable=False)
    # system | user; "removed" keeps a mail the user took out from being re-added automatically
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


OUTBOX_STATUSES = ("scheduled", "sending", "sent", "cancelled", "failed")
FOLLOW_UP_STATUSES = ("waiting", "replied", "reminded", "cancelled")


class Outbox(Base):
    """A Gmail draft waiting to be sent by Sift (Phase 4): right after Send (the undo window) or at
    a chosen time (send later). The mail itself lives only in the Gmail draft, so it can be seen
    and edited in Gmail; Sift keeps the draft id, the time and a short summary for its lists."""
    __tablename__ = "outbox"
    __table_args__ = (
        CheckConstraint(_in("status", OUTBOX_STATUSES), name="status_valid"),
        Index("ix_outbox_due", "status", "send_at"),
        Index("uq_outbox_pending_draft", "account_id", "draft_id", unique=True,
              postgresql_where=text("status IN ('scheduled', 'sending')")),
    )
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gmail_accounts.id", ondelete="CASCADE"), nullable=False)
    draft_id: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(64))
    subject: Mapped[str | None] = mapped_column(Text)
    recipients: Mapped[str | None] = mapped_column(Text)  # "a@x.com, b@y.com" for the list
    send_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    later: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)  # send later vs undo window
    follow_up_days: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="scheduled", server_default="scheduled", nullable=False)
    sending_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    sent_gmail_id: Mapped[str | None] = mapped_column(String(64))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = created()


class FollowUp(Base):
    """"Remind me if there's no reply" for a sent mail (Phase 4). Resolved as soon as someone
    else writes in the conversation; otherwise one notification when it's due."""
    __tablename__ = "follow_ups"
    __table_args__ = (
        CheckConstraint(_in("status", FOLLOW_UP_STATUSES), name="status_valid"),
        Index("ix_follow_ups_due", "status", "due_at"),
        Index("ix_follow_ups_thread", "account_id", "thread_id"),
    )
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gmail_accounts.id", ondelete="CASCADE"), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sent_gmail_id: Mapped[str | None] = mapped_column(String(64))
    subject: Mapped[str | None] = mapped_column(Text)
    recipients: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="waiting", server_default="waiting", nullable=False)
    created_at: Mapped[datetime] = created()


AI_TASK_KINDS = ("timelines", "todos", "sort", "fill")
AI_TASK_STATUSES = ("queued", "running", "done", "stopped", "failed")


class AiTask(Base):
    """Something the user asked the AI to do over a folder (and its subfolders): build company
    timelines, make to-dos, or sort into subfolders. Its token use is counted separately."""
    __tablename__ = "ai_tasks"
    __table_args__ = (
        CheckConstraint(_in("kind", AI_TASK_KINDS), name="kind_valid"),
        CheckConstraint(_in("status", AI_TASK_STATUSES), name="status_valid"),
        Index("ix_ai_tasks_user_created", "user_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    folder_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("folders.id", ondelete="SET NULL"))
    folder_name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    include_subfolders: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    instruction: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="queued", server_default="queued", nullable=False)
    total: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    done: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    changed: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)  # timelines joined / to-dos made / mails moved
    note: Mapped[str | None] = mapped_column(String(300))
    # set when the task runs over a search (Ask Sift, e.g. "from:nvidia newer_than:30d") instead of a folder
    query: Mapped[str | None] = mapped_column(Text)
    target_group_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("mail_groups.id", ondelete="CASCADE"))  # fill: into this group (else folder_id)
    assistant_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assistant_runs.id", ondelete="SET NULL"))  # started by Sift AI
    created_at: Mapped[datetime] = created()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


ASSISTANT_STATUSES = ("planned", "running", "done", "failed", "cancelled")


class AssistantRun(Base):
    """One request to Ask Sift: the user's words, the plan the AI made (steps over the app's own
    actions), and what running each step did. Plans that change anything wait for the user."""
    __tablename__ = "assistant_runs"
    __table_args__ = (
        CheckConstraint(_in("status", ASSISTANT_STATUSES), name="status_valid"),
        Index("ix_assistant_runs_user_created", "user_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    reply: Mapped[str | None] = mapped_column(Text)
    steps: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    results: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="planned", server_default="planned", nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = created()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


BULK_STATUSES = ("queued", "running", "done", "failed")


class BulkJob(Base):
    """A big change to many conversations at once (app/bulk.py): runs in the worker with progress.
    Holds message ids and the action only, never mail content."""
    __tablename__ = "bulk_jobs"
    __table_args__ = (
        CheckConstraint(_in("status", BULK_STATUSES), name="status_valid"),
        Index("ix_bulk_jobs_user_created", "user_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    message_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)  # one per conversation
    status: Mapped[str] = mapped_column(String(10), default="queued", server_default="queued", nullable=False)
    total: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    done: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    changed: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)  # ids that changed, for Undo
    failed_accounts: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    created_at: Mapped[datetime] = created()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

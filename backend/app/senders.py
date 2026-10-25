"""Senders Directory and Aggregated Statistics (Phase C Item 2)."""
import uuid
from datetime import datetime

from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.models import Message, Rule
from app import vip


def list_senders(
    db: Session,
    user_id: uuid.UUID,
    q: str | None = None,
    domain: str | None = None,
    min_count: int = 1,
    sort_by: str = "count",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """List all unique senders with aggregate email counts, unread counts, and activity."""
    stmt = (
        select(
            Message.sender,
            func.max(Message.sender_name).label("sender_name"),
            func.max(Message.authenticated_domain).label("domain"),
            func.count(Message.id).label("total_count"),
            func.count().filter(Message.labels.contains(["UNREAD"])).label("unread_count"),
            func.count().filter(Message.priority == "urgent").label("urgent_count"),
            func.count().filter(Message.has_attachment.is_(True)).label("attachment_count"),
            func.max(Message.received_at).label("last_received_at"),
        )
        .where(Message.user_id == user_id, Message.sender.is_not(None), Message.sender != "")
        .group_by(Message.sender)
    )

    if min_count > 1:
        stmt = stmt.having(func.count(Message.id) >= min_count)

    if q and q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Message.sender.ilike(term),
                Message.sender_name.ilike(term),
                Message.authenticated_domain.ilike(term),
            )
        )

    if domain and domain.strip():
        dom = domain.strip().lower()
        stmt = stmt.where(
            or_(
                Message.authenticated_domain == dom,
                Message.sender.ilike(f"%@{dom}"),
            )
        )

    # Total matching senders count
    count_subq = stmt.subquery()
    total = db.scalar(select(func.count()).select_from(count_subq)) or 0

    # Sorting
    if sort_by == "recent":
        stmt = stmt.order_by(desc("last_received_at").nulls_last())
    elif sort_by == "unread":
        stmt = stmt.order_by(desc("unread_count"), desc("total_count"))
    elif sort_by == "urgent":
        stmt = stmt.order_by(desc("urgent_count"), desc("total_count"))
    elif sort_by == "name":
        stmt = stmt.order_by(func.coalesce(func.max(Message.sender_name), Message.sender).asc())
    else:  # "count"
        stmt = stmt.order_by(desc("total_count"), desc("last_received_at").nulls_last())

    stmt = stmt.offset(max(0, offset)).limit(max(1, min(limit, 100)))
    rows = db.execute(stmt).all()

    if not rows:
        return [], total

    # Look up sample latest subject for each sender on this page
    sender_emails = [r.sender for r in rows]
    # Fetch latest message per sender in this page
    latest_stmt = (
        select(Message.sender, Message.subject)
        .where(
            Message.user_id == user_id,
            Message.sender.in_(sender_emails),
            Message.subject.is_not(None),
        )
        .order_by(Message.received_at.desc().nulls_last())
    )
    samples: dict[str, str] = {}
    for s_email, s_subj in db.execute(latest_stmt).all():
        if s_email not in samples and s_subj:
            samples[s_email] = s_subj

    vip_emails = vip.get_vip_emails(db, user_id)
    items = []
    for r in rows:
        email = r.sender
        derived_dom = r.domain or (email.split("@")[-1] if "@" in email else None)
        items.append({
            "email": email,
            "name": r.sender_name,
            "domain": derived_dom,
            "total_count": int(r.total_count),
            "unread_count": int(r.unread_count),
            "urgent_count": int(r.urgent_count),
            "attachment_count": int(r.attachment_count),
            "last_received_at": r.last_received_at.isoformat() if r.last_received_at else None,
            "sample_subject": samples.get(email),
            "is_vip": email.lower() in vip_emails,
        })

    return items, total


def get_sender_detail(db: Session, user_id: uuid.UUID, sender_email: str) -> dict | None:
    """Detailed profile, recent message thread summaries, and associated rules for a sender."""
    clean_email = sender_email.strip().lower()

    # Aggregate stats for this sender
    stat_stmt = (
        select(
            Message.sender,
            func.max(Message.sender_name).label("sender_name"),
            func.max(Message.authenticated_domain).label("domain"),
            func.count(Message.id).label("total_count"),
            func.count().filter(Message.labels.contains(["UNREAD"])).label("unread_count"),
            func.count().filter(Message.priority == "urgent").label("urgent_count"),
            func.count().filter(Message.has_attachment.is_(True)).label("attachment_count"),
            func.max(Message.received_at).label("last_received_at"),
        )
        .where(
            Message.user_id == user_id,
            func.lower(Message.sender) == clean_email,
        )
        .group_by(Message.sender)
    )
    stat = db.execute(stat_stmt).first()
    if not stat:
        return None

    # Fetch recent messages
    recent_msgs_stmt = (
        select(Message)
        .where(
            Message.user_id == user_id,
            func.lower(Message.sender) == clean_email,
        )
        .order_by(Message.received_at.desc().nulls_last())
        .limit(15)
    )
    recent = list(db.scalars(recent_msgs_stmt))

    # Associated rules (matching sender or domain)
    user_rules = list(db.scalars(select(Rule).where(Rule.user_id == user_id)))
    derived_domain = stat.domain or (clean_email.split("@")[-1] if "@" in clean_email else "")
    matched_rules = []
    for rule in user_rules:
        cond_str = str(rule.conditions)
        if clean_email in cond_str or (derived_domain and derived_domain in cond_str):
            matched_rules.append({
                "id": str(rule.id),
                "name": rule.name,
                "enabled": rule.enabled,
                "action": rule.action,
            })

    return {
        "email": stat.sender,
        "name": stat.sender_name,
        "domain": derived_domain,
        "total_count": int(stat.total_count),
        "unread_count": int(stat.unread_count),
        "urgent_count": int(stat.urgent_count),
        "attachment_count": int(stat.attachment_count),
        "last_received_at": stat.last_received_at.isoformat() if stat.last_received_at else None,
        "recent_messages": [
            {
                "id": str(m.id),
                "subject": m.subject,
                "snippet": m.snippet,
                "received_at": m.received_at.isoformat() if m.received_at else None,
                "priority": m.priority,
                "category": m.category,
                "unread": "UNREAD" in (m.labels or []),
                "has_attachment": m.has_attachment,
            }
            for m in recent
        ],
        "rules": matched_rules,
        "is_vip": vip.is_vip(db, user_id, clean_email),
    }

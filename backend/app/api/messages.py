import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import accounts as account_service
from app import events, grouping, notes as notes_service, reader, rule_tools
from app import snooze as snooze_service
from app.db import get_db
from app.mail.base import AuthRevoked
from app.mail.gmail import GmailError
from app.mail.message import extract_body
from app.models import GmailAccount, GroupMember, MailNote, Message, Notification, User
from app.security import current_user

router = APIRouter(prefix="/api/v1/messages")
FEED_STATUSES = ("processed",)
SILENCED_STATUSES = ("silenced", "ignored")


def message_json(m: Message, account: GmailAccount | None = None, notification: Notification | None = None, notes_count: int = 0) -> dict:
    ext = m.extraction or {}
    return {
        "id": str(m.id), "account_id": str(m.account_id),
        "account": (account.label or account.email) if account else None,
        "account_color": account.color if account else None,
        "thread_id": m.thread_id, "sender": m.sender, "sender_name": m.sender_name,
        "subject": m.subject, "snippet": m.snippet,
        "received_at": m.received_at.isoformat() if m.received_at else None,
        "priority": m.priority, "category": m.category, "status": m.status,
        "has_attachment": m.has_attachment, "pinned": m.pinned, "has_note": notes_count > 0, "notes_count": notes_count,
        "unread": "UNREAD" in (m.labels or []),
        "starred": "STARRED" in (m.labels or []), "in_inbox": "INBOX" in (m.labels or []),
        "matched_rule_id": str(m.matched_rule_id) if m.matched_rule_id else None,
        "summary": ext.get("summary"), "company": ext.get("company"), "platform": ext.get("platform"),
        "deadline": ext.get("deadline"), "links": ext.get("links") or [], "action_needed": ext.get("action_needed", False),
        "opportunity_id": ext.get("opportunity_id"), "todo_id": ext.get("todo_id"),
        "company_question": ext.get("company_question"),
        "decided_by": ext.get("source") or ("rule" if m.matched_rule_id else ext.get("heuristic") and "heuristic"),
        "notified_at": notification.sent_at.isoformat() if notification and notification.sent_at else None,
        "delivered_at": notification.acknowledged_at.isoformat() if notification and notification.acknowledged_at else None,
    }


@router.get("")
def list_messages(
    priority: str | None = Query(default=None, pattern="^(urgent|normal|digest|silent)$"),
    account_id: uuid.UUID | None = None,
    view: str = Query(default="feed", pattern="^(feed|silenced|all)$"),
    before: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    grouped: bool = False,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """`grouped=true` folds mail in groups into group rows when the user turned grouping on
    (brief section 21); urgent mail keeps its own row too. Items then carry "type".
    Pages are cursor based (`before` = the previous page's `next_before`); `total` counts the
    rows in all pages and `pages` how many pages of `limit` mails that makes, for "Page 2 of 7"."""
    q = select(Message).where(Message.user_id == user.id)
    if view == "feed":
        q = q.where(Message.status.in_(FEED_STATUSES), ~snooze_service.active_condition())  # snoozed: back when it wakes
    elif view == "silenced":
        q = q.where(Message.status.in_(SILENCED_STATUSES))
    if priority:
        q = q.where(Message.priority == priority)
    if account_id:
        q = q.where(Message.account_id == account_id)
    accounts = {a.id: a for a in db.scalars(select(GmailAccount).where(GmailAccount.user_id == user.id))}
    if grouped and view == "feed" and grouping.enabled(db, user.id):
        rows, groups, next_before, mail_total, group_total = grouping.feed_page(db, user.id, q, before, limit)
        note_counts = dict(db.execute(select(MailNote.message_id, func.count()).where(MailNote.message_id.in_([m.id for m in rows])).group_by(MailNote.message_id)).all()) if rows else {}
        items = [{"type": "mail", **message_json(m, accounts.get(m.account_id), notes_count=note_counts.get(m.id, 0))} for m in rows]
        items += [grouping.group_json(g, ms) for g, ms in groups]
        items.sort(key=lambda i: (bool(i.get("pinned")), i["received_at"] or ""), reverse=True)
        return {"items": items, "next_before": next_before, "grouped": True,
                "total": mail_total + group_total, "pages": page_count(mail_total, limit)}
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    if before:
        q = q.where(Message.pinned.is_(False), Message.received_at < before)
    rows = list(db.scalars(q.order_by(Message.pinned.desc(), Message.received_at.desc().nulls_last()).limit(limit)))
    note_counts = dict(db.execute(select(MailNote.message_id, func.count()).where(MailNote.message_id.in_([m.id for m in rows])).group_by(MailNote.message_id)).all()) if rows else {}
    items = [message_json(m, accounts.get(m.account_id), notes_count=note_counts.get(m.id, 0)) for m in rows]
    unpinned = [m for m in rows if not m.pinned]
    next_before = None
    if len(rows) == limit:
        next_before = unpinned[-1].received_at.isoformat() if unpinned and unpinned[-1].received_at else datetime.now(UTC).isoformat()
    return {"items": items, "next_before": next_before,
            "total": total, "pages": page_count(total, limit)}


def page_count(total: int, limit: int) -> int:
    return max(1, -(-total // limit))


def _own(db: Session, user: User, message_id: uuid.UUID) -> Message:
    m = db.get(Message, message_id)
    if m is None or m.user_id != user.id:
        raise HTTPException(404, "message not found")
    return m


@router.get("/{message_id}")
def get_message(message_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    m = _own(db, user, message_id)
    n = db.scalar(select(Notification).where(Notification.message_id == m.id))
    note_items = notes_service.list_for_message(db, user.id, m.id)
    out = message_json(m, db.get(GmailAccount, m.account_id), n, notes_count=len(note_items))
    out["notes"] = [notes_service.note_json(note) for note in note_items]
    # the group it was put in (when grouping is on), so the apps can open it from the mail
    from app.models import MailGroup
    on = grouping.enabled(db, user.id)
    groups = [{"id": str(g.id), "title": g.title, "custom": g.kind == "custom"} for g in db.scalars(
        select(MailGroup).join(GroupMember, GroupMember.group_id == MailGroup.id)
        .where(GroupMember.message_id == m.id, GroupMember.added_by != "removed").order_by(MailGroup.kind != "custom"))
        if g.kind == "custom" or on]
    out["groups"] = groups
    out["group_id"] = groups[0]["id"] if groups else None
    return out


@router.get("/{message_id}/thread")
def get_thread(message_id: uuid.UUID, images: bool | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """The whole conversation, fetched live from Gmail: sanitized HTML (remote images blocked
    unless `images`, and then only through the image proxy), plain text, and attachments as
    signed links. Not stored, not logged."""
    m = _own(db, user, message_id)
    return thread_json(db, user, db.get(GmailAccount, m.account_id), m.thread_id, images, m.subject)


def thread_json(db: Session, user: User, account: GmailAccount, thread_id: str, images: bool | None, fallback_subject: str | None = None) -> dict:
    if images is None:  # the user's setting (default: load, through the image proxy)
        from app import user_settings
        images = bool(user_settings.get(db, user.id)["load_remote_images"])
    if account.status != "active":
        raise HTTPException(409, f"account is {account.status}")
    try:
        thread = account_service.provider_for(account).get_thread(thread_id)
    except AuthRevoked as exc:
        account_service.mark_auth_failure(account, exc)
        db.commit()
        raise HTTPException(409, f"account is {account.status}") from exc
    except GmailError as exc:
        raise HTTPException(404 if exc.status == 404 else 502, "conversation not available") from exc
    msgs = reader.render_thread(thread, user_id=str(user.id), account_id=str(account.id), base="", images=images)
    stored = dict(db.execute(select(Message.gmail_id, Message.id).where(
        Message.account_id == account.id, Message.gmail_id.in_([x["gmail_id"] for x in msgs]))).all())
    for x in msgs:
        x["id"] = str(stored[x["gmail_id"]]) if x["gmail_id"] in stored else None
        x.pop("html")  # clients load the sandboxed document from html_url instead

    # Index any attachments in the rendered messages if stored in db
    from app import attachments
    for m_raw in thread.get("messages") or []:
        gid = m_raw.get("id")
        if gid in stored and m_raw.get("payload"):
            m_db = db.get(Message, stored[gid])
            if m_db:
                try:
                    attachments.index_attachments(db, m_db, account, m_raw["payload"])
                except Exception:
                    pass
    db.commit()

    return {"thread_id": thread_id, "account": account.label or account.email, "account_id": str(account.id),
            "subject": (msgs[0]["subject"] if msgs else fallback_subject) or "", "images": images, "messages": msgs}


@router.get("/{message_id}/body")
def get_body(message_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Plain-text body fetched live from Gmail for reading. Not stored, not logged.
    (The sandboxed HTML reader arrives in Phase 3.)"""
    m = _own(db, user, message_id)
    account = db.get(GmailAccount, m.account_id)
    if account.status != "active":
        raise HTTPException(409, f"account is {account.status}")
    try:
        full = account_service.provider_for(account).get_full(m.gmail_id)
    except AuthRevoked as exc:
        account_service.mark_auth_failure(account, exc)
        db.commit()
        raise HTTPException(409, f"account is {account.status}") from exc
    text, files = extract_body(full.get("payload", {}))
    return {"text": text.strip()[:100_000], "attachments": files}


class LikeThisIn(BaseModel):
    action: str = Field(default="silent", pattern="^(silent|digest|ignore)$")
    save: bool = True  # False returns the draft + preview without saving (for review)


@router.post("/{message_id}/like-this")
def like_this(message_id: uuid.UUID, body: LikeThisIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """One-tap "ignore mails like this": same verified sender + same subject template."""
    m = _own(db, user, message_id)
    try:
        draft = rule_tools.like_this(m, body.action)
    except rule_tools.RuleToolError as exc:
        raise HTTPException(422, str(exc)) from exc
    result = {"draft": draft, "preview": rule_tools.preview(db, user.id, draft["conditions"])}
    if body.save:
        rule = rule_tools.save_rule(db, user.id, draft, origin="one_tap")
        if body.action in ("silent", "ignore"):
            rule_tools.remember_template(db, m, body.action)
            m.status, m.priority = ("silenced" if body.action == "silent" else "ignored"), "silent"
        db.commit()
        result["rule_id"] = str(rule.id)
    return result


@router.post("/{message_id}/unsilence")
def unsilence(message_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """"Not like this" from the Silenced view."""
    m = _own(db, user, message_id)
    if m.status not in SILENCED_STATUSES:
        raise HTTPException(409, "mail is not silenced")
    result = rule_tools.unsilence(db, m)
    db.commit()
    return result



class ReadStateIn(BaseModel):
    message_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    unread: bool


@router.post("/read-state")
def set_read_state(body: ReadStateIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Read / unread for whole conversations, the way opening a mail or the read button works.
    With write access it changes Gmail too; without it, only Sift's copy (never a permission
    prompt for simply reading). Every open app of the user updates live."""
    from app import accounts as account_service
    from app import actions, events
    from app.mail.base import AuthRevoked
    from app.mail.gmail import GmailError

    msgs = list(db.scalars(select(Message).where(Message.user_id == user.id, Message.id.in_(body.message_ids))))
    if len(msgs) != len(set(body.message_ids)):
        raise HTTPException(404, "message not found")
    add, remove = (["UNREAD"], []) if body.unread else ([], ["UNREAD"])
    threads = {(m.account_id, m.thread_id) for m in msgs}
    accounts = {a.id: a for a in db.scalars(select(GmailAccount).where(GmailAccount.id.in_({a for a, _ in threads})))}
    in_gmail, local_only, changed_ids = 0, set(), []
    for account_id, thread_id in threads:
        account = accounts[account_id]
        thread_msgs = list(db.scalars(select(Message).where(Message.account_id == account_id, Message.thread_id == thread_id)))
        already = all(("UNREAD" in (m.labels or [])) == body.unread for m in thread_msgs)
        if already:
            continue  # nothing to do (e.g. opening a mail that's already read): no Gmail call
        if account_service.can_modify(account) and account.status == "active":
            try:
                account_service.provider_for(account).modify_thread(thread_id, add, remove)
                in_gmail += 1
            except AuthRevoked as exc:
                account_service.mark_auth_failure(account, exc)
                local_only.add(account.email)
            except GmailError as exc:
                if exc.status == 403:
                    account.scopes = [s for s in (account.scopes or []) if s != account_service.google_oauth.MODIFY_SCOPE]
                local_only.add(account.email)
        else:
            local_only.add(account.email)
        actions._apply_local(db, account_id, thread_id, add, remove)
        changed_ids += [m.id for m in thread_msgs]
    if changed_ids:
        events.mail_changed(db, user.id, changed_ids)
    db.commit()
    return {"unread": body.unread, "conversations": len(threads), "in_gmail": in_gmail, "sift_only": sorted(local_only)}



class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)


@router.get("/{message_id}/notes")
def list_notes(message_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    _own(db, user, message_id)
    notes_list = notes_service.list_for_message(db, user.id, message_id)
    return {"notes": [notes_service.note_json(n) for n in notes_list]}


@router.post("/{message_id}/notes", status_code=201)
def create_note(message_id: uuid.UUID, body: NoteIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    _own(db, user, message_id)
    try:
        note = notes_service.add_note(db, user.id, message_id, body.body)
    except notes_service.NoteError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    return notes_service.note_json(note)


@router.patch("/{message_id}/notes/{note_id}")
def update_note(message_id: uuid.UUID, note_id: uuid.UUID, body: NoteIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    _own(db, user, message_id)
    try:
        note = notes_service.update_note(db, user.id, message_id, note_id, body.body)
    except notes_service.NoteError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    return notes_service.note_json(note)


@router.delete("/{message_id}/notes/{note_id}")
def delete_note(message_id: uuid.UUID, note_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    _own(db, user, message_id)
    try:
        notes_service.delete_note(db, user.id, message_id, note_id)
    except notes_service.NoteError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    return {"ok": True}



class PinIn(BaseModel):
    pinned: bool | None = None


@router.post("/{message_id}/pin")
def pin_message(message_id: uuid.UUID, body: PinIn = PinIn(), user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    m = _own(db, user, message_id)
    m.pinned = not m.pinned if body.pinned is None else body.pinned
    db.commit()
    events.mail_changed(db, user.id, [m.id])
    return {"id": str(m.id), "pinned": m.pinned}


class BatchPinIn(BaseModel):
    message_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    pinned: bool


@router.post("/pin")
def batch_pin(body: BatchPinIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    msgs = list(db.scalars(select(Message).where(Message.user_id == user.id, Message.id.in_(body.message_ids))))
    if len(msgs) != len(set(body.message_ids)):
        raise HTTPException(404, "message not found")
    for m in msgs:
        m.pinned = body.pinned
    db.commit()
    events.mail_changed(db, user.id, [m.id for m in msgs])
    return {"pinned": body.pinned, "count": len(msgs)}

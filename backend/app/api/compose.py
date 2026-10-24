"""Writing mail (Phase 4): drafts, attachments, send (with undo), send later, follow-ups, reply and
forward details, and AI reply drafts.

Every draft is a Gmail draft; these endpoints read and write it in Gmail (see app/compose.py).
Creating, changing and sending drafts need the account's write access (gmail.modify, which
covers drafts and sending); without it the answer is 403 needs_write_access, like mail actions,
and the app asks for it. Reading (listing drafts, reply details) works read-only. Concurrent
saves of one draft are serialized with a Postgres advisory lock, so an autosave can't drop an
attachment being added at the same moment.
"""
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import accounts as account_service
from app import compose, demo, outbox, reader, user_settings
from app.db import get_db
from app.mail.base import AuthRevoked
from app.mail.gmail import GmailError
from app.models import FollowUp, GmailAccount, Message, Outbox, User
from app.redact import redact
from app.security import current_user

router = APIRouter(prefix="/api/v1")
GMAIL_ID = r"^[A-Za-z0-9_-]{1,64}$"


# ---- helpers -----------------------------------------------------------------------------------

def _account(db: Session, user: User, account_id: uuid.UUID, write: bool) -> GmailAccount:
    a = db.get(GmailAccount, account_id)
    if a is None or a.user_id != user.id:
        raise HTTPException(404, "account not found")
    if demo.is_demo(a) and not a.encrypted_refresh_token:
        raise HTTPException(400, "The demo account has no Gmail behind it, so it can't write or send mail")
    if a.status != "active":
        raise HTTPException(409, f"account is {a.status}")
    if write and not account_service.can_modify(a):
        raise HTTPException(403, {"code": "needs_write_access",
                                  "message": f"Sift needs your permission to write and send mail from {a.email}",
                                  "accounts": [{"id": str(a.id), "email": a.email}]})
    return a


def _gmail(db: Session, account: GmailAccount, fn):
    """Run a Gmail call, turning its failures into HTTP answers."""
    try:
        return fn(account_service.provider_for(account))
    except AuthRevoked as exc:
        account_service.mark_auth_failure(account, exc)
        db.commit()
        raise HTTPException(409, f"account is {account.status}") from exc
    except GmailError as exc:
        if exc.status == 404:
            raise HTTPException(404, "not found in Gmail (deleted or already sent?)") from exc
        if exc.status == 403:
            account.scopes = [s for s in (account.scopes or []) if s != account_service.google_oauth.MODIFY_SCOPE]
            db.commit()
            raise HTTPException(403, {"code": "needs_write_access", "message": f"Sift needs your permission to write and send mail from {account.email}",
                                      "accounts": [{"id": str(account.id), "email": account.email}]}) from exc
        raise HTTPException(502, f"Gmail error {exc.status}") from exc
    except compose.ComposeError as exc:
        raise HTTPException(422, str(exc)) from exc


def _lock(db: Session, account_id: uuid.UUID, draft_id: str) -> None:
    """Saves of one draft take turns. If another save (e.g. a large attachment) holds it past the
    database's lock timeout, answer "busy" instead of failing: the app retries on its next save."""
    try:
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"draft:{account_id}:{draft_id}"})
    except OperationalError as exc:
        db.rollback()
        raise HTTPException(409, "This draft is still being saved; try again in a moment") from exc


def _from(db: Session, user: User, account: GmailAccount) -> tuple[str, str]:
    return account.email, user_settings.get(db, user.id)["sender_name"]


def _draft_json(account: GmailAccount, draft_id: str, thread_id: str | None, d: compose.Draft, version: str | None = None) -> dict:
    return {"account_id": str(account.id), "account_email": account.email, "draft_id": draft_id, "thread_id": thread_id, "version": version,
            "to": d.to, "cc": d.cc, "bcc": d.bcc, "subject": d.subject, "body": d.body,
            "in_reply_to": d.in_reply_to, "references": d.references,
            "attachments": [{"index": i, "filename": a.filename, "mime": a.mime, "size": len(a.data)} for i, a in enumerate(d.attachments)],
            "attachments_size": sum(len(a.data) for a in d.attachments), "attachments_limit": compose.MAX_TOTAL_BYTES}


def _message(db: Session, user: User, message_id: uuid.UUID | None, account_id: uuid.UUID | None, gmail_id: str | None) -> tuple[GmailAccount, str]:
    """(account, Gmail message id) for a stored message, or for Gmail-only mail by account + id."""
    if message_id is not None:
        m = db.get(Message, message_id)
        if m is None or m.user_id != user.id:
            raise HTTPException(404, "message not found")
        return _account(db, user, m.account_id, write=False), m.gmail_id
    if account_id is None or not gmail_id:
        raise HTTPException(422, "give message_id, or account_id and gmail_id")
    return _account(db, user, account_id, write=False), gmail_id


# ---- reply / forward details -------------------------------------------------------------------

@router.get("/compose/context")
def reply_context(mode: str = Query(pattern="^(reply|reply_all|forward)$"), message_id: uuid.UUID | None = None,
                  account_id: uuid.UUID | None = None, gmail_id: str | None = Query(default=None, pattern=GMAIL_ID),
                  user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Recipients, subject, quoted text and threading headers for a reply, reply-all or forward."""
    account, gid = _message(db, user, message_id, account_id, gmail_id)
    msg = _gmail(db, account, lambda p: p.get_full(gid))
    ctx = compose.context(msg, mode, account.email)
    ctx["attachments"] = [{"filename": a.filename, "mime": a.mime, "size": a.size}
                          for a in reader.walk(msg.get("payload") or {}).attachments
                          if not (a.content_id and a.mime in reader.INLINE_IMAGE_TYPES)] if mode == "forward" else []
    return {"account_id": str(account.id), "account_email": account.email, "mode": mode, **ctx}


# ---- drafts ------------------------------------------------------------------------------------

class DraftFields(BaseModel):
    to: list[str] = Field(default_factory=list, max_length=compose.MAX_RECIPIENTS)
    cc: list[str] = Field(default_factory=list, max_length=compose.MAX_RECIPIENTS)
    bcc: list[str] = Field(default_factory=list, max_length=compose.MAX_RECIPIENTS)
    subject: str = Field(default="", max_length=compose.MAX_SUBJECT_CHARS)
    body: str = Field(default="", max_length=compose.MAX_BODY_CHARS)


class DraftIn(DraftFields):
    account_id: uuid.UUID
    thread_id: str | None = Field(default=None, pattern=GMAIL_ID)
    in_reply_to: str | None = Field(default=None, max_length=998)
    references: str | None = Field(default=None, max_length=8000)
    forward_gmail_id: str | None = Field(default=None, pattern=GMAIL_ID)  # carry the original's attachments


def _fields(body: DraftFields) -> compose.Draft:
    try:
        return compose.Draft(to=compose.addresses(body.to), cc=compose.addresses(body.cc), bcc=compose.addresses(body.bcc),
                             subject=body.subject, body=body.body)
    except compose.ComposeError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/compose/drafts")
def create_draft(body: DraftIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    account = _account(db, user, body.account_id, write=True)
    d = _fields(body)
    d.in_reply_to, d.references = body.in_reply_to, body.references
    name = _from(db, user, account)

    def work(p):
        if body.forward_gmail_id:
            d.attachments = compose.forward_attachments(p, p.get_full(body.forward_gmail_id))
        created = p.create_draft(compose.build(*name, d), body.thread_id)
        m = created.get("message", {})
        return created["id"], m.get("threadId") or body.thread_id, m.get("id")

    draft_id, thread_id, version = _gmail(db, account, work)
    return _draft_json(account, draft_id, thread_id, d, version)


@router.get("/compose/drafts")
def list_drafts(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Gmail drafts of every connected account (newest first), with Sift's schedule if any."""
    scheduled = {(r.account_id, r.draft_id): r for r in db.scalars(select(Outbox).where(Outbox.user_id == user.id, Outbox.status.in_(("scheduled", "sending"))))}
    out, failed = [], []
    accounts = list(db.scalars(select(GmailAccount).where(GmailAccount.user_id == user.id, GmailAccount.status == "active",
                                                          GmailAccount.encrypted_refresh_token.is_not(None))))

    def of_account(a: GmailAccount) -> list[dict] | None:
        # each draft's headers are one Gmail request; fetched a few at a time, not one by one
        try:
            p = account_service.provider_for(a)
            items = p.list_drafts(25)
            with ThreadPoolExecutor(max_workers=6) as pool:
                metas = list(pool.map(lambda item: p.get_draft_meta(item["id"]), items))
        except (AuthRevoked, GmailError, httpx.HTTPError):
            return None
        rows = []
        for item, meta in zip(items, metas):
            m = meta.get("message", {})
            headers = {h["name"].lower(): h["value"] for h in (m.get("payload") or {}).get("headers") or []}
            row = scheduled.get((a.id, item["id"]))
            rows.append({"account_id": str(a.id), "account_email": a.email, "draft_id": item["id"], "thread_id": m.get("threadId"),
                         "subject": headers.get("subject", ""), "to": headers.get("to", ""), "snippet": m.get("snippet", ""),
                         "updated_ms": int(m.get("internalDate") or 0), "outbox": outbox.outbox_json(row) if row else None})
        return rows

    with ThreadPoolExecutor(max_workers=4) as pool:
        for a, rows in zip(accounts, pool.map(of_account, accounts)):
            if rows is None:
                failed.append(a.email)
            else:
                out.extend(rows)
    out.sort(key=lambda x: -x["updated_ms"])
    return {"drafts": out, "failed_accounts": failed}


@router.get("/compose/drafts/{account_id}/{draft_id}")
def get_draft(account_id: uuid.UUID, draft_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    account = _account(db, user, account_id, write=False)
    _check_id(draft_id)
    raw, thread_id, version = _gmail(db, account, lambda p: p.get_draft_raw(draft_id))
    out = _draft_json(account, draft_id, thread_id, compose.parse(raw), version)
    row = db.scalar(select(Outbox).where(Outbox.account_id == account.id, Outbox.draft_id == draft_id, Outbox.status.in_(("scheduled", "sending"))))
    out["outbox"] = outbox.outbox_json(row) if row else None
    return out


def _check_id(draft_id: str) -> None:
    if not draft_id or len(draft_id) > 64 or not draft_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(404, "not found")


def _not_sending(db: Session, account: GmailAccount, draft_id: str) -> None:
    row = db.scalar(select(Outbox).where(Outbox.account_id == account.id, Outbox.draft_id == draft_id, Outbox.status.in_(("scheduled", "sending"))))
    if row is not None and (row.status == "sending" or row.send_at <= datetime.now(UTC) + timedelta(seconds=3)):
        raise HTTPException(409, "This mail is being sent")


class DraftUpdate(DraftFields):
    # The version (message id) this edit started from. When the draft changed since (another
    # device or Gmail itself saved it), the answer is 409 draft_changed with the latest draft, so
    # nobody's text is overwritten silently. Leave it out to overwrite on purpose ("keep mine").
    base_version: str | None = Field(default=None, max_length=64)


@router.put("/compose/drafts/{account_id}/{draft_id}")
def update_draft(account_id: uuid.UUID, draft_id: str, body: DraftUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Autosave: new recipients/subject/text; reply headers and attachments are kept."""
    account = _account(db, user, account_id, write=True)
    _check_id(draft_id)
    _lock(db, account.id, draft_id)
    _not_sending(db, account, draft_id)
    fields = _fields(body)
    name = _from(db, user, account)

    def work(p):
        raw, thread_id, version = p.get_draft_raw(draft_id)
        old = compose.parse(raw)
        if body.base_version and version and body.base_version != version:
            raise HTTPException(409, {"code": "draft_changed", "message": "This draft was changed on another device or in Gmail.",
                                      "draft": _draft_json(account, draft_id, thread_id, old, version)})
        fields.in_reply_to, fields.references, fields.attachments = old.in_reply_to, old.references, old.attachments
        updated = p.update_draft(draft_id, compose.build(*name, fields), thread_id)
        return thread_id, (updated.get("message") or {}).get("id")

    thread_id, version = _gmail(db, account, work)
    out = _draft_json(account, draft_id, thread_id, fields, version)
    db.commit()  # releases the lock
    return out


@router.delete("/compose/drafts/{account_id}/{draft_id}")
def discard_draft(account_id: uuid.UUID, draft_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Discard (the user's own unsent draft). A scheduled send of it is cancelled first."""
    account = _account(db, user, account_id, write=True)
    _check_id(draft_id)
    _lock(db, account.id, draft_id)
    row = db.scalar(select(Outbox).where(Outbox.account_id == account.id, Outbox.draft_id == draft_id, Outbox.status.in_(("scheduled", "sending"))))
    if row is not None:
        if row.status == "sending":
            raise HTTPException(409, "This mail is being sent")
        row.status = "cancelled"
    _gmail(db, account, lambda p: p.delete_draft(draft_id))
    db.commit()
    return {"ok": True}


@router.post("/compose/drafts/{account_id}/{draft_id}/attachments")
async def add_attachment(account_id: uuid.UUID, draft_id: str, request: Request,
                         filename: str = Query(min_length=1, max_length=255), user: User = Depends(current_user),
                         db: Session = Depends(get_db)) -> dict:
    """The file is the raw request body (Content-Type = its type), added to the Gmail draft."""
    declared = int(request.headers.get("content-length") or 0)
    if declared > compose.MAX_TOTAL_BYTES:
        raise HTTPException(413, "Attachments are limited to 25 MB in total")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > compose.MAX_TOTAL_BYTES:
            raise HTTPException(413, "Attachments are limited to 25 MB in total")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise HTTPException(422, "empty file")
    mime = compose.guess_mime(filename, (request.headers.get("content-type") or "").split(";")[0].strip())

    def sync() -> dict:
        account = _account(db, user, account_id, write=True)
        _check_id(draft_id)
        _lock(db, account.id, draft_id)
        _not_sending(db, account, draft_id)
        name = _from(db, user, account)

        def work(p):
            raw, thread_id, _ = p.get_draft_raw(draft_id)
            d = compose.parse(raw)
            d.attachments.append(compose.Attachment(compose.safe_filename(filename), mime, data))
            updated = p.update_draft(draft_id, compose.build(*name, d), thread_id)
            return thread_id, d, (updated.get("message") or {}).get("id")

        thread_id, d, version = _gmail(db, account, work)
        db.commit()
        return _draft_json(account, draft_id, thread_id, d, version)

    return await run_in_threadpool(sync)


@router.delete("/compose/drafts/{account_id}/{draft_id}/attachments/{index}")
def remove_attachment(account_id: uuid.UUID, draft_id: str, index: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    account = _account(db, user, account_id, write=True)
    _check_id(draft_id)
    _lock(db, account.id, draft_id)
    _not_sending(db, account, draft_id)
    name = _from(db, user, account)

    def work(p):
        raw, thread_id, _ = p.get_draft_raw(draft_id)
        d = compose.parse(raw)
        if not 0 <= index < len(d.attachments):
            raise HTTPException(404, "no such attachment")
        d.attachments.pop(index)
        updated = p.update_draft(draft_id, compose.build(*name, d), thread_id)
        return thread_id, d, (updated.get("message") or {}).get("id")

    thread_id, d, version = _gmail(db, account, work)
    db.commit()
    return _draft_json(account, draft_id, thread_id, d, version)


# ---- sending -----------------------------------------------------------------------------------

class SendIn(BaseModel):
    send_at: datetime | None = None  # None: now, after the undo window
    follow_up_days: int | None = Field(default=None, ge=1, le=60)

    @model_validator(mode="after")
    def _aware(self):
        if self.send_at is not None and self.send_at.tzinfo is None:
            raise ValueError("send_at needs a time zone")
        return self


@router.post("/compose/drafts/{account_id}/{draft_id}/send")
def send(account_id: uuid.UUID, draft_id: str, body: SendIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    account = _account(db, user, account_id, write=True)
    _check_id(draft_id)
    _lock(db, account.id, draft_id)
    raw, thread_id, _ = _gmail(db, account, lambda p: p.get_draft_raw(draft_id))
    d = compose.parse(raw)
    recipients = d.to + d.cc + d.bcc
    if not recipients:
        raise HTTPException(422, "Add at least one recipient")
    try:
        compose.addresses(recipients)
    except compose.ComposeError as exc:
        raise HTTPException(422, str(exc)) from exc
    undo = int(user_settings.get(db, user.id)["undo_send_seconds"])
    later = body.send_at is not None
    send_at = body.send_at.astimezone(UTC) if later else datetime.now(UTC) + timedelta(seconds=undo)
    try:
        row = outbox.schedule(db, account, draft_id, thread_id=thread_id, subject=d.subject,
                              recipients=", ".join(compose.bare(r) for r in recipients), send_at=send_at,
                              later=later, follow_up_days=body.follow_up_days)
    except outbox.OutboxError as exc:
        raise HTTPException(422 if "time" in str(exc) else 429 if "limit" in str(exc) else 409, str(exc)) from exc
    db.commit()
    if not later and undo == 0:
        outbox.send_one(row.id)  # no undo window: send right away
        db.refresh(row)
    return {**outbox.outbox_json(row), "undo_seconds": 0 if later else undo}


@router.get("/outbox")
def list_outbox(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Scheduled mail (soonest first) and the last 50 sent, failed or cancelled."""
    pending = db.scalars(select(Outbox).where(Outbox.user_id == user.id, Outbox.status.in_(("scheduled", "sending"))).order_by(Outbox.send_at))
    done = db.scalars(select(Outbox).where(Outbox.user_id == user.id, Outbox.status.in_(("sent", "failed", "cancelled")))
                      .order_by(Outbox.created_at.desc()).limit(50))
    emails = {a.id: a.email for a in db.scalars(select(GmailAccount).where(GmailAccount.user_id == user.id))}
    j = lambda r: {**outbox.outbox_json(r), "account_email": emails.get(r.account_id)}  # noqa: E731
    return {"scheduled": [j(r) for r in pending], "recent": [j(r) for r in done]}


def _outbox_call(fn, db: Session, user: User, outbox_id: uuid.UUID, *args) -> dict:
    try:
        row = fn(db, user.id, outbox_id, *args)
    except LookupError as exc:
        raise HTTPException(404, "not found") from exc
    except outbox.OutboxError as exc:
        raise HTTPException(409 if "sent" in str(exc).lower() or "scheduled" in str(exc) else 422, str(exc)) from exc
    db.commit()
    return outbox.outbox_json(row)


@router.post("/outbox/{outbox_id}/cancel")
def cancel_send(outbox_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Undo, or unschedule a send-later. The mail stays in Gmail drafts."""
    return _outbox_call(outbox.cancel, db, user, outbox_id)


@router.post("/outbox/{outbox_id}/send-now")
def send_now(outbox_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return _outbox_call(outbox.send_now, db, user, outbox_id)


class RescheduleIn(BaseModel):
    send_at: datetime

    @model_validator(mode="after")
    def _aware(self):
        if self.send_at.tzinfo is None:
            raise ValueError("send_at needs a time zone")
        return self


@router.patch("/outbox/{outbox_id}")
def reschedule(outbox_id: uuid.UUID, body: RescheduleIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return _outbox_call(outbox.reschedule, db, user, outbox_id, body.send_at.astimezone(UTC))


@router.get("/follow-ups")
def list_follow_ups(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(FollowUp).where(FollowUp.user_id == user.id).order_by(FollowUp.status != "waiting", FollowUp.due_at.desc()).limit(100))
    return {"follow_ups": [outbox.follow_up_json(f) for f in rows]}


@router.post("/follow-ups/{follow_up_id}/cancel")
def cancel_follow_up(follow_up_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    f = db.get(FollowUp, follow_up_id)
    if f is None or f.user_id != user.id:
        raise HTTPException(404, "not found")
    if f.status == "waiting":
        f.status = "cancelled"
    db.commit()
    return outbox.follow_up_json(f)


# ---- AI reply drafts ---------------------------------------------------------------------------

class AiDraftIn(BaseModel):
    message_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    gmail_id: str | None = Field(default=None, pattern=GMAIL_ID)
    instructions: str = Field(default="", max_length=600)


@router.post("/compose/ai-draft")
def ai_draft(body: AiDraftIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """A reply written with the user's own key, for the user to edit and send themselves.
    Personal identifiers are redacted before the conversation leaves the server."""
    from app.llm import service as llm
    from app.llm.base import LlmError

    account, gid = _message(db, user, body.message_id, body.account_id, body.gmail_id)
    if not llm.ai_enabled(db, user.id):
        raise HTTPException(409, "Add an API key to draft replies with AI")

    def thread_text(p) -> str:
        msg = p.get_full(gid)
        thread = p.get_thread(msg["threadId"]) if msg.get("threadId") else {"messages": [msg]}
        msgs = sorted(thread.get("messages") or [msg], key=lambda m: int(m.get("internalDate") or 0))
        msgs = [m for m in msgs if "DRAFT" not in (m.get("labelIds") or [])]
        upto = next((i for i, m in enumerate(msgs) if m.get("id") == gid), len(msgs) - 1)
        out = []
        for m in msgs[max(0, upto - 5): upto + 1]:
            r = reader.render_message(m, user_id=str(user.id), account_id=str(account.id), base="", images=False)
            who = (r["from"] or {}).get("email", "")
            me = " (the user)" if who.lower() == account.email.lower() else ""
            out.append(f"From: {(r['from'] or {}).get('name') or who}{me}\nDate: {r['date'] or ''}\nSubject: {r['subject']}\n\n{r['text'][:4000]}")
        return "\n\n-----\n\n".join(out)

    text_ = _gmail(db, account, thread_text)
    try:
        draft = llm.reply_draft(db, user.id, account.id, redact(text_), body.instructions,
                                user_settings.get(db, user.id)["sender_name"])
    except LlmError as exc:
        db.commit()
        raise HTTPException(409 if "API key" in str(exc) or "cap" in str(exc) else 502, str(exc)) from exc
    db.commit()
    return {"body": draft}

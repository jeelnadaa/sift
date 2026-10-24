"""AI on folders: filing new mail by what the AI understood, sorting into subfolders, and
explicit tasks run over a folder.

- **AI filing** (`Folder.ai_rule`): after the AI has read a new mail, it is filed in every folder
  whose rule matches: its category is listed, or (with "timeline") it joined a company timeline.
  Rules on sender/subject still run first in the normal rule engine; this runs after the AI.
- **Auto-sort** (`Folder.auto_sort`): mail filed in such a folder moves into a subfolder, created
  when missing: per company (the timeline's company or the AI's; no extra AI call), per sender
  (no AI call), or by the user's own instruction ("ai": one small AI call per mail).
- **AI tasks** (`AiTask`): "build timelines", "make to-dos" or "sort into subfolders" over the mail
  already in a folder and its subfolders. Mail the AI never read is read once (with the user's
  key, redacted, counted under the task). Token use of a task is recorded with its id, so the
  usage page can show what each task cost apart from the everyday per-mail work.
Never raises into the pipeline: a failure here leaves the mail where it was.
"""
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session

from app import folders, notify, opportunities
from app.db import get_sessionmaker
from app.models import AiTask, Folder, FolderItem, GmailAccount, Message, Opportunity, OpportunityEvent, Todo

log = logging.getLogger(__name__)
SORT_MODES = ("company", "sender", "ai")
TASK_LIMIT = 300  # mails per task run; a second run continues with what's left


# ---- auto-sort ---------------------------------------------------------------------------------

def _company(db: Session, msg: Message) -> str | None:
    ext = msg.extraction or {}
    if ext.get("opportunity_id"):
        opp = db.get(Opportunity, uuid.UUID(ext["opportunity_id"]))
        if opp is not None:
            return opp.company
    event = db.scalar(select(OpportunityEvent).where(OpportunityEvent.message_id == msg.id))
    if event is not None:
        return db.get(Opportunity, event.opportunity_id).company
    return (ext.get("company") or "").strip() or None


def _sender(msg: Message) -> str | None:
    if msg.sender_name and msg.sender_name.strip():
        return msg.sender_name.strip()
    domain = msg.authenticated_domain or (msg.sender or "").rpartition("@")[2]
    return domain or None


def subfolder_name(db: Session, folder: Folder, msg: Message, mode: str | None = None, instruction: str | None = None) -> str | None:
    mode = mode or folder.auto_sort
    if mode == "company":
        return _company(db, msg)
    if mode == "sender":
        return _sender(msg)
    if mode == "ai":
        from app.llm import service as llm

        existing = [f.name for f in db.scalars(select(Folder).where(Folder.parent_id == folder.id))]
        summary = (msg.extraction or {}).get("summary") or msg.snippet or ""
        return llm.sort_into(db, msg.user_id, msg.account_id, instruction or folder.auto_sort_instruction or "Group similar mail together",
                             existing, f"{msg.sender_name or ''} <{msg.sender or ''}>", msg.subject or "", summary)
    return None


def _child(db: Session, folder: Folder, name: str) -> Folder:
    """The subfolder called `name` (same name ignoring case, or a near-identical company name),
    created when missing."""
    children = list(db.scalars(select(Folder).where(Folder.parent_id == folder.id)))
    for c in children:
        if c.name.lower() == name.lower() or opportunities.name_score(c.name, name) >= opportunities.FUZZY:
            return c
    return folders.create(db, folder.user_id, name[:120], folder.id)


def sort_thread(db: Session, folder: Folder, msg: Message, mode: str | None = None, instruction: str | None = None) -> Folder | None:
    """Moves the mail's conversation from `folder` into the right subfolder. Returns it, or None
    when no subfolder fits (the mail stays in `folder`)."""
    name = subfolder_name(db, folder, msg, mode, instruction)
    if not name:
        return None
    try:
        child = _child(db, folder, name)
    except folders.FolderError as exc:  # too deep, or an unusable name
        log.info("auto-sort skipped for folder %s: %s", folder.id, exc)
        return None
    if child.id == folder.id:
        return None
    db.execute(insert(FolderItem).values(folder_id=child.id, account_id=msg.account_id, thread_id=msg.thread_id).on_conflict_do_nothing())
    db.execute(delete(FolderItem).where(FolderItem.folder_id == folder.id, FolderItem.account_id == msg.account_id,
                                        FolderItem.thread_id == msg.thread_id))
    return child


def sort_if_needed(db: Session, folder: Folder, msg: Message) -> None:
    """After filing into `folder`: follow its auto-sort, down nested auto-sorting folders."""
    seen = set()
    while folder is not None and folder.auto_sort in SORT_MODES and folder.id not in seen:
        seen.add(folder.id)
        folder = sort_thread(db, folder, msg)


# ---- new mail ----------------------------------------------------------------------------------

def rule_matches(rule: dict | None, msg: Message) -> bool:
    if not rule:
        return False
    ext = msg.extraction or {}
    if msg.category and msg.category in (rule.get("categories") or []):
        return True
    return bool(rule.get("timeline") and ext.get("opportunity_id"))


def on_processed(db: Session, msg: Message) -> None:
    """Pipeline hook, after classification: AI filing, then auto-sort of every auto-sorting folder
    the conversation is in (rules may have filed it before the AI ran)."""
    if msg.status != "processed":
        return
    user_folders = list(db.scalars(select(Folder).where(Folder.user_id == msg.user_id, Folder.saved_search_id.is_(None))))
    if not any(f.ai_rule or f.auto_sort for f in user_folders):
        return
    savepoint = db.begin_nested()  # a failure here must not undo the mail's own classification
    try:
        for f in user_folders:
            if rule_matches(f.ai_rule, msg):
                db.execute(insert(FolderItem).values(folder_id=f.id, account_id=msg.account_id, thread_id=msg.thread_id).on_conflict_do_nothing())
        db.flush()
        held = set(db.scalars(select(FolderItem.folder_id).where(FolderItem.account_id == msg.account_id, FolderItem.thread_id == msg.thread_id)))
        for f in user_folders:
            if f.id in held and f.auto_sort in SORT_MODES:
                sort_if_needed(db, f, msg)
        db.flush()
        savepoint.commit()
    except Exception:
        log.exception("folder AI failed for message %s; it stays where it was", msg.id)
        savepoint.rollback()


# ---- explicit tasks ------------------------------------------------------------------------------

def create_task(db: Session, user_id: uuid.UUID, folder: Folder, kind: str, include_subfolders: bool, instruction: str | None) -> AiTask:
    task = AiTask(user_id=user_id, folder_id=folder.id, folder_name=folder.name, kind=kind,
                  include_subfolders=include_subfolders, instruction=(instruction or "").strip()[:500] or None)
    db.add(task)
    db.flush()
    return task


def _messages(db: Session, task: AiTask) -> list[Message]:
    tree = folders.load_tree(db, task.user_id)
    ids = tree.subtree(task.folder_id) if task.include_subfolders else [task.folder_id]
    pairs = select(FolderItem.account_id, FolderItem.thread_id).where(FolderItem.folder_id.in_(ids))
    q = (select(Message).where(Message.user_id == task.user_id, Message.status.in_(("processed", "silenced", "ignored")),
                               func.row(Message.account_id, Message.thread_id).in_(pairs))
         .order_by(Message.received_at.desc().nullslast()).limit(TASK_LIMIT))
    return list(db.scalars(q))


def _read(db: Session, msg: Message) -> bool:
    """Make sure the AI has read this mail (extraction from the AI). Returns False when it can't
    (AI off, cap reached, mail gone)."""
    if (msg.extraction or {}).get("source") == "llm":
        return True
    from app import accounts as account_service
    from app.llm import service as llm
    from app.mail.message import clean_body, extract_body
    from app.redact import redact

    if not llm.ai_enabled(db, msg.user_id) or not llm.under_cap(db, msg.user_id):
        return False
    account = db.get(GmailAccount, msg.account_id)
    try:
        body, _ = extract_body(account_service.provider_for(account).get_full(msg.gmail_id).get("payload", {}))
    except Exception:  # noqa: BLE001  (deleted in Gmail, account revoked…)
        return False
    opp_text, opp_keys = opportunities.prompt_list(opportunities.active(db, msg.user_id))
    ext = llm.extract(db, msg.user_id, msg.account_id, msg.sender or "", msg.subject or "", redact(clean_body(body)),
                      msg.received_at, opp_text, list(opp_keys))
    if not ext or ext.get("source") != "llm":
        return False
    ext["opportunity_keys"] = {k: str(o.id) for k, o in opp_keys.items()}
    msg.extraction = {**(msg.extraction or {}), **ext}
    if msg.category in (None, "other"):
        msg.category = ext.get("category")
    return True


def _timeline(db: Session, msg: Message) -> bool:
    from app.pipeline import _timeline_and_todos

    if db.scalar(select(OpportunityEvent).where(OpportunityEvent.message_id == msg.id)) is not None:
        return False
    ext = dict(msg.extraction or {})
    if not (ext.get("company") or ext.get("opportunity") not in (None, "none", "new", "unsure")):
        return False
    if ext.get("company") and ext.get("opportunity") in (None, "none", "unsure"):
        ext["opportunity"] = "new"  # the user asked for timelines here: start one rather than ask
    msg.extraction = _timeline_and_todos(db, msg, ext, todos_too=False, force_timeline=True)
    return bool(msg.extraction.get("opportunity_id"))


def _todo(db: Session, msg: Message) -> bool:
    from app.pipeline import _timeline_and_todos

    ext = msg.extraction or {}
    if not ext.get("action_needed") or db.scalar(select(Todo).where(Todo.message_id == msg.id)) is not None:
        return False
    msg.extraction = _timeline_and_todos(db, msg, ext, timeline_too=False)
    return bool(msg.extraction.get("todo_id"))


def run_task(task_id: uuid.UUID) -> None:
    """Worker job. Commits after every mail, so progress shows and a crash loses little."""
    from app.llm import service as llm

    with get_sessionmaker()() as db:
        task = db.get(AiTask, task_id)
        if task is None or task.status not in ("queued", "running"):
            return
        folder = db.get(Folder, task.folder_id) if task.folder_id else None
        if folder is None:
            task.status, task.note, task.finished_at = "failed", "The folder was deleted", datetime.now(UTC)
            db.commit()
            return
        task.status = "running"
        msgs = _messages(db, task)
        task.total, task.done, task.changed = len(msgs), 0, 0
        db.commit()
        token = llm.current_task.set(task.id)
        try:
            unread = 0
            from app.locks import LockBusy, user_lock

            for msg in msgs:
                try:
                    with user_lock(task.user_id, wait_seconds=600):  # takes turns with new mail (app.locks)
                        result = _one(db, task, folder, msg)
                except LockBusy:
                    task.note = "Stopped: mail processing stayed busy. Run it again."
                    task.status = "stopped"
                    break
                if result == "unread":
                    unread += 1
                    if llm.ai_enabled(db, task.user_id) and not llm.under_cap(db, task.user_id):
                        task.note = "Stopped: daily token cap reached. Run it again tomorrow to continue."
                        task.status = "stopped"
                        break
                task.done += 1
                db.commit()
            if task.status == "running":
                task.status = "done"
                if unread:
                    task.note = f"{unread} mail{'s' if unread != 1 else ''} couldn't be read (AI off, or no longer in Gmail)."
        except Exception as exc:  # noqa: BLE001
            log.exception("AI task %s failed", task.id)
            db.rollback()
            task = db.get(AiTask, task_id)
            task.status, task.note = "failed", f"Something went wrong ({type(exc).__name__}). Nothing was lost; run it again."
        finally:
            llm.current_task.reset(token)
        task.finished_at = datetime.now(UTC)
        tokens = task_tokens(db, task.id)
        what = {"timelines": "mail joined company timelines", "todos": "to-dos made", "sort": "mail moved into subfolders"}[task.kind]
        notify.send_system(db, task.user_id, f"AI task finished: {task.folder_name}",
                           f"{task.changed} {what} from {task.done} mail{'s' if task.done != 1 else ''} · {tokens:,} tokens.")
        db.commit()


def _one(db: Session, task: AiTask, folder: Folder, msg: Message) -> str:
    """One mail of a task. Returns "changed", "same" or "unread" (the AI couldn't read it)."""
    try:
        db.refresh(msg)  # another job may have changed it while this task waited for its turn
    except InvalidRequestError:  # deleted meanwhile
        return "same"
    if task.kind == "sort":
        holder = folder
        if task.include_subfolders and not db.scalar(select(FolderItem).where(
                FolderItem.folder_id == folder.id, FolderItem.account_id == msg.account_id, FolderItem.thread_id == msg.thread_id)):
            holder = None  # already in a subfolder: leave it
        mode = "ai" if task.instruction else (folder.auto_sort or "company")
        if holder is not None and (mode != "company" or _read(db, msg)):
            if sort_thread(db, holder, msg, mode, task.instruction):
                task.changed += 1
                return "changed"
        return "same"
    if not _read(db, msg):
        return "unread"
    if _timeline(db, msg) if task.kind == "timelines" else _todo(db, msg):
        task.changed += 1
        return "changed"
    return "same"


def task_tokens(db: Session, task_id: uuid.UUID) -> int:
    from app.models import TokenUsage

    return int(db.scalar(select(func.coalesce(func.sum(TokenUsage.input_tokens + TokenUsage.output_tokens), 0))
                         .where(TokenUsage.task_id == task_id)) or 0)


def task_json(db: Session, t: AiTask) -> dict:
    return {"id": str(t.id), "folder_id": str(t.folder_id) if t.folder_id else None, "folder_name": t.folder_name, "kind": t.kind,
            "include_subfolders": t.include_subfolders, "instruction": t.instruction, "status": t.status, "total": t.total,
            "done": t.done, "changed": t.changed, "note": t.note, "tokens": task_tokens(db, t.id),
            "created_at": t.created_at.isoformat(), "finished_at": t.finished_at.isoformat() if t.finished_at else None}

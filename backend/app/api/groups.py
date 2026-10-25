"""Grouping API (brief sections 13 and 21): the opt-in answer, groups and their controls."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import folders, grouping, jobs, rule_tools
from app.api.messages import message_json
from app.db import get_db
from app.models import GmailAccount, GroupPreference, MailGroup, MailTag, Tag, User
from app.security import current_user

router = APIRouter(prefix="/api/v1")


@router.get("/grouping")
def grouping_status(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return grouping.status(db, user.id)


class AnswerIn(BaseModel):
    answer: str = Field(pattern="^(yes|no|dismissed)$")


@router.post("/grouping")
def grouping_answer(body: AnswerIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """The first-open prompt's answer, or the Settings switch. Yes groups the last 30 days."""
    turned_on = grouping.answer(db, user.id, body.answer)
    db.commit()
    if turned_on:
        jobs.enqueue_sync("grouping_backfill", {"user_id": str(user.id)}, dedupe_key=f"grouping:{user.id}")
    return grouping.status(db, user.id)


def _on(db: Session, user: User) -> None:
    if not grouping.enabled(db, user.id):
        raise HTTPException(409, "grouping is off")


def _group(db: Session, user: User, group_id: uuid.UUID) -> MailGroup:
    try:
        g = grouping.own(db, user.id, group_id)
    except grouping.GroupError as exc:
        raise HTTPException(404, str(exc)) from exc
    if g.kind != "custom":
        _on(db, user)  # automatic groups exist only while grouping is on; custom groups always
    return g


def _run(db: Session, fn, *args):
    try:
        out = fn(*args)
    except (grouping.GroupError, folders.FolderError, rule_tools.RuleToolError) as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    return out


@router.get("/groups")
def list_groups(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    """Your custom groups first (even empty, even with grouping off), then automatic ones."""
    custom = list(db.scalars(select(MailGroup).where(MailGroup.user_id == user.id, MailGroup.kind == "custom")
                             .order_by(MailGroup.last_activity_at.desc().nulls_last(), MailGroup.created_at.desc())))
    auto = []
    if grouping.enabled(db, user.id):
        shown = grouping.shown_group_ids(db, user.id)
        auto = list(db.scalars(select(MailGroup).where(MailGroup.id.in_(shown), MailGroup.kind != "custom")
                               .order_by(MailGroup.last_activity_at.desc())))
    return [grouping.group_json(g, grouping.members(db, g)) for g in custom + auto]


class NewGroupIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    query: str | None = Field(default=None, max_length=500)  # Sift search: free, checked by Sift
    instruction: str | None = Field(default=None, max_length=300)  # plain words: checked by the AI on new mail
    fill: bool = False  # also put matching mail that is already in Sift in it now
    fill_query: str | None = Field(default=None, max_length=500)  # which existing mail to look at (default: the search, or the last 30 days)


def _criteria(db: Session, user: User, query: str | None, instruction: str | None) -> tuple[str | None, str | None]:
    from app import places
    try:
        return places.check_query(db, user.id, query), places.check_instruction(instruction)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/groups", status_code=201)
def create_group(body: NewGroupIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """A group of your own. New mail joins when it matches the search and/or the AI says it fits
    the description; it can sit in several groups and folders at once (app/places.py)."""
    query, instruction = _criteria(db, user, body.query, body.instruction)
    if instruction:
        from app.llm import service as llm
        if not llm.ai_enabled(db, user.id):
            raise HTTPException(409, "A description needs your AI key; use a search instead, or add a key in Settings")
    title = " ".join(body.title.split())[:200]
    if db.scalar(select(MailGroup.id).where(MailGroup.user_id == user.id, MailGroup.kind == "custom",
                                            func.lower(MailGroup.title) == title.lower())):
        raise HTTPException(409, f"You already have a group called {title}")
    g = MailGroup(user_id=user.id, title=title, kind="custom", key=f"custom:{uuid.uuid4().hex}",
                  query=query, instruction=instruction, collapsed=True)
    db.add(g)
    db.flush()
    task = _start_fill(db, user, g, body.fill_query) if body.fill else None
    db.commit()
    return {**grouping.group_json(g, grouping.members(db, g)), "fill_task": task}


def _start_fill(db: Session, user: User, g: MailGroup, fill_query: str | None) -> dict | None:
    """Fills a custom group with mail already in Sift: searches at once (free), descriptions as an AI task."""
    from app import folder_ai, places
    scope = " ".join((fill_query or "").split()) or g.query or "newer_than:30d"
    if not (g.query or g.instruction):
        raise HTTPException(422, "give the group a search or a description to fill it")
    try:
        places.check_query(db, user.id, scope)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not g.instruction:  # search only: no AI, done now
        n = folder_ai.fill_now(db, user.id, "group", g.id, scope, g.query)
        return {"status": "done", "changed": n}
    task = folder_ai.create_fill_task(db, user.id, "group", g.id, g.title, scope)
    db.flush()
    jobs.enqueue_pg(db, "ai_task", {"task_id": str(task.id)}, dedupe_key=f"ai_task:{task.id}")
    return folder_ai.task_json(db, task)


class FillIn(BaseModel):
    query: str | None = Field(default=None, max_length=500)


@router.post("/groups/{group_id}/fill")
def fill_group(group_id: uuid.UUID, body: FillIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    g = _group(db, user, group_id)
    if g.kind != "custom":
        raise HTTPException(422, "only your own groups can be filled")
    out = _start_fill(db, user, g, body.query)
    db.commit()
    return out


@router.delete("/groups/{group_id}", status_code=204)
def delete_group(group_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    """Removes the group only; its mail stays where it is."""
    g = _group(db, user, group_id)
    db.delete(g)
    db.commit()


class AddIn(BaseModel):
    message_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


@router.post("/groups/{group_id}/add")
def add_members(group_id: uuid.UUID, body: AddIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Put mail in a group by hand (it can be in other groups and folders too)."""
    from app import places
    from app.models import GroupMember, Message
    g = _group(db, user, group_id)
    n = 0
    for mid in body.message_ids:
        m = db.get(Message, mid)
        if m is None or m.user_id != user.id:
            continue
        existing = db.get(GroupMember, {"group_id": g.id, "message_id": m.id})
        if existing is not None and existing.added_by == "removed":
            existing.added_by, n = "user", n + 1  # taken out before, put back by hand
        elif places.add(db, "group", g.id, m, by="user"):
            n += 1
    db.commit()
    return {"added": n, **grouping.group_json(g, grouping.members(db, g))}


@router.get("/groups/{group_id}")
def get_group(group_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    g = _group(db, user, group_id)
    ms = grouping.members(db, g)
    accounts = {a.id: a for a in db.scalars(select(GmailAccount).where(GmailAccount.user_id == user.id))}
    return {**grouping.group_json(g, ms), "items": [message_json(m, accounts.get(m.account_id)) for m in ms]}


class GroupPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    muted: bool | None = None
    collapsed: bool | None = None
    query: str | None = Field(default=None, max_length=500)  # custom groups: "" clears
    instruction: str | None = Field(default=None, max_length=300)


@router.patch("/groups/{group_id}")
def edit_group(group_id: uuid.UUID, body: GroupPatch, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    g = _group(db, user, group_id)
    if body.title is not None:
        g.title = " ".join(body.title.split())[:200] or g.title
    if body.muted is not None:
        g.muted = body.muted
    if body.collapsed is not None:
        g.collapsed = body.collapsed
    if body.query is not None or body.instruction is not None:
        if g.kind != "custom":
            raise HTTPException(422, "only your own groups have criteria")
        q, i = _criteria(db, user, body.query if body.query is not None else g.query,
                         body.instruction if body.instruction is not None else g.instruction)
        g.query, g.instruction = q, i
    db.commit()
    return grouping.group_json(g, grouping.members(db, g))


class CollapseIn(BaseModel):
    collapsed: bool


@router.post("/groups/collapse-all")
def collapse_all(body: CollapseIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    _on(db, user)
    n = 0
    for g in db.scalars(select(MailGroup).where(MailGroup.user_id == user.id)):
        g.collapsed, n = body.collapsed, n + 1
    db.commit()
    return {"updated": n}


class MessageIn(BaseModel):
    message_id: uuid.UUID


@router.post("/groups/{group_id}/remove")
def remove_member(group_id: uuid.UUID, body: MessageIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    g = _group(db, user, group_id)
    _run(db, grouping.remove_member, db, g, body.message_id)


class SplitIn(BaseModel):
    message_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    title: str | None = Field(default=None, max_length=200)


@router.post("/groups/{group_id}/split")
def split(group_id: uuid.UUID, body: SplitIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    g = _group(db, user, group_id)
    new = _run(db, grouping.split, db, g, body.message_ids, body.title)
    return grouping.group_json(new, grouping.members(db, new))


class MergeIn(BaseModel):
    target_id: uuid.UUID


@router.post("/groups/{group_id}/merge")
def merge(group_id: uuid.UUID, body: MergeIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    source, target = _group(db, user, group_id), _group(db, user, body.target_id)
    _run(db, grouping.merge, db, source, target)
    return grouping.group_json(target, grouping.members(db, target))


class FileIn(BaseModel):
    folder_id: uuid.UUID


@router.post("/groups/{group_id}/file")
def file_group(group_id: uuid.UUID, body: FileIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """File every thread in the group into a folder."""
    g = _group(db, user, group_id)

    def run():
        f = folders.own(db, user.id, body.folder_id)
        threads = {(m.account_id, m.thread_id) for m in grouping.members(db, g)}
        return sum(folders.file_thread(db, user.id, f, a, t) for a, t in threads)

    return {"filed": _run(db, run)}


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


@router.post("/groups/{group_id}/tag")
def tag_group(group_id: uuid.UUID, body: TagIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    g = _group(db, user, group_id)
    name = " ".join(body.name.split())
    tag = db.scalar(select(Tag).where(Tag.user_id == user.id, Tag.name == name))
    if tag is None:
        tag = Tag(user_id=user.id, name=name)
        db.add(tag)
        db.flush()
    ms = grouping.members(db, g)
    if ms:
        db.execute(insert(MailTag).values([{"tag_id": tag.id, "message_id": m.id} for m in ms]).on_conflict_do_nothing())
    db.commit()
    return {"tagged": len(ms), "tag": name}


class RuleIn(BaseModel):
    action: str = Field(pattern="^(silent|digest|file)$")
    folder_id: uuid.UUID | None = None
    save: bool = False


@router.post("/groups/{group_id}/rule")
def rule_from_group(group_id: uuid.UUID, body: RuleIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """A rule for mail like this group's latest mail: silence, digest, or "file mail like this here"."""
    g = _group(db, user, group_id)
    ms = grouping.members(db, g)
    if not ms:
        raise HTTPException(422, "the group is empty")
    latest = ms[0]

    def draft():
        if body.action == "file":
            if body.folder_id is None:
                raise rule_tools.RuleToolError("pick a folder")
            f = folders.own(db, user.id, body.folder_id)
            d = rule_tools.like_this(latest, "llm")
            d["name"], d["action"] = f"File in {f.name}: {g.title}"[:200], {"type": "llm", "folder_id": str(f.id)}
        else:
            d = rule_tools.like_this(latest, body.action)
        if g.kind not in ("template",):
            # a group of varied subjects: match the sender only, not the latest subject's template
            d["conditions"] = {"all": [rule_tools.sender_condition(latest)]}
        return d

    try:
        d = draft()
    except (rule_tools.RuleToolError, folders.FolderError) as exc:
        raise HTTPException(422, str(exc)) from exc
    result = {"draft": d, "preview": rule_tools.preview(db, user.id, d["conditions"])}
    if body.save:
        result["rule_id"] = str(rule_tools.save_rule(db, user.id, d, origin="one_tap").id)
        db.commit()
    return result


@router.get("/grouping/preferences")
def preferences(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [{"sender_or_domain": p.sender_or_domain, "mode": p.mode}
            for p in db.scalars(select(GroupPreference).where(GroupPreference.user_id == user.id).order_by(GroupPreference.sender_or_domain))]


class PreferenceIn(BaseModel):
    sender_or_domain: str = Field(min_length=1, max_length=320)
    mode: str | None = Field(default=None, pattern="^(always|never)$")  # None clears it


@router.put("/grouping/preferences")
def set_preference(body: PreferenceIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    _run(db, grouping.set_preference, db, user.id, body.sender_or_domain, body.mode)
    return preferences(user, db)

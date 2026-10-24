"""Grouping API (brief sections 13 and 21): the opt-in answer, groups and their controls."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
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
    _on(db, user)
    try:
        return grouping.own(db, user.id, group_id)
    except grouping.GroupError as exc:
        raise HTTPException(404, str(exc)) from exc


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
    _on(db, user)
    shown = grouping.shown_group_ids(db, user.id)
    rows = db.scalars(select(MailGroup).where(MailGroup.id.in_(shown)).order_by(MailGroup.last_activity_at.desc()))
    return [grouping.group_json(g, grouping.members(db, g)) for g in rows]


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


@router.patch("/groups/{group_id}")
def edit_group(group_id: uuid.UUID, body: GroupPatch, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    g = _group(db, user, group_id)
    if body.title is not None:
        g.title = " ".join(body.title.split())[:200] or g.title
    if body.muted is not None:
        g.muted = body.muted
    if body.collapsed is not None:
        g.collapsed = body.collapsed
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

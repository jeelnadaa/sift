"""Folders (brief section 18): a nested tree in our database, holding threads (account id +
thread id), so new replies land in the folder by themselves. Filing never touches Gmail.

Trees are small (tens of folders), so tree math (depth, cycles, roll-ups) is done in Python
on the user's whole folder list rather than with recursive SQL.
"""
import uuid
from dataclasses import dataclass

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Folder, FolderItem, GmailAccount, Message, Rule, Setting

MAX_FOLDER_DEPTH = 10  # brief section 18: one constant, easy to raise later
NOTIFY_MODES = ("default", "always", "mute")
VIEW_STATUSES = ("processed", "silenced", "ignored")  # a folder shows what was filed, silenced or not


class FolderError(ValueError):
    pass


@dataclass
class Tree:
    by_id: dict[uuid.UUID, Folder]

    def children(self, parent_id: uuid.UUID | None) -> list[Folder]:
        return sorted((f for f in self.by_id.values() if f.parent_id == parent_id), key=lambda f: (f.position, f.name.lower()))

    def depth(self, folder_id: uuid.UUID | None) -> int:
        """Root folders are depth 1; None (the top) is 0."""
        d, seen = 0, set()
        while folder_id is not None and folder_id not in seen:
            seen.add(folder_id)
            d += 1
            folder_id = self.by_id[folder_id].parent_id
        return d

    def subtree(self, folder_id: uuid.UUID) -> list[uuid.UUID]:
        out, stack = [], [folder_id]
        while stack:
            fid = stack.pop()
            out.append(fid)
            stack.extend(f.id for f in self.by_id.values() if f.parent_id == fid)
        return out

    def height(self, folder_id: uuid.UUID) -> int:
        """Levels from this folder down to its deepest subfolder (a leaf is 1)."""
        kids = [f.id for f in self.by_id.values() if f.parent_id == folder_id]
        return 1 + max((self.height(k) for k in kids), default=0)

    def path(self, folder_id: uuid.UUID) -> list[Folder]:
        out = []
        while folder_id is not None:
            f = self.by_id[folder_id]
            out.append(f)
            folder_id = f.parent_id
        return list(reversed(out))


def load_tree(db: Session, user_id: uuid.UUID) -> Tree:
    return Tree({f.id: f for f in db.scalars(select(Folder).where(Folder.user_id == user_id))})


def own(db: Session, user_id: uuid.UUID, folder_id: uuid.UUID | str) -> Folder:
    try:
        f = db.get(Folder, uuid.UUID(str(folder_id)))
    except ValueError:
        f = None
    if f is None or f.user_id != user_id:
        raise FolderError("folder not found")
    return f


def _clean_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise FolderError("folder name can't be empty")
    if len(name) > 120:
        raise FolderError("folder name is too long (120 characters at most)")
    return name


def _next_position(tree: Tree, parent_id: uuid.UUID | None) -> int:
    return max((f.position for f in tree.children(parent_id)), default=-1) + 1


def create(db: Session, user_id: uuid.UUID, name: str, parent_id: uuid.UUID | None = None,
           color: str | None = None, icon: str | None = None) -> Folder:
    tree = load_tree(db, user_id)
    if parent_id is not None:
        parent = own(db, user_id, parent_id)
        if parent.saved_search_id is not None:
            raise FolderError("a smart folder can't hold other folders")
        if tree.depth(parent.id) + 1 > MAX_FOLDER_DEPTH:
            raise FolderError(f"folders can be nested {MAX_FOLDER_DEPTH} levels deep at most")
    f = Folder(user_id=user_id, parent_id=parent_id, name=_clean_name(name), color=color, icon=icon,
               position=_next_position(tree, parent_id))
    db.add(f)
    db.flush()
    return f


def edit(folder: Folder, *, name: str | None = None, color: str | None = None, icon: str | None = None,
         pinned: bool | None = None, notify_mode: str | None = None, clear: tuple[str, ...] = ()) -> Folder:
    if name is not None:
        folder.name = _clean_name(name)
    if color is not None or "color" in clear:
        folder.color = color
    if icon is not None or "icon" in clear:
        folder.icon = icon
    if pinned is not None:
        folder.pinned = pinned
    if notify_mode is not None:
        if notify_mode not in NOTIFY_MODES:
            raise FolderError(f"notify mode must be one of {', '.join(NOTIFY_MODES)}")
        folder.notify_mode = notify_mode
    return folder


def _place(tree: Tree, folder: Folder, parent_id: uuid.UUID | None, position: int | None) -> None:
    """Put `folder` among `parent_id`'s children at `position` (end if None), renumbering siblings."""
    siblings = [f for f in tree.children(parent_id) if f.id != folder.id]
    position = len(siblings) if position is None else max(0, min(position, len(siblings)))
    siblings.insert(position, folder)
    for i, f in enumerate(siblings):
        f.position = i
    folder.parent_id = parent_id


def move(db: Session, user_id: uuid.UUID, folder: Folder, parent_id: uuid.UUID | None, position: int | None = None) -> Folder:
    """Move a folder with everything in it; also used to reorder siblings (same parent)."""
    tree = load_tree(db, user_id)
    if parent_id is not None:
        parent = own(db, user_id, parent_id)
        if parent.id in tree.subtree(folder.id):
            raise FolderError("a folder can't go inside itself or one of its own subfolders")
        if parent.saved_search_id is not None:
            raise FolderError("a smart folder can't hold other folders")
        if tree.depth(parent.id) + tree.height(folder.id) > MAX_FOLDER_DEPTH:
            raise FolderError(f"that would nest folders more than {MAX_FOLDER_DEPTH} levels deep")
    _place(tree, folder, parent_id, position)
    db.flush()
    return folder


def _repoint_rules(db: Session, user_id: uuid.UUID, old_ids: set[uuid.UUID], new_id: uuid.UUID | None) -> int:
    """Rules that file into a removed folder file into `new_id` instead, or stop filing (the
    rest of the rule keeps working). Returns how many rules changed."""
    old = {str(i) for i in old_ids}
    changed = 0
    for r in db.scalars(select(Rule).where(Rule.user_id == user_id)):
        if str((r.action or {}).get("folder_id")) in old:
            action = dict(r.action)
            if new_id is None:
                action.pop("folder_id")
            else:
                action["folder_id"] = str(new_id)
            r.action = action
            changed += 1
    return changed


def merge(db: Session, user_id: uuid.UUID, source: Folder, target: Folder) -> dict:
    """Everything in `source` (mail and subfolders) goes into `target`; `source` is removed."""
    tree = load_tree(db, user_id)
    if target.id in tree.subtree(source.id):
        raise FolderError("a folder can't merge into itself or one of its own subfolders")
    if source.saved_search_id is not None or target.saved_search_id is not None:
        raise FolderError("smart folders can't be merged")
    kids = tree.children(source.id)
    if kids and tree.depth(target.id) + max(tree.height(k.id) for k in kids) > MAX_FOLDER_DEPTH:
        raise FolderError(f"that would nest folders more than {MAX_FOLDER_DEPTH} levels deep")
    items = list(db.execute(select(FolderItem.account_id, FolderItem.thread_id).where(FolderItem.folder_id == source.id)))
    if items:
        db.execute(insert(FolderItem).values([{"folder_id": target.id, "account_id": a, "thread_id": t} for a, t in items])
                   .on_conflict_do_nothing())
    for k in kids:
        _place(tree, k, target.id, None)
    rules = _repoint_rules(db, user_id, {source.id}, target.id)
    db.delete(source)
    db.flush()
    return {"moved_threads": len(items), "moved_folders": len(kids), "rules_updated": rules}


def remove(db: Session, user_id: uuid.UUID, folder: Folder, subfolders: str) -> dict:
    """Delete the folder and its filing. Mail is never deleted. `subfolders` is "delete"
    (they go too) or "move_up" (they move one level up)."""
    if subfolders not in ("delete", "move_up"):
        raise FolderError("subfolders must be delete or move_up")
    tree = load_tree(db, user_id)
    kids = tree.children(folder.id)
    if subfolders == "move_up":
        for k in kids:
            _place(tree, k, folder.parent_id, None)
        gone = {folder.id}
    else:
        gone = set(tree.subtree(folder.id))
    rules = _repoint_rules(db, user_id, gone, None)
    db.flush()
    db.execute(delete(Folder).where(Folder.id.in_(gone)))  # folder_items cascade
    return {"deleted_folders": len(gone), "rules_updated": rules}


# ---- filing ------------------------------------------------------------------------------------

def file_thread(db: Session, user_id: uuid.UUID, folder: Folder, account_id: uuid.UUID, thread_id: str) -> bool:
    """Returns False when it was already there."""
    if folder.saved_search_id is not None:
        raise FolderError("mail can't be filed into a smart folder by hand")
    account = db.get(GmailAccount, account_id)
    if account is None or account.user_id != user_id:
        raise FolderError("account not found")
    added = db.execute(insert(FolderItem).values(folder_id=folder.id, account_id=account_id, thread_id=thread_id)
                       .on_conflict_do_nothing().returning(FolderItem.id)).scalar() is not None
    remember_last_used(db, user_id, folder.id)
    return added


def unfile_thread(db: Session, folder: Folder, account_id: uuid.UUID, thread_id: str) -> bool:
    res = db.execute(delete(FolderItem).where(FolderItem.folder_id == folder.id, FolderItem.account_id == account_id,
                                              FolderItem.thread_id == thread_id))
    return res.rowcount > 0


def remember_last_used(db: Session, user_id: uuid.UUID, folder_id: uuid.UUID) -> None:
    """For the one-tap "Move to last used folder". Internal, so not in user_settings.EDITABLE."""
    row = db.scalar(select(Setting).where(Setting.user_id == user_id, Setting.account_id.is_(None)))
    if row is None:
        row = Setting(user_id=user_id, account_id=None, data={})
        db.add(row)
    row.data = {**row.data, "last_folder_id": str(folder_id)}


def last_used(db: Session, user_id: uuid.UUID) -> Folder | None:
    row = db.scalar(select(Setting).where(Setting.user_id == user_id, Setting.account_id.is_(None)))
    fid = (row.data if row else {}).get("last_folder_id")
    if not fid:
        return None
    try:
        return own(db, user_id, fid)
    except FolderError:
        return None


def folders_for_thread(db: Session, account_id: uuid.UUID, thread_id: str) -> list[Folder]:
    return list(db.scalars(select(Folder).join(FolderItem, FolderItem.folder_id == Folder.id)
                           .where(FolderItem.account_id == account_id, FolderItem.thread_id == thread_id)))


def notify_mode_for(db: Session, msg: Message) -> str:
    """The thread's folders decide: "always" wins over "mute" (when two folders disagree,
    Sift errs on the side of telling the user), otherwise "default"."""
    modes = set(db.scalars(select(Folder.notify_mode).join(FolderItem, FolderItem.folder_id == Folder.id)
                           .where(FolderItem.account_id == msg.account_id, FolderItem.thread_id == msg.thread_id)))
    if "always" in modes:
        return "always"
    return "mute" if "mute" in modes else "default"


# ---- reading -----------------------------------------------------------------------------------

def _counts(db: Session, user_id: uuid.UUID) -> tuple[dict, dict]:
    """Per folder: threads filed, and threads with unread mail (local labels, kept in step with Gmail)."""
    threads = dict(db.execute(select(FolderItem.folder_id, func.count()).join(Folder, Folder.id == FolderItem.folder_id)
                              .where(Folder.user_id == user_id).group_by(FolderItem.folder_id)).all())
    unread_threads = (
        select(FolderItem.folder_id, func.count(func.distinct(Message.thread_id)))
        .join(Folder, Folder.id == FolderItem.folder_id)
        .join(Message, and_(Message.account_id == FolderItem.account_id, Message.thread_id == FolderItem.thread_id))
        .where(Folder.user_id == user_id, Message.labels.contains(["UNREAD"]), Message.status != "duplicate")
        .group_by(FolderItem.folder_id)
    )
    return threads, dict(db.execute(unread_threads).all())


def folder_json(f: Folder, threads: int = 0, unread: int = 0, unread_total: int = 0, children: list | None = None) -> dict:
    return {
        "id": str(f.id), "parent_id": str(f.parent_id) if f.parent_id else None, "name": f.name, "color": f.color,
        "icon": f.icon, "position": f.position, "pinned": f.pinned, "notify_mode": f.notify_mode,
        "smart": f.saved_search_id is not None, "threads": threads, "unread": unread, "unread_total": unread_total,
        "children": children if children is not None else [],
    }


def tree_json(db: Session, user_id: uuid.UUID) -> dict:
    """Nested tree. Unread counts roll up to parents; pinned roots come first."""
    tree = load_tree(db, user_id)
    threads, unread = _counts(db, user_id)

    def node(f: Folder) -> dict:
        kids = [node(k) for k in tree.children(f.id)]
        total = unread.get(f.id, 0) + sum(k["unread_total"] for k in kids)
        return folder_json(f, threads.get(f.id, 0), unread.get(f.id, 0), total, kids)

    roots = tree.children(None)
    roots.sort(key=lambda f: not f.pinned)  # stable: keeps position order within pinned / unpinned
    last = last_used(db, user_id)
    return {"folders": [node(f) for f in roots], "max_depth": MAX_FOLDER_DEPTH,
            "last_used_id": str(last.id) if last else None}


def thread_rows(db: Session, user_id: uuid.UUID, folder: Folder, include_subfolders: bool = False,
                q: str | None = None, before=None, limit: int = 50) -> tuple[list[Message], list[Folder], int]:
    """Latest message of each thread in the folder (and its subfolders), newest first.
    `q` is a plain words-in-sender/subject/snippet search; full search arrives in Phase 3."""
    tree = load_tree(db, user_id)
    ids = tree.subtree(folder.id) if include_subfolders else [folder.id]
    filed = select(FolderItem.account_id, FolderItem.thread_id).where(FolderItem.folder_id.in_(ids)).distinct().subquery()
    latest = (
        select(Message.id, func.row_number().over(partition_by=(Message.account_id, Message.thread_id),
                                                  order_by=Message.received_at.desc().nulls_last()).label("rn"))
        .join(filed, and_(Message.account_id == filed.c.account_id, Message.thread_id == filed.c.thread_id))
        .where(Message.user_id == user_id, Message.status.in_(VIEW_STATUSES))
    )
    if q:
        for word in q.split()[:8]:
            like = f"%{word.replace('%', '').replace('_', '')}%"
            latest = latest.where(or_(Message.subject.ilike(like), Message.sender.ilike(like),
                                      Message.sender_name.ilike(like), Message.snippet.ilike(like)))
    latest = latest.subquery()
    stmt = select(Message).join(latest, and_(Message.id == latest.c.id, latest.c.rn == 1))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if before is not None:
        stmt = stmt.where(Message.received_at < before)
    rows = list(db.scalars(stmt.order_by(Message.received_at.desc().nulls_last()).limit(limit)))
    return rows, tree.path(folder.id), total


def mark_thread_counts(db: Session, user_id: uuid.UUID, rows: list[Message]) -> dict[tuple, tuple[int, int]]:
    """(account, thread) -> (messages, unread) for thread rows."""
    if not rows:
        return {}
    keys = {(m.account_id, m.thread_id) for m in rows}
    stmt = (select(Message.account_id, Message.thread_id, func.count(),
                   func.count().filter(Message.labels.contains(["UNREAD"])))
            .where(Message.user_id == user_id, Message.status != "duplicate",
                   or_(*[and_(Message.account_id == a, Message.thread_id == t) for a, t in keys]))
            .group_by(Message.account_id, Message.thread_id))
    return {(a, t): (n, u) for a, t, n, u in db.execute(stmt)}


def reorder(db: Session, user_id: uuid.UUID, parent_id: uuid.UUID | None, ordered: list[uuid.UUID]) -> None:
    tree = load_tree(db, user_id)
    kids = {f.id: f for f in tree.children(parent_id)}
    if set(ordered) != set(kids):
        raise FolderError("send every folder at this level, in the new order")
    for i, fid in enumerate(ordered):
        kids[fid].position = i
    db.flush()


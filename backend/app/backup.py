"""Settings backup (brief sections 18 and 20): folders, rules, tags, categories, grouping
preferences and settings as one JSON file. No mail, tokens or API keys are ever exported.

Accounts are referred to by email address, not id, so a file can be imported after
reconnecting accounts (ids change). Import adds to what exists; it never deletes.
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import folders as folder_service
from app import rules as engine
from app import user_settings
from app.rule_tools import next_position
from app.models import Category, Folder, GmailAccount, GroupPreference, Rule, Tag

FORMAT = "sift-backup"
VERSION = 1
MAX_ITEMS = 2000


class BackupError(ValueError):
    pass


def _map_accounts(node, mapping: dict[str, str]):
    """Rewrite `account` condition values (and nothing else) through `mapping`; unknown ones are dropped."""
    if isinstance(node, dict):
        if node.get("field") == "account":
            values = node.get("value") if isinstance(node.get("value"), list) else [node.get("value")]
            return {**node, "value": [mapping[str(v)] for v in values if str(v) in mapping]}
        return {k: _map_accounts(v, mapping) for k, v in node.items()}
    if isinstance(node, list):
        return [_map_accounts(x, mapping) for x in node]
    return node


def export(db: Session, user_id: uuid.UUID) -> dict:
    accounts = {str(a.id): a.email for a in db.scalars(select(GmailAccount).where(GmailAccount.user_id == user_id))}
    tree = folder_service.load_tree(db, user_id)
    out_folders = []

    def walk(parent_id, parent_ref):
        for f in tree.children(parent_id):
            if f.saved_search_id is not None:
                continue  # smart folders come with saved searches (Phase 3)
            out_folders.append({"ref": str(f.id), "parent": parent_ref, "name": f.name, "color": f.color, "icon": f.icon,
                                "pinned": f.pinned, "notify_mode": f.notify_mode})
            walk(f.id, str(f.id))

    walk(None, None)
    rules = [{
        "name": r.name, "enabled": r.enabled, "origin": r.origin,
        "conditions": _map_accounts(r.conditions, accounts), "exceptions": _map_accounts(r.exceptions, accounts) if r.exceptions else None,
        "action": r.action, "accounts": [accounts[str(a)] for a in (r.account_scope or []) if str(a) in accounts] if r.account_scope else None,
    } for r in db.scalars(select(Rule).where(Rule.user_id == user_id).order_by(Rule.position))]
    stored = user_settings.get(db, user_id)
    return {
        "format": FORMAT, "version": VERSION, "exported_at": datetime.now(UTC).isoformat(),
        "folders": out_folders,
        "rules": rules,
        "tags": [{"name": t.name, "color": t.color} for t in db.scalars(select(Tag).where(Tag.user_id == user_id).order_by(Tag.name))],
        "categories": [{"name": c.name, "definition": c.definition} for c in db.scalars(select(Category).where(Category.user_id == user_id).order_by(Category.name))],
        "group_preferences": [{"sender_or_domain": p.sender_or_domain, "mode": p.mode}
                              for p in db.scalars(select(GroupPreference).where(GroupPreference.user_id == user_id))],
        "settings": {k: stored[k] for k in user_settings.EDITABLE if k in stored},
    }


def _list(data: dict, key: str) -> list:
    v = data.get(key) or []
    if not isinstance(v, list) or len(v) > MAX_ITEMS:
        raise BackupError(f"{key} must be a list of at most {MAX_ITEMS} items")
    return v


def import_(db: Session, user_id: uuid.UUID, data: dict) -> dict:
    """All or nothing: the caller commits only if this returns. Rules whose accounts are not
    connected here come in disabled, so they never widen to every account by accident."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise BackupError("this isn't a Sift backup file")
    if not isinstance(data.get("version"), int) or data["version"] > VERSION:
        raise BackupError("this backup comes from a newer version of Sift")
    report = {"folders": 0, "rules": 0, "rules_disabled": 0, "tags": 0, "categories": 0, "group_preferences": 0, "settings": 0}

    # folders: parents always come before children in an export; refs map to new ids
    refs: dict[str, Folder] = {}
    for item in _list(data, "folders"):
        parent = refs.get(item.get("parent")) if item.get("parent") else None
        if item.get("parent") and parent is None:
            raise BackupError(f"folder {item.get('name')!r} refers to a parent that isn't in the file")
        try:
            f = folder_service.create(db, user_id, str(item.get("name", "")), parent.id if parent else None,
                                      item.get("color"), item.get("icon"))
            folder_service.edit(f, pinned=bool(item.get("pinned")), notify_mode=item.get("notify_mode") or "default")
        except folder_service.FolderError as exc:
            raise BackupError(f"folder {item.get('name')!r}: {exc}") from exc
        refs[str(item.get("ref"))] = f
        report["folders"] += 1

    emails = {a.email: str(a.id) for a in db.scalars(select(GmailAccount).where(GmailAccount.user_id == user_id))}
    position = next_position(db, user_id)
    for item in _list(data, "rules"):
        try:
            action = dict(item["action"])
            if action.get("folder_id"):
                target = refs.get(str(action["folder_id"]))
                if target is None:
                    action.pop("folder_id")
                else:
                    action["folder_id"] = str(target.id)
            conditions = _map_accounts(item["conditions"], emails)
            exceptions = _map_accounts(item["exceptions"], emails) if item.get("exceptions") else None
            engine.validate_condition(conditions)
            engine.validate_action(action)
            if exceptions:
                engine.validate_condition(exceptions)
        except (KeyError, TypeError, engine.RuleError) as exc:
            raise BackupError(f"rule {item.get('name')!r} is not valid: {exc}") from exc
        enabled = bool(item.get("enabled", True))
        scope = None
        if item.get("accounts"):
            scope = [emails[e] for e in item["accounts"] if e in emails]
            if len(scope) < len(item["accounts"]):
                enabled = False  # missing accounts: off until the user checks it
                scope = scope or [str(uuid.UUID(int=0))]  # an empty scope would mean "all accounts"
        if not enabled and item.get("enabled", True):
            report["rules_disabled"] += 1
        db.add(Rule(user_id=user_id, position=position, name=str(item.get("name") or "Imported rule")[:200], enabled=enabled,
                    conditions=conditions, action=action, exceptions=exceptions, account_scope=scope, origin="import"))
        position += 1
        report["rules"] += 1

    for item in _list(data, "tags"):
        name = str(item.get("name", "")).strip()[:80]
        if name and not db.scalar(select(Tag).where(Tag.user_id == user_id, Tag.name == name)):
            db.add(Tag(user_id=user_id, name=name, color=item.get("color")))
            report["tags"] += 1
    for item in _list(data, "categories"):
        name = str(item.get("name", "")).strip()[:80]
        if name and not db.scalar(select(Category).where(Category.user_id == user_id, Category.name == name)):
            db.add(Category(user_id=user_id, name=name, definition=item.get("definition")))
            report["categories"] += 1
    for item in _list(data, "group_preferences"):
        key, mode = str(item.get("sender_or_domain", "")).strip().lower()[:320], item.get("mode")
        if key and mode in ("always", "never"):
            pref = db.scalar(select(GroupPreference).where(GroupPreference.user_id == user_id, GroupPreference.sender_or_domain == key))
            if pref is None:
                db.add(GroupPreference(user_id=user_id, sender_or_domain=key, mode=mode))
            else:
                pref.mode = mode
            report["group_preferences"] += 1

    settings = data.get("settings") or {}
    if not isinstance(settings, dict):
        raise BackupError("settings must be an object")
    known = {k: v for k, v in settings.items() if k in user_settings.EDITABLE}
    try:
        user_settings.update(db, user_id, known)
    except (ValueError, TypeError) as exc:
        raise BackupError(f"settings: {exc}") from exc
    report["settings"] = len(known)
    db.flush()
    return report

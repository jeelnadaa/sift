/** Selecting many things and acting on them at once (owner, 2026-10-31).
 *
 * `useSelection` keeps what is picked on a list: mail ("m:<id>") and group rows ("g:<id>"), or
 * "everything this list shows" (`all`). Checkboxes show on hover and stay once anything is
 * picked; Shift-click picks a range; Esc clears.
 *
 * `BulkBar` sits above the list. With nothing picked it is one quiet "Select" line; once anything is
 * picked it becomes a sticky bar with the count ("3 mails + 2 groups (41 mails)"), "Select all N",
 * and the actions that fit the selection: every mail action for mail, and the same for groups (on
 * every mail in them) plus group actions when only groups are picked. Everything goes through one
 * server call, POST /bulk, which also serves Ask Sift. Trash, spam, more than 50 conversations, and
 * anything that reaches mail inside groups is confirmed first with exact counts. Big Gmail changes
 * run as a job with progress; reversible ones end with Undo. */
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { del, get, patch, post, type Group, type Mail } from "./api";
import { FolderPicker, Modal, actionToast, confirmDialog, errorText, inputDialog, toast } from "./components";
import { SnoozeDialog, withWriteAccess } from "./mailActions";

export interface Match { view?: "feed" | "silenced"; priority?: string | null; account_id?: string | null; folder_id?: string; include_subfolders?: boolean; group_id?: string }
export interface BulkTarget { message_ids?: string[]; group_ids?: string[]; opportunity_ids?: string[]; folder_ids?: string[]; match?: Match }
interface Picked { mails: number; groups: number; group_mails: number; urgent_in_groups: number; conversations: number }
interface Undo { action: string; params: Record<string, string>; message_ids: string[] }
interface Job { id: string; status: string; total: number; done: number; changed: number; failed_accounts: string[]; undo: Undo | null }
interface BulkResult { picked: Picked; conversations: number; changed: number; failed_accounts: string[]; sift_only: string[]; job: Job | null; undo: Undo | null }

const ASK_OVER = 50;  // more conversations than this are confirmed first
const DONE: Record<string, string> = {
  read: "Marked read", unread: "Marked unread", archive: "Archived", unarchive: "Moved to the inbox", trash: "Moved to Gmail's trash",
  untrash: "Restored from trash", spam: "Reported as spam", notspam: "Not spam", star: "Starred", unstar: "Star removed",
  important: "Marked important", unimportant: "Marked not important", label: "Label added", unlabel: "Label removed",
  pin: "Pinned", unpin: "Unpinned", file: "Filed", unfile: "Removed from the folder", group_add: "Added to the group",
  group_remove: "Removed from the group", mute: "Muted", unmute: "Unmuted", timeline: "Added to the timeline",
  untimeline: "Taken off the timeline", snooze: "Snoozed",
};

// for "Archive 12 conversations?"
const VERB: Record<string, string> = {
  read: "Mark read", unread: "Mark unread", archive: "Archive", unarchive: "Move to the inbox", trash: "Move to Gmail's trash",
  untrash: "Restore", spam: "Report as spam", notspam: "Mark not spam", star: "Star", unstar: "Remove the star from",
  important: "Mark important", unimportant: "Mark not important", label: "Label", unlabel: "Remove the label from",
  pin: "Pin", unpin: "Unpin", file: "File", unfile: "Take out of the folder", group_add: "Add to the group",
  group_remove: "Take out of the group", mute: "Mute", unmute: "Unmute", timeline: "Add to the timeline",
  untimeline: "Take off the timeline", snooze: "Snooze",
};

const plural = (n: number, one: string, many = one + "s") => `${n} ${n === 1 ? one : many}`;

/** What Ask Sift calls "these": ids only (the AI is told how many, never which). */
export interface AskSelection { message_ids?: string[]; group_ids?: string[]; opportunity_ids?: string[]; folder_ids?: string[]; label: string }

/** Opens Ask Sift with the selection as "these" (App listens for sift:ask). */
export function askAbout(sel: AskSelection) {
  dispatchEvent(new CustomEvent<AskSelection>("sift:ask", { detail: sel }));
}

export function AskButton({ sel }: { sel: AskSelection | null }) {
  return (
    <button className="btn btn-ghost btn-sm ask-these" disabled={!sel} onClick={() => sel && askAbout(sel)}
      data-tip={sel ? "Ask Sift to do something with these, in your own words" : "Pick rows on this page (not \"all\") to ask about them"}>✦ Ask</button>
  );
}

/** Runs one action over a selection: confirm when it's big or reaches into groups, ask for Gmail
 * write access when needed, follow a background job, then offer Undo. Resolves true when done. */
export async function runBulk(target: BulkTarget, action: string, params: Record<string, string> = {}, opts: { quiet?: boolean; confirmed?: boolean } = {}): Promise<boolean> {
  try {
    if (!opts.confirmed) {
      const pre = await post<BulkResult>("/bulk", { ...target, action, ...params, preview: true });
      const p = pre.picked;
      const risky = action === "trash" || action === "spam";
      if (p.conversations === 0) { toast("Nothing to change"); return false; }
      if (risky || p.conversations > ASK_OVER || p.groups > 0) {
        const parts = [plural(p.conversations, "conversation")];
        if (p.groups) parts.push(`including ${plural(p.group_mails, "mail")} in ${plural(p.groups, "group")}`);
        if (p.urgent_in_groups) parts.push(`(${plural(p.urgent_in_groups, "urgent mail")} among them)`);
        const ok = await confirmDialog({
          title: `${VERB[action] ?? action} ${parts.join(" ")}?`,
          body: action === "trash" ? "Gmail keeps trash for 30 days; Undo restores it." : action === "spam" ? "Gmail moves them to Spam and learns from it." : undefined,
          confirm: "Go ahead", danger: risky,
        });
        if (!ok) return false;
      }
    }
    const r = await withWriteAccess(() => post<BulkResult>("/bulk", { ...target, action, ...params }), true);
    if (!r) return false;
    if (r.job) return await follow(r.job, action, opts.quiet);
    finish(action, r.changed, r.failed_accounts, r.sift_only, r.undo, opts.quiet);
    return true;
  } catch (e) {
    toast(errorText(e));
    return false;
  }
}

async function follow(job: Job, action: string, quiet?: boolean): Promise<boolean> {
  let j = job;
  for (let i = 0; i < 1800 && (j.status === "queued" || j.status === "running"); i++) {
    toast(`${DONE[action] ?? "Working"}… ${j.done} of ${j.total}`);
    await new Promise((r) => setTimeout(r, 1000));
    try { j = await get<Job>(`/bulk/jobs/${j.id}`); } catch { /* keep waiting; the job carries on in the worker */ }
  }
  if (j.status === "failed") { toast(`Stopped after ${j.done} of ${j.total}. Try again for the rest.`); return false; }
  finish(action, j.changed, j.failed_accounts, [], j.undo, quiet);
  return true;
}

function finish(action: string, changed: number, failed: string[], siftOnly: string[], undo: Undo | null, quiet?: boolean) {
  dispatchEvent(new Event("sift:refresh"));
  if (failed.length) { toast(`Couldn't change mail in ${failed.join(", ")}. The rest is done.`); return; }
  if (quiet) return;
  const text = changed === 0 ? "Already done" : `${DONE[action] ?? "Done"}: ${plural(changed, "conversation")}${siftOnly.length ? " (in Sift only for " + siftOnly.join(", ") + ")" : ""}`;
  if (undo) actionToast(text, { label: "Undo", run: () => { void runBulk({ message_ids: undo.message_ids }, undo.action, undo.params, { quiet: true, confirmed: true }).then((ok) => ok && toast("Undone")); } }, 8000);
  else toast(text);
}

// ---- selection ----------------------------------------------------------------------------

export interface Selection {
  keys: Set<string>; all: boolean; size: number;
  has: (key: string) => boolean;
  toggle: (key: string, ordered: string[], shift: boolean) => void;
  setPage: (keys: string[], on: boolean) => void;
  selectAll: () => void;
  clear: () => void;
}

/** What is picked on one list; cleared when `resetKey` changes (filters, page) and with Esc. */
export function useSelection(resetKey: string): Selection {
  const [keys, setKeys] = useState<Set<string>>(new Set());
  const [all, setAll] = useState(false);
  const last = useRef<string | null>(null);
  const clear = useCallback(() => { setKeys(new Set()); setAll(false); last.current = null; }, []);
  useEffect(clear, [resetKey, clear]);
  useEffect(() => {
    if (!keys.size && !all) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !document.querySelector(".modal")) clear(); };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [keys.size, all, clear]);
  return {
    keys, all, size: keys.size, has: (k) => all || keys.has(k),
    toggle: (key, ordered, shift) => {
      setAll(false);
      setKeys((prev) => {
        const next = new Set(prev);
        const on = !prev.has(key);
        const a = last.current ? ordered.indexOf(last.current) : -1;
        const b = ordered.indexOf(key);
        if (shift && a >= 0 && b >= 0) for (const k of ordered.slice(Math.min(a, b), Math.max(a, b) + 1)) { if (on) next.add(k); else next.delete(k); }
        else if (on) next.add(key); else next.delete(key);
        return next;
      });
      last.current = key;
    },
    setPage: (page, on) => { setAll(false); setKeys(on ? new Set(page) : new Set()); },
    selectAll: () => setAll(true),
    clear,
  };
}

/** A row's checkbox (pass as MailRow/GroupRow `lead`). */
export function SelectBox({ sel, k, ordered, label }: { sel: Selection; k: string; ordered: string[]; label: string }) {
  return (
    <input type="checkbox" className="sel" checked={sel.has(k)} aria-label={label}
      onClick={(e) => { e.stopPropagation(); sel.toggle(k, ordered, e.shiftKey); }} onChange={() => {}}
      data-tip="Select (Shift-click picks a range)" />
  );
}

export const rowKey = (i: Mail | Group) => (i.type === "group" ? "g:" : "m:") + i.id;

// ---- the bar ------------------------------------------------------------------------------

type Place = { kind: "folder"; id: string; name: string } | { kind: "group"; id: string; name: string } | { kind: "silenced" } | null;

export function BulkBar({ sel, items, total, match, place = null, noun = "mails", extra }: {
  sel: Selection; items: (Mail | Group)[]; total?: number; match?: Match; place?: Place; noun?: string;
  extra?: (mailIds: string[]) => ReactNode;  // the page's own buttons (e.g. Silenced: "Not like this")
}) {
  const [picker, setPicker] = useState<null | "folder" | "group" | "timeline" | "snooze">(null);
  const [menu, setMenu] = useState(false);
  const [busy, setBusy] = useState(false);
  const moreRef = useRef<HTMLDivElement>(null);
  useEffect(() => {  // the menu closes on a click elsewhere or Esc
    if (!menu) return;
    const away = (e: MouseEvent) => { if (!moreRef.current?.contains(e.target as Node)) setMenu(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopImmediatePropagation(); setMenu(false); } };
    addEventListener("mousedown", away);
    addEventListener("keydown", esc, true);
    return () => { removeEventListener("mousedown", away); removeEventListener("keydown", esc, true); };
  }, [menu]);
  const page = items.map(rowKey);
  const chosen = items.filter((i) => sel.has(rowKey(i)));
  const mails = chosen.filter((i) => i.type !== "group") as Mail[];
  const groups = chosen.filter((i) => i.type === "group") as Group[];
  const inGroups = groups.reduce((n, g) => n + g.count, 0);
  const allOnPage = page.length > 0 && page.every((k) => sel.has(k));
  const target: BulkTarget = sel.all && match ? { match } : { message_ids: mails.map((m) => m.id), group_ids: groups.map((g) => g.id) };
  const onlyGroups = !sel.all && groups.length > 0 && mails.length === 0;

  async function go(action: string, params: Record<string, string> = {}) {
    setMenu(false);
    setBusy(true);
    const ok = await runBulk(target, action, params);
    setBusy(false);
    if (ok && ["archive", "trash", "spam", "snooze", "unfile", "group_remove"].includes(action)) sel.clear();
  }

  async function groupAction(kind: "mute" | "unmute" | "rename" | "merge" | "delete") {
    setMenu(false);
    try {
      if (kind === "rename") {
        const title = await inputDialog({ title: "Rename group", label: "Name", initial: groups[0].title, confirm: "Rename" });
        if (!title?.trim()) return;
        await patch(`/groups/${groups[0].id}`, { title: title.trim() });
      } else if (kind === "merge") {
        const [into, ...rest] = groups;
        if (!await confirmDialog({ title: `Merge ${plural(groups.length, "group")} into "${into.title}"?`, body: `${plural(inGroups, "mail")} end up in one group. Mail itself doesn't change.`, confirm: "Merge" })) return;
        for (const g of rest) await post(`/groups/${g.id}/merge`, { target_id: into.id });
      } else if (kind === "delete") {
        const custom = groups.filter((g) => g.custom).length;
        if (!await confirmDialog({ title: `${custom === groups.length ? "Delete" : "Ungroup"} ${plural(groups.length, "group")}?`, body: "The mail stays in your feed and in Gmail; only the grouping goes.", confirm: custom === groups.length ? "Delete" : "Ungroup", danger: true })) return;
        for (const g of groups) await del(`/groups/${g.id}`);
        sel.clear();
      } else {
        for (const g of groups) await patch(`/groups/${g.id}`, { muted: kind === "mute" });
      }
      toast({ mute: "Muted", unmute: "Unmuted", rename: "Renamed", merge: "Merged", delete: "Done" }[kind]);
      dispatchEvent(new Event("sift:refresh"));
    } catch (e) { toast(errorText(e)); }
  }

  if (!sel.size && !sel.all) {
    if (!page.length) return null;
    return (
      <div className="bulk-head">
        <input type="checkbox" checked={false} onChange={() => sel.setPage(page, true)} aria-label="Select everything on this page" data-tip="Select everything on this page" />
        <span className="dim">Select</span>
      </div>
    );
  }
  const count = sel.all
    ? (total !== undefined ? `All ${total} in this list` : `All ${noun}`)
    : [mails.length && plural(mails.length, "mail"), groups.length && `${plural(groups.length, "group")} (${plural(inGroups, "mail")})`].filter(Boolean).join(" + ");
  const more: [string, () => void, string?][] = [
    ["Star", () => go("star")], ["Remove star", () => go("unstar")],
    ["Mark important", () => go("important")], ["Mark not important", () => go("unimportant")],
    ["Move to inbox", () => go("unarchive")], ["Report spam", () => go("spam")],
    ["Snooze…", () => { setMenu(false); setPicker("snooze"); }],
    ["Add Gmail label…", async () => { setMenu(false); const l = await inputDialog({ title: "Add a Gmail label", label: "Label", placeholder: "New or existing label", confirm: "Add" }); if (l?.trim()) void go("label", { label: l.trim() }); }],
    ["Remove Gmail label…", async () => { setMenu(false); const l = await inputDialog({ title: "Remove a Gmail label", label: "Label", confirm: "Remove" }); if (l?.trim()) void go("unlabel", { label: l.trim() }); }],
    ["File in folder…", () => { setMenu(false); setPicker("folder"); }],
    ...(place?.kind === "folder" ? [["Remove from this folder", () => go("unfile", { folder_id: place.id })] as [string, () => void]] : []),
    ["Add to group…", () => { setMenu(false); setPicker("group"); }],
    ...(place?.kind === "group" ? [["Remove from this group", () => go("group_remove", { group_id: place.id })] as [string, () => void]] : []),
    ["Add to timeline…", () => { setMenu(false); setPicker("timeline"); }, onlyGroups ? "Pick mail, not groups, for a timeline" : undefined],
    ["Take off timeline", () => go("untimeline")],
    ["Pin to top", () => go("pin"), onlyGroups ? "Groups can't be pinned; pick their mail" : undefined],
    ["Unpin", () => go("unpin")],
    ["Mute conversations", () => go("mute")], ["Unmute conversations", () => go("unmute")],
  ];
  const groupOnly: [string, () => void, boolean][] = onlyGroups ? [
    ["Mute group", () => groupAction("mute"), true], ["Unmute group", () => groupAction("unmute"), true],
    ["Rename group…", () => groupAction("rename"), groups.length === 1], ["Merge groups", () => groupAction("merge"), groups.length > 1],
    [groups.every((g) => g.custom) ? "Delete group" : "Ungroup", () => groupAction("delete"), true],
  ] : [];
  return (
    <>
      <div className="bulk-bar" role="toolbar" aria-label="Selected">
        <input type="checkbox" checked={allOnPage} ref={(el) => { if (el) el.indeterminate = !allOnPage && !sel.all; }}
          onChange={() => sel.setPage(page, !allOnPage)} aria-label={allOnPage ? "Clear the selection" : "Select everything on this page"} />
        <span className="bulk-count">{count}</span>
        {allOnPage && !sel.all && match && total !== undefined && total > page.length && (
          <button className="link" onClick={sel.selectAll} data-tip="Every mail this list shows, on every page">Select all {total}</button>
        )}
        <span className="spacer" />
        <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => go("read")} data-tip="Mark read (in Gmail too, with write access)">Read</button>
        <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => go("unread")}>Unread</button>
        <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => go("archive")} data-tip="Archive in Gmail">Archive</button>
        <button className="btn btn-ghost btn-sm danger-text" disabled={busy} onClick={() => go("trash")} data-tip="Move to Gmail's trash (Undo restores it)">Delete</button>
        {extra?.(mails.map((m) => m.id))}
        {place?.kind === "silenced" && <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => go("unarchive")} data-tip="Back to Gmail's inbox">Move to inbox</button>}
        <div className="bulk-more" ref={moreRef}>
          <button className="btn btn-ghost btn-sm" aria-haspopup="menu" aria-expanded={menu} onClick={() => setMenu(!menu)}>More ▾</button>
          {menu && (
            <ul className="select-menu bulk-menu" role="menu">
              {groupOnly.filter(([, , show]) => show).map(([label, fn]) => <li key={label} role="menuitem" onClick={fn}>{label}</li>)}
              {groupOnly.length > 0 && <li className="sep" aria-hidden="true" />}
              {more.map(([label, fn, off]) => (
                <li key={label} role="menuitem" aria-disabled={!!off} className={off ? "off" : ""} data-tip={off} onClick={off ? undefined : fn}>{label}</li>
              ))}
            </ul>
          )}
        </div>
        <AskButton sel={sel.all ? null : { message_ids: mails.map((m) => m.id), group_ids: groups.map((g) => g.id), label: count }} />
        <button className="btn btn-ghost btn-sm" onClick={sel.clear} aria-label="Clear the selection" data-tip="Clear (Esc)">✕</button>
      </div>
      {picker === "folder" && <FolderPicker title="File in…" onClose={() => setPicker(null)} onPick={(f) => { setPicker(null); if (f) void go("file", { folder_id: f.id }); }} />}
      {picker === "snooze" && <SnoozeDialog onClose={() => setPicker(null)} onDone={() => setPicker(null)} onPick={(d) => { setPicker(null); void go("snooze", { until: d.toISOString() }); }} />}
      {picker === "group" && <PickList title="Add to group" load={() => get<Group[]>("/groups").then((gs) => gs.filter((g) => g.custom).map((g) => ({ id: g.id, name: g.title })))}
        empty="No groups of yours yet. Make one under Groups." onClose={() => setPicker(null)} onPick={(id) => { setPicker(null); void go("group_add", { group_id: id }); }} />}
      {picker === "timeline" && <PickList title="Add to timeline" load={() => get<{ id: string; company: string; status: string }[]>("/opportunities").then((os) => os.filter((o) => o.status !== "closed").map((o) => ({ id: o.id, name: o.company })))}
        empty="No company timelines yet." onClose={() => setPicker(null)} onPick={(id) => { setPicker(null); void go("timeline", { opportunity_id: id }); }} />}
    </>
  );
}

function PickList({ title, load, empty, onPick, onClose }: { title: string; load: () => Promise<{ id: string; name: string }[]>; empty: string; onPick: (id: string) => void; onClose: () => void }) {
  const [rows, setRows] = useState<{ id: string; name: string }[] | null>(null);
  useEffect(() => { load().then(setRows).catch((e) => { toast(errorText(e)); setRows([]); }); }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Modal title={title} onClose={onClose}>
      {rows === null && <p className="dim">Loading…</p>}
      {rows?.length === 0 && <p className="dim">{empty}</p>}
      {rows?.map((r) => <div key={r.id} className="pick" onClick={() => onPick(r.id)}>{r.name}</div>)}
    </Modal>
  );
}

/** Many simple calls (to-dos, timelines, folders), two at a time; returns how many worked. */
export async function runMany<T>(items: T[], fn: (x: T) => Promise<unknown>): Promise<number> {
  let ok = 0;
  const queue = [...items];
  await Promise.all([0, 1].map(async () => {
    for (let x = queue.shift(); x !== undefined; x = queue.shift()) {
      try { await fn(x); ok++; } catch { /* counted below */ }
    }
  }));
  return ok;
}

/** A small "Select" line / bar for lists of things that aren't mail (to-dos, timelines, folders, groups). */
export function ThingBar({ sel, keys, noun, children }: { sel: Selection; keys: string[]; noun: [string, string]; children: ReactNode }) {
  const allOnPage = keys.length > 0 && keys.every((k) => sel.has(k));
  if (!sel.size) {
    if (!keys.length) return null;
    return (
      <div className="bulk-head">
        <input type="checkbox" checked={false} onChange={() => sel.setPage(keys, true)} aria-label={`Select all ${noun[1]}`} data-tip={`Select all ${noun[1]}`} />
        <span className="dim">Select</span>
      </div>
    );
  }
  return (
    <div className="bulk-bar" role="toolbar" aria-label="Selected">
      <input type="checkbox" checked={allOnPage} ref={(el) => { if (el) el.indeterminate = !allOnPage; }} onChange={() => sel.setPage(keys, !allOnPage)}
        aria-label={allOnPage ? "Clear the selection" : `Select all ${noun[1]}`} />
      <span className="bulk-count">{sel.size} {sel.size === 1 ? noun[0] : noun[1]}</span>
      <span className="spacer" />
      {children}
      <button className="btn btn-ghost btn-sm" onClick={sel.clear} aria-label="Clear the selection" data-tip="Clear (Esc)">✕</button>
    </div>
  );
}

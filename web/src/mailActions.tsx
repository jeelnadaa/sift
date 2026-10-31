/** Changing mail in Gmail from the web UI (Phase 3c): one helper for every action, the snooze
 * picker, and the one-time "allow Sift to change mail in this account" step. */
import { useEffect, useState } from "react";
import { ApiError, get, post } from "./api";
import { Modal, TextField, errorText, toast } from "./components";

export interface Target { message_ids?: string[]; threads?: { account_id: string; thread_id: string }[] }
export type MailAction = "archive" | "unarchive" | "read" | "unread" | "star" | "unstar" | "trash" | "untrash" | "spam" | "notspam" | "label" | "unlabel";

const DONE: Record<string, string> = {
  archive: "Archived", unarchive: "Back in the inbox", read: "Marked read", unread: "Marked unread", star: "Starred", unstar: "Star removed",
  trash: "Moved to Gmail's trash", untrash: "Restored from trash", spam: "Reported as spam", notspam: "Not spam", label: "Label added", unlabel: "Label removed",
};
const UNDO: Partial<Record<MailAction, MailAction>> = { archive: "unarchive", trash: "untrash", spam: "notspam", read: "unread", unread: "read", star: "unstar", unstar: "star" };

type Pending = { accounts: { id: string; email: string }[]; retry: () => Promise<boolean> };
let askAccess: (p: Pending) => void = () => {};

/** Runs an action. When an account hasn't given write access yet, asks for it once and retries.
 * Resolves true when the action went through. */
export async function mailAction(target: Target, action: MailAction, label?: string, quiet = false): Promise<boolean> {
  try {
    const r = await post<{ done: number; failed_accounts: string[] }>("/mail/actions", { ...target, action, label });
    if (r.failed_accounts.length) toast(`Couldn't change mail in ${r.failed_accounts.join(", ")}. Try again later.`);
    else if (!quiet) toastWithUndo(DONE[action] ?? "Done", target, action);
    return r.failed_accounts.length === 0;
  } catch (e) {
    if (e instanceof ApiError && e.code === "needs_write_access") {
      const accounts = (e.body as { detail: { accounts: { id: string; email: string }[] } }).detail.accounts;
      return new Promise((resolve) => askAccess({ accounts, retry: async () => { const ok = await mailAction(target, action, label, quiet); resolve(ok); return ok; } }));
    }
    toast(errorText(e));
    return false;
  }
}

/** Runs `fn`; when Gmail write access is missing for an account, asks for it once (the same
 * dialog as mail actions) and runs it again. Resolves undefined when the user gave up or it failed
 * for another reason (the error is shown as a toast unless `rethrow`). */
export async function withWriteAccess<T>(fn: () => Promise<T>, rethrow = false): Promise<T | undefined> {
  try {
    return await fn();
  } catch (e) {
    if (e instanceof ApiError && e.code === "needs_write_access") {
      const accounts = (e.body as { detail: { accounts: { id: string; email: string }[] } }).detail.accounts;
      return new Promise((resolve) => askAccess({ accounts, retry: async () => { const r = await withWriteAccess(fn, rethrow); resolve(r); return r !== undefined; } }));
    }
    if (rethrow) throw e;
    toast(errorText(e));
    return undefined;
  }
}

function toastWithUndo(text: string, target: Target, action: MailAction) {
  const undo = UNDO[action];
  toast(undo ? `${text} · press Z to undo` : text);
  if (!undo) return;
  const onKey = (e: KeyboardEvent) => {
    if (e.key.toLowerCase() === "z" && !/INPUT|TEXTAREA/.test((e.target as HTMLElement).tagName)) { mailAction(target, undo, undefined, true).then((ok) => ok && toast("Undone")); stop(); }
  };
  const stop = () => removeEventListener("keydown", onKey);
  addEventListener("keydown", onKey);
  setTimeout(stop, 6000);
}

/** Mounted once (App): the "allow changes" dialog. Opens Google's page for one account in a new
 * tab; when the user comes back, "Try again" re-runs what they asked for. */
export function WriteAccessHost() {
  const [p, setP] = useState<Pending | null>(null);
  const [opened, setOpened] = useState<Set<string>>(new Set());
  useEffect(() => { askAccess = (x) => { setOpened(new Set()); setP(x); }; }, []);
  if (!p) return null;
  async function open(id: string) {
    try {
      const r = await get<{ auth_url: string }>(`/accounts/${id}/write-access-url`);
      window.open(r.auth_url, "_blank", "noopener");
      setOpened((s) => new Set([...s, id]));
    } catch (e) { toast(errorText(e)); }
  }
  return (
    <Modal title="Allow Sift to change mail?" onClose={() => setP(null)} foot={<>
      <button className="btn btn-ghost btn-sm" onClick={() => setP(null)} data-tip="Keep the account read-only">Not now</button>
      <button className="btn btn-primary btn-sm" disabled={opened.size === 0} data-tip={opened.size ? "Run the action now that access is granted" : "Allow it in Google first"}
        onClick={async () => { const x = p; setP(null); await x.retry(); }}>I've allowed it, try again</button>
    </>}>
      <p className="muted">Archive, labels, read/unread, star, trash, snooze, and writing and sending mail change things in Gmail, so Google asks you once per account. Sift still never sends or deletes mail on its own: only when you press Send.</p>
      <div className="stack" style={{ marginTop: 12 }}>
        {p.accounts.map((a) => (
          <div key={a.id} className="inline" style={{ justifyContent: "space-between" }}>
            <b>{a.email}</b>
            <button className="btn btn-ghost btn-sm" onClick={() => open(a.id)} data-tip="Opens Google's permission page in a new tab">{opened.has(a.id) ? "Opened ✓ (open again)" : "Allow in Google"}</button>
          </div>
        ))}
      </div>
    </Modal>
  );
}

// ---- snooze --------------------------------------------------------------------------------

function at(daysAhead: number, hour: number): Date {
  const d = new Date();
  d.setDate(d.getDate() + daysAhead);
  d.setHours(hour, 0, 0, 0);
  return d;
}

export function snoozeChoices(now = new Date()): [string, Date][] {
  const later = new Date(now.getTime() + 3 * 3600_000);
  later.setMinutes(0, 0, 0);
  const sat = (6 - now.getDay() + 7) % 7 || 7;
  const mon = (1 - now.getDay() + 7) % 7 || 7;
  const out: [string, Date][] = [];
  if (later.getDate() === now.getDate()) out.push(["Later today", later]);
  out.push(["Tomorrow morning", at(1, 9)], ["Tomorrow evening", at(1, 18)]);
  if (sat > 1) out.push(["This weekend", at(sat, 9)]);
  out.push(["Next week", at(mon, 9)]);
  return out;
}

/** With `onPick` it only chooses the time (the caller snoozes, e.g. a selection of many). */
export function SnoozeDialog({ target, onClose, onDone, onPick }: { target?: Target; onClose: () => void; onDone: () => void; onPick?: (until: Date) => void }) {
  const [custom, setCustom] = useState("");
  async function go(until: Date) {
    if (onPick) { onPick(until); return; }
    try {
      const r = await post<{ in_gmail: boolean }[]>("/snoozes", { ...target, until: until.toISOString() });
      toast(`Snoozed until ${until.toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}${r.some((x) => !x.in_gmail) ? " (hidden in Sift; Gmail unchanged)" : ""}`);
      onDone();
    } catch (e) { toast(errorText(e)); }
  }
  return (
    <Modal title="Snooze until…" onClose={onClose}>
      <div className="stack">
        {snoozeChoices().map(([label, d]) => (
          <button key={label} className="pick" style={{ justifyContent: "space-between", width: "100%" }} onClick={() => go(d)} data-tip="It comes back to your feed (and Gmail's inbox, with write access) and notifies you">
            <span>{label}</span><span className="dim">{d.toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" })}</span>
          </button>
        ))}
        <div className="field"><label htmlFor="sz">Pick a date and time</label>
          <div className="inline">
            <input id="sz" className="input" type="datetime-local" value={custom} onChange={(e) => setCustom(e.target.value)} style={{ flex: 1 }} />
            <button className="btn btn-primary btn-sm" style={{ height: 42 }} disabled={!custom} onClick={() => go(new Date(custom))}>Snooze</button>
          </div>
        </div>
        <p className="dim" style={{ fontSize: 12.5 }}>With write access the conversation is archived in Gmail and comes back to the inbox on time. Without it, it's hidden in Sift only. A reply brings it back early.</p>
      </div>
    </Modal>
  );
}

export function LabelDialog({ accountId, onClose, onPick }: { accountId: string; onClose: () => void; onPick: (name: string) => void }) {
  const [labels, setLabels] = useState<{ id: string; name: string }[] | null>(null);
  const [name, setName] = useState("");
  useEffect(() => { get<{ id: string; name: string }[]>(`/accounts/${accountId}/labels`).then(setLabels).catch(() => setLabels([])); }, [accountId]);
  return (
    <Modal title="Add a Gmail label" onClose={onClose} foot={<><button className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
      <button className="btn btn-primary btn-sm" disabled={!name.trim()} onClick={() => onPick(name.trim())} data-tip="A new label is created in Gmail if it doesn't exist">Add label</button></>}>
      <div className="field"><label htmlFor="lbl">Label</label><TextField id="lbl" value={name} onChange={setName} placeholder="New or existing label" autoFocus maxLength={225} onEnter={() => { if (name.trim()) onPick(name.trim()); }} /></div>
      <div className="tabs" style={{ marginTop: 12 }}>
        {labels === null && <span className="dim">Loading labels…</span>}
        {labels?.map((l) => <button key={l.id} className="chip" onClick={() => onPick(l.name)} data-tip="Add this label">{l.name}</button>)}
      </div>
    </Modal>
  );
}

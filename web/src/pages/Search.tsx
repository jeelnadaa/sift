import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { del, get, patch, post, session, type Account, type FolderTree, type Mail } from "../api";
import { Top } from "../App";
import {
  Banner, FolderPicker, MailRow, Modal, Pager, Select, TextField, Toggle, confirmDialog, errorText, inputDialog, toast, useLoad, usePages,
} from "../components";
import { flatten, accountName } from "../util";
import { SnoozeDialog, mailAction, type MailAction, type Target } from "../mailActions";

interface Chip { text: string; kind: "gmail" | "sift"; label: string; negated: boolean }
interface Result {
  items: (Mail & { source?: string; score?: number; gmail_id?: string })[];
  next_before: string | null; total: number; pages: number;
  estimated?: boolean; failed_accounts?: string[]; gmail_query?: string; words?: string[]; chips?: Chip[];
}
interface Saved { id: string; name: string; query: string; pinned: boolean; notify: boolean; smart_folder_id: string | null }
interface Suggest { senders: S[]; folders: S[]; tags: S[]; saved: S[]; recent: S[] }
interface S { label: string; query: string; detail?: string; count?: number }
interface SemStatus { ai_enabled: boolean; indexed: number; recent_total: number; backfill_days: number }

const PAGE = 30;
const QUICK: [string, string, string][] = [
  ["is:unread", "Unread", "Only unread mail"],
  ["has:attachment", "Has attachment", "Only mail with attachments"],
  ["newer_than:7d", "Last 7 days", "Mail from the last 7 days"],
  ["newer_than:30d", "Last 30 days", "Mail from the last 30 days"],
  ["is:silenced", "Silenced", "Mail a rule or template kept quiet"],
  ["is:grouped", "In a group", "Mail that sits in a group"],
  ["has:note", "Has a note", "Mail you wrote a private note on"],
];

const words = (q: string) => q.split(/\s+/).filter(Boolean);

/** Search (brief section 19): Gmail syntax plus Sift's own filters, across accounts, or by meaning. */
export function SearchPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const mode = params.get("mode") === "meaning" ? "meaning" : "keywords";
  const [draft, setDraft] = useState(q);
  const [chips, setChips] = useState<Chip[]>([]);
  const [parseError, setParseError] = useState<string | null>(null);
  const [gmailQuery, setGmailQuery] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [filing, setFiling] = useState(false);
  const [saving, setSaving] = useState(false);
  const [managing, setManaging] = useState(false);
  const [snoozingSel, setSnoozingSel] = useState(false);
  const accounts = useLoad(() => get<Account[]>("/accounts"));
  const tree = useLoad(() => get<FolderTree>("/folders"));
  const saved = useLoad(() => get<Saved[]>("/saved-searches"));
  const sem = useLoad(() => get<SemStatus>("/search/semantic/status"));

  useEffect(() => setDraft(q), [q]);
  // chips and the Gmail part, from the parser, whenever the query changes
  useEffect(() => {
    if (!q) { setChips([]); setGmailQuery(""); setParseError(null); return; }
    post<{ error: string | null; chips: Chip[]; gmail_query: string }>("/search/parse", { q })
      .then((r) => { setChips(r.chips); setGmailQuery(r.gmail_query); setParseError(r.error); })
      .catch(() => {});
  }, [q]);

  const results = usePages<Mail, Result>(async (before) => {
    if (!q || parseError) return { items: [], next_before: null, total: 0, pages: 1 };
    if (mode === "meaning") {
      const offset = before ? Number(before) : 0;
      const r = await get<{ items: Result["items"]; total: number; next_offset: number | null }>("/search/semantic", { q, offset, limit: PAGE });
      return { items: r.items, next_before: r.next_offset === null ? null : String(r.next_offset), total: r.total, pages: Math.max(1, Math.ceil(r.total / PAGE)) };
    }
    const r = await get<Result & { next_cursor: string | null }>("/search", { q, cursor: before, limit: PAGE });
    // Gmail only estimates how many results a search has (and badly), so Gmail searches show no total
    return { ...r, next_before: r.next_cursor, total: r.estimated ? -1 : r.total, pages: r.estimated ? 0 : Math.max(1, Math.ceil(r.total / PAGE)) };
  }, [q, mode, parseError]);
  useEffect(() => setSelected(new Set()), [q, mode, results.page]);

  function run(next: string, nextMode = mode) {
    const clean = next.trim().replace(/\s+/g, " ");
    setParams(clean ? { q: clean, ...(nextMode === "meaning" ? { mode: "meaning" } : {}) } : {});
  }
  const add = (token: string) => run([...words(q).filter((w) => w !== token), token].join(" "));
  const removeChip = (c: Chip) => run(chips.filter((x) => x !== c).map((x) => x.text).join(" "));
  const negateChip = (c: Chip) => run(chips.map((x) => (x === c ? (x.negated ? x.text.slice(1) : "-" + x.text) : x.text)).join(" "));

  const items = results.data?.items ?? [];
  const r = results.data as Result | null;
  const stored = items.filter((m) => m.id);
  const aiOn = !!sem.data?.ai_enabled;

  const storedSel = [...selected].filter((k) => !k.startsWith("g:"));
  const target = (): Target => ({
    message_ids: storedSel,
    threads: [...selected].filter((k) => k.startsWith("g:")).map((k) => { const [, account_id, thread_id] = k.split(":"); return { account_id, thread_id }; }),
  });
  async function bulk(action: MailAction) {
    if (await mailAction(target(), action)) { setSelected(new Set()); results.reload(); }
  }
  async function bulkTag() {
    const name = await inputDialog({ title: `Tag ${selected.size} mail${selected.size === 1 ? "" : "s"}`, label: "Tag", placeholder: "e.g. Later", confirm: "Tag" });
    if (!name) return;
    try {
      await post("/search/tag", { message_ids: storedSel, name });
      toast(`Tagged ${selected.size}`);
      setSelected(new Set());
    } catch (e) { toast(errorText(e)); }
  }
  async function exportCsv() {
    try {
      const res = await fetch(`/api/v1/search/export?q=${encodeURIComponent(q)}`, { headers: { Authorization: `Bearer ${session.token()}` } });
      if (!res.ok) throw new Error(`Export failed (${res.status})`);
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url; a.download = "sift-search.csv"; a.click();
      URL.revokeObjectURL(url);
    } catch (e) { toast(errorText(e)); }
  }

  return (
    <>
      <Top title="Search">
        {q && <button className="btn btn-primary btn-sm" onClick={() => setSaving(true)} data-tip="Keep this search: pin it, get notified of new matches, or show it as a smart folder">Save this search</button>}
        <button className="btn btn-ghost btn-sm" onClick={() => setManaging(true)} data-tip="Rename, pin, notify or delete saved searches">Saved searches</button>
        {q && mode === "keywords" && <button className="btn btn-ghost btn-sm" onClick={exportCsv} data-tip="Download up to 500 results as a spreadsheet (CSV)">Export CSV</button>}
      </Top>
      <section className="page">
        <div className="card stack" style={{ marginBottom: 16 }}>
          <div className="inline">
            <SearchBox value={draft} onChange={setDraft} onRun={(v) => run(v)} />
            <button className="btn btn-primary btn-sm" style={{ height: 42 }} onClick={() => run(draft)} data-tip="Search  (Enter)">Search</button>
          </div>
          <div className="tabs" style={{ margin: 0 }}>
            <button className={`chip ${mode === "keywords" ? "on" : ""}`} onClick={() => run(q, "keywords")} data-tip="Gmail's own search plus Sift's filters, across all your accounts">Keywords</button>
            <button className={`chip ${mode === "meaning" ? "on" : ""}`} disabled={!aiOn} onClick={() => aiOn && run(q, "meaning")}
              data-tip={aiOn ? `Find mail by what it's about, not exact words. ${sem.data?.indexed ?? 0} mails indexed (new mail + last ${sem.data?.backfill_days ?? 90} days)` : "Add an API key to enable"}>By meaning</button>
            {mode === "meaning" && sem.data && sem.data.indexed < sem.data.recent_total && (
              <a className="link" onClick={async () => { try { sem.setData(await post<SemStatus>("/search/semantic/index")); toast("Indexing the last 90 days in the background"); } catch (e) { toast(errorText(e)); } }}
                data-tip="Send the remaining mail from the last 90 days to your AI key for the meaning index (sender, subject and preview only)">Index {sem.data.recent_total - sem.data.indexed} more</a>
            )}
          </div>
          {chips.length > 0 && (
            <div className="tabs" style={{ margin: 0 }}>
              {chips.map((c, i) => (
                <span key={i} className={`chip on ${c.negated ? "neg" : ""}`} data-tip={c.kind === "sift" ? "A Sift filter (answered by Sift, not Gmail)" : "Sent to Gmail as typed"}>
                  {c.kind === "sift" && <span className="dim" aria-hidden="true">◆</span>}{c.label}
                  <button className="x" onClick={() => negateChip(c)} data-tip={c.negated ? "Stop excluding" : "Exclude these instead"} aria-label={`Negate ${c.label}`}>¬</button>
                  <button className="x" onClick={() => removeChip(c)} data-tip="Remove this filter" aria-label={`Remove ${c.label}`}>✕</button>
                </span>
              ))}
            </div>
          )}
          <FilterBuilder accounts={accounts.data ?? []} tree={tree.data} onAdd={add} />
          <p className="search-note">
            <b>◆ Sift filters</b> (folder, tag, priority, company, silenced…) only see mail Sift has seen, from when you connected the account.
            {" "}<b>Gmail syntax</b> (from:, subject:, has:attachment, newer_than:…) searches all your mail in Gmail.
          </p>
          {parseError && <p className="err-text">{parseError}</p>}
          {gmailQuery && mode === "keywords" && (
            <div className="field"><label>Gmail query (copy into Gmail)</label>
              <div className="inline">
                <code className="input code" style={{ flex: 1, display: "flex", alignItems: "center", overflowWrap: "anywhere", height: "auto", minHeight: 42, padding: "10px 14px" }}>{gmailQuery}</code>
                <button className="btn btn-ghost btn-sm" style={{ height: 42 }} onClick={() => navigator.clipboard.writeText(gmailQuery).then(() => toast("Copied"))} data-tip="Copy the Gmail part; Sift filters (◆) aren't Gmail syntax">Copy</button>
              </div>
            </div>
          )}
          <PlainEnglish aiOn={aiOn} onQuery={(query) => run(query)} />
        </div>

        {(saved.data?.length ?? 0) > 0 && (
          <div className="tabs">
            <span className="dim">Saved:</span>
            {saved.data!.map((s) => (
              <button key={s.id} className={`chip ${q === s.query ? "on" : ""}`} onClick={() => run(s.query)} data-tip={`${s.query}${s.notify ? "\nNotifies on new matches" : ""}${s.smart_folder_id ? "\nShown as a smart folder" : ""}`}>
                {s.pinned && "📌 "}{s.name}{s.notify && " 🔔"}
              </button>
            ))}
          </div>
        )}

        {!q && <div className="card dim">Search all your accounts with Gmail syntax (<span className="code">from:kotak has:attachment newer_than:30d</span>), add Sift's own filters (◆ folder, tag, priority, company, silenced…), or switch to <b>By meaning</b> to describe what a mail is about.</div>}
        {q && results.error && <Banner tone="err" action="Retry" onAction={results.reload}>{results.error}</Banner>}
        {(r?.failed_accounts?.length ?? 0) > 0 && <Banner tone="warn">Couldn't search {r!.failed_accounts!.join(", ")} right now; showing the other accounts.</Banner>}

        {q && results.data && (
          <>
            <Pager page={results.page} pages={results.pages || results.page} total={results.total} noun={mode === "meaning" ? "matches" : "conversations"} onPrev={results.onPrev} onNext={results.onNext} />
            {selected.size > 0 && (
              <div className="banner ok" style={{ marginBottom: 12 }}>
                <span>{selected.size} selected</span>
                <span className="spacer" />
                <button className="btn btn-ghost btn-sm" onClick={() => bulk("read")} data-tip="Mark the selected conversations read in Gmail">Mark read</button>
                <button className="btn btn-ghost btn-sm" onClick={() => bulk("archive")} data-tip="Archive the selected conversations in Gmail (Z to undo)">Archive</button>
                <button className="btn btn-ghost btn-sm" onClick={() => setSnoozingSel(true)} data-tip="Hide the selected conversations until later">Snooze…</button>
                <button className="btn btn-ghost btn-sm" disabled={!storedSel.length} onClick={() => setFiling(true)} data-tip={storedSel.length ? "File the selected conversations in a folder" : "Filing needs mail Sift stored"}>File in folder</button>
                <button className="btn btn-ghost btn-sm" disabled={!storedSel.length} onClick={bulkTag} data-tip={storedSel.length ? "Tag the selected mails" : "Tags need mail Sift stored"}>Tag</button>
                <button className="btn btn-ghost btn-sm" onClick={() => setSelected(new Set())} data-tip="Clear the selection">Clear</button>
              </div>
            )}
            <div className="list">
              {items.length === 0 && <div className="empty">{mode === "meaning" ? "Nothing close enough in meaning. Try other words, or Keywords." : "No mail matches."}</div>}
              {items.map((m, i) => (
                <MailRow key={m.id ?? `${m.account_id}:${m.thread_id}`} m={m} n={i + 1} highlight={r?.words}
                  draggable={!!m.id}
                  lead={(() => {
                    const key = m.id ?? `g:${m.account_id}:${m.thread_id}`;
                    return <input type="checkbox" checked={selected.has(key)} aria-label="Select" data-tip={m.id ? "Select for bulk actions" : "Select (older mail: archive, read and snooze work; file and tag need mail Sift stored)"}
                      onClick={(e) => e.stopPropagation()} onChange={() => setSelected((s) => { const n = new Set(s); if (n.has(key)) n.delete(key); else n.add(key); return n; })} />;
                  })()}
                  extra={<>
                    {m.score !== undefined && <span className="tag ok" data-tip="How close in meaning (1 = identical)">{Math.round(m.score * 100)}%</span>}
                    {!m.id && <span className="tag" data-tip="Found in Gmail; Sift never processed it (older than Sift)">Gmail only</span>}
                  </>}
                  onOpen={() => navigate(m.id ? `/mail/${m.id}` : `/read/${m.account_id}/${m.thread_id}`)} />
              ))}
            </div>
            <Pager bottom page={results.page} pages={results.pages || results.page} total={results.total} noun="conversations" onPrev={results.onPrev} onNext={results.onNext} />
            {stored.length < items.length && <p className="dim" style={{ fontSize: 13, marginTop: 10 }}>Rows marked "Gmail only" are older mail Sift never processed; open them to read. Sift filters (◆) only match mail Sift has.</p>}
          </>
        )}
      </section>

      {filing && <FolderPicker title={`File ${selected.size} conversation${selected.size === 1 ? "" : "s"} in…`} onClose={() => setFiling(false)}
        onPick={async (f) => {
          setFiling(false);
          if (!f) return;
          try { const res = await post<{ filed: number }>(`/folders/${f.id}/threads`, { message_ids: storedSel }); toast(`Filed ${res.filed} in ${f.name}`); setSelected(new Set()); } catch (e) { toast(errorText(e)); }
        }} />}
      {snoozingSel && <SnoozeDialog target={target()} onClose={() => setSnoozingSel(false)} onDone={() => { setSnoozingSel(false); setSelected(new Set()); results.reload(); }} />}
      {saving && <SaveDialog query={q} onClose={() => setSaving(false)} onSaved={() => { setSaving(false); saved.reload(); }} />}
      {managing && <ManageSaved list={saved.data ?? []} onClose={() => setManaging(false)} onChanged={saved.reload} />}
    </>
  );
}

/** Search box with live suggestions: senders, folders, tags, saved and recent searches. */
function SearchBox({ value, onChange, onRun }: { value: string; onChange: (v: string) => void; onRun: (v: string) => void }) {
  const [sug, setSug] = useState<Suggest | null>(null);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const last = value.split(/\s+/).pop() ?? "";

  useEffect(() => {
    if (!open) return;
    const t = setTimeout(() => { get<Suggest>("/search/suggest", { q: last.replace(/^-?\w+:/, "") }).then(setSug).catch(() => {}); }, 200);
    return () => clearTimeout(t);
  }, [last, open]);
  useEffect(() => {
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    addEventListener("mousedown", away);
    return () => removeEventListener("mousedown", away);
  }, []);

  const pick = (s: S, replace: boolean) => {
    const next = replace ? s.query : [...value.split(/\s+/).slice(0, -1), s.query].join(" ").trim() + " ";
    onChange(next);
    if (replace) { onRun(next); setOpen(false); }
  };
  const groups: [string, S[], boolean][] = sug ? [["Recent", sug.recent, true], ["Saved", sug.saved, true], ["Senders", sug.senders, false], ["Folders", sug.folders, false], ["Tags", sug.tags, false]] : [];
  const any = groups.some(([, xs]) => xs.length);
  return (
    <div className="search-box" ref={box}>
      <div onFocus={() => setOpen(true)}>
        <TextField value={value} onChange={(v) => { onChange(v); setOpen(true); }} onEnter={() => { onRun(value); setOpen(false); }}
          placeholder='from:kotak has:attachment newer_than:30d  ·  folder:"Job hunt" -tag:done' ariaLabel="Search" maxRows={4} />
      </div>
      {open && any && (
        <div className="select-menu suggest" role="listbox">
          {groups.filter(([, xs]) => xs.length).map(([title, xs, replace]) => (
            <div key={title}>
              <div className="nav-h" style={{ padding: "6px 10px 4px" }}>{title}</div>
              {xs.map((s) => (
                <li key={title + s.query} role="option" aria-selected={false} onMouseDown={(e) => { e.preventDefault(); pick(s, replace); }}
                  data-tip={replace ? "Run this search" : `Add ${s.query} to the search`}>
                  <span>{s.label}</span>{(s.detail || s.count) && <small>{[s.detail !== s.label ? s.detail : null, s.count ? `${s.count} mails` : null].filter(Boolean).join(" · ")}</small>}
                </li>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Buttons and dropdowns that add filters to the query (the builder and the string convert both ways). */
function FilterBuilder({ accounts, tree, onAdd }: { accounts: Account[]; tree: FolderTree | null; onAdd: (token: string) => void }) {
  const quote = (v: string) => (/[\s(){}"]/.test(v) ? `"${v.replace(/"/g, "")}"` : v);
  const folderOpts = [{ value: "", label: "In folder…" }, { value: "none", label: "In no folder" },
    ...flatten(tree?.folders ?? []).filter(([f]) => !f.smart).map(([f, d]) => ({ value: f.name, label: `${"  ".repeat(d)}${f.name}`, hint: d ? undefined : "Includes its subfolders" }))];
  return (
    <div className="tabs" style={{ margin: 0 }}>
      {QUICK.map(([tok, label, tip]) => <button key={tok} className="chip" onClick={() => onAdd(tok)} data-tip={tip}>{label}</button>)}
      <Select value="" ariaLabel="Add a priority filter" options={[{ value: "", label: "Priority…" }, ...["urgent", "normal", "digest", "silent"].map((p) => ({ value: p, label: p[0].toUpperCase() + p.slice(1) }))]}
        onChange={(v) => v && onAdd(`priority:${v}`)} />
      <Select value="" ariaLabel="Add a folder filter" options={folderOpts} onChange={(v) => v && onAdd(`folder:${quote(v)}`)} />
      {accounts.length > 1 && <Select value="" ariaLabel="Search one account" options={[{ value: "", label: "Account…" }, ...accounts.map((a) => ({ value: a.email, label: accountName(a.label, a.email), hint: a.email }))]}
        onChange={(v) => v && onAdd(`account:${v}`)} />}
    </div>
  );
}

function PlainEnglish({ aiOn, onQuery }: { aiOn: boolean; onQuery: (q: string) => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  async function go() {
    setBusy(true);
    try {
      const r = await post<{ query: string; explanation: string }>("/search/from-text", { text: text.trim() });
      onQuery(r.query);
      toast(r.explanation || "Turned into a search");
    } catch (e) { toast(errorText(e)); } finally { setBusy(false); }
  }
  return (
    <div className={`field ${aiOn ? "" : "locked"}`} data-tip={aiOn ? undefined : "Add an API key to enable. Typing Gmail syntax above works without one."}>
      <label>Or describe it</label>
      <div className="inline">
        <TextField value={text} onChange={setText} placeholder="mails from Walmart last week" ariaLabel="Describe the mail you want" maxLength={300} onEnter={() => { if (aiOn && text.trim()) go(); }} />
        <button className="btn btn-ghost btn-sm" style={{ height: 42 }} disabled={!aiOn || !text.trim() || busy} onClick={go} data-tip="Your AI key turns this into the same filters you can edit above">{busy ? "Thinking…" : "Turn into search"}</button>
      </div>
    </div>
  );
}

function SaveDialog({ query, onClose, onSaved }: { query: string; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState("");
  const [notify, setNotify] = useState(false);
  const [smart, setSmart] = useState(false);
  const [pinned, setPinned] = useState(false);
  async function save() {
    try { await post("/saved-searches", { name: name.trim(), query, notify, smart_folder: smart, pinned }); toast("Saved"); onSaved(); } catch (e) { toast(errorText(e)); }
  }
  return (
    <Modal title="Save this search" onClose={onClose} foot={<><button className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button><button className="btn btn-primary btn-sm" disabled={!name.trim()} onClick={save}>Save</button></>}>
      <div className="stack">
        <div className="field"><label htmlFor="sv-n">Name</label><TextField id="sv-n" value={name} onChange={setName} autoFocus maxLength={120} placeholder="e.g. Unreplied recruiters" onEnter={() => { if (name.trim()) save(); }} /></div>
        <div className="field"><label>Query</label><code className="code dim" style={{ overflowWrap: "anywhere" }}>{query}</code></div>
        <div className="set-row"><div>Pin to the top</div><Toggle on={pinned} onChange={setPinned} label="Pin" /></div>
        <div className="set-row"><div>Notify me of new matches<small>Even mail a rule keeps quiet. Mail that already notified isn't sent twice.</small></div><Toggle on={notify} onChange={setNotify} label="Notify on new matches" /></div>
        <div className="set-row"><div>Show as a smart folder<small>In the folder tree; it updates itself.</small></div><Toggle on={smart} onChange={setSmart} label="Smart folder" /></div>
      </div>
    </Modal>
  );
}

function ManageSaved({ list, onClose, onChanged }: { list: Saved[]; onClose: () => void; onChanged: () => void }) {
  async function change(s: Saved, body: object) {
    try { await patch(`/saved-searches/${s.id}`, body); onChanged(); } catch (e) { toast(errorText(e)); }
  }
  return (
    <Modal title="Saved searches" onClose={onClose}>
      {list.length === 0 && <p className="dim">Nothing saved yet. Run a search, then "Save this search".</p>}
      {list.map((s) => (
        <div key={s.id} className="set-row" style={{ alignItems: "flex-start" }}>
          <div style={{ minWidth: 0 }}><b>{s.name}</b><small className="code" style={{ overflowWrap: "anywhere" }}>{s.query}</small></div>
          <div className="inline" style={{ flex: "none" }}>
            <Toggle on={s.pinned} label="Pinned" onChange={(v) => change(s, { pinned: v })} />
            <Toggle on={s.notify} label="Notify on new matches" onChange={(v) => change(s, { notify: v })} />
            <Toggle on={!!s.smart_folder_id} label="Smart folder" onChange={(v) => change(s, { smart_folder: v })} />
            <button className="chip" data-tip="Rename" onClick={async () => { const n = await inputDialog({ title: "Rename saved search", label: "Name", initial: s.name }); if (n) change(s, { name: n }); }}>✎</button>
            <button className="chip" data-tip="Delete this saved search (and its smart folder)" onClick={async () => {
              if (!(await confirmDialog({ title: `Delete "${s.name}"?`, body: "The saved search and its smart folder go. Mail is untouched.", confirm: "Delete", danger: true }))) return;
              try { await del(`/saved-searches/${s.id}`); onChanged(); } catch (e) { toast(errorText(e)); }
            }}>✕</button>
          </div>
        </div>
      ))}
      <p className="dim" style={{ fontSize: 12.5, marginTop: 8 }}>Switches: pinned · notify on new matches · smart folder.</p>
    </Modal>
  );
}


/** Writing mail (Phase 4): new mail, reply, reply all, forward, and reopening a draft.
 *
 * The mail is a Gmail draft from the first change on: it autosaves (1.5 s after typing stops)
 * and can be finished in Gmail too. Saves run one at a time, so an attachment upload and an
 * autosave never overwrite each other. Send waits for the undo window (Settings) and shows an
 * Undo button; Send later schedules it; "Remind me" sets a follow-up if nobody replies.
 * AI reply drafts use the user's own key and only fill the text box: nothing is sent without
 * pressing Send. */
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Top, lastPage } from "../App";
import { ApiError, del, get, patch, post, put, upload, type Account, type AiStatus, type DraftData, type OutboxItem, type ReplyContext, type ReplyTemplate, type ReplyTemplateListResult, type Settings } from "../api";
import { Banner, Modal, Select, TextField, actionToast, confirmDialog, errorText, toast } from "../components";
import { withWriteAccess } from "../mailActions";
import { fullTime } from "../util";
import { size } from "./Thread";

type Mode = "new" | "reply" | "reply_all" | "forward";
const TITLES: Record<Mode | "draft", string> = { new: "New mail", reply: "Reply", reply_all: "Reply all", forward: "Forward", draft: "Draft" };
const EMAIL = /^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$/;
const isDemo = (a: Account) => a.email.endsWith("@demo.sift.local");
const bareOf = (a: string) => (a.match(/<([^>]+)>/)?.[1] ?? a).trim();

function at(days: number, hour: number): Date {
  const d = new Date();
  d.setDate(d.getDate() + days);
  d.setHours(hour, 0, 0, 0);
  return d;
}

function laterChoices(): { value: string; label: string; when: Date }[] {
  const now = new Date();
  const out: { value: string; label: string; when: Date }[] = [];
  if (now.getHours() < 17) out.push({ value: "eve", label: "This evening, 18:00", when: at(0, 18) });
  out.push({ value: "tom", label: `Tomorrow morning, 09:00`, when: at(1, 9) });
  const toMonday = ((8 - now.getDay()) % 7) || 7;
  out.push({ value: "mon", label: `Monday, 09:00`, when: at(toMonday, 9) });
  return out;
}

export function ComposePage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const mode = (params.get("mode") as Mode) || "new";
  const draftParam = params.get("draft"); // "accountId:draftId"
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [ai, setAi] = useState<AiStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  const [accountId, setAccountId] = useState("");
  const [to, setTo] = useState<string[]>([]);
  const [cc, setCc] = useState<string[]>([]);
  const [bcc, setBcc] = useState<string[]>([]);
  const [showCc, setShowCc] = useState(false);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [draft, setDraft] = useState<DraftData | null>(null);
  const [scheduled, setScheduled] = useState<OutboxItem | null>(null);
  const [threading, setThreading] = useState<{ thread_id: string | null; in_reply_to: string | null; references: string | null; forward_gmail_id: string | null }>(
    { thread_id: null, in_reply_to: null, references: null, forward_gmail_id: null });
  const [forwardFiles, setForwardFiles] = useState<ReplyContext["attachments"]>([]);
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [later, setLater] = useState("");
  const [customLater, setCustomLater] = useState("");
  const [followUp, setFollowUp] = useState("0");
  const [aiOpen, setAiOpen] = useState(false);
  const [aiText, setAiText] = useState("");
  const [aiBusy, setAiBusy] = useState(false);
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  // set when another device (or Gmail) saved this draft since we loaded it: autosave pauses until
  // the user loads their version or keeps this one
  const [conflict, setConflict] = useState<DraftData | null>(null);
  const conflictRef = useRef<DraftData | null>(null);
  const draftRef = useRef<DraftData | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const original = { message: params.get("message"), account: params.get("account"), gmail: params.get("gmail") };
  const replying = mode === "reply" || mode === "reply_all";
  const title = TITLES[draftParam ? "draft" : mode];
  draftRef.current = draft;

  // ---- load ----------------------------------------------------------------------------------
  useEffect(() => {
    (async () => {
      try {
        const accs = await get<Account[]>("/accounts");
        setAccounts(accs);
        let targetAcc = "";
        let replyBody = "";
        if (draftParam) {
          const [acc, did] = draftParam.split(":");
          targetAcc = acc;
          const d = await get<DraftData>(`/compose/drafts/${acc}/${did}`);
          setDraft(d); setAccountId(d.account_id); setTo(d.to); setCc(d.cc); setBcc(d.bcc); setShowCc(d.cc.length + d.bcc.length > 0);
          setSubject(d.subject); setBody(d.body); setScheduled(d.outbox ?? null);
          setThreading({ thread_id: d.thread_id, in_reply_to: d.in_reply_to, references: d.references, forward_gmail_id: null });
          setState("saved");
        } else if (mode !== "new") {
          const ctx = await get<ReplyContext>("/compose/context", { mode, message_id: original.message ?? undefined, account_id: original.account ?? undefined, gmail_id: original.gmail ?? undefined });
          targetAcc = ctx.account_id;
          replyBody = ctx.body;
          setAccountId(ctx.account_id); setTo(ctx.to); setCc(ctx.cc); setShowCc(ctx.cc.length > 0); setSubject(ctx.subject);
          setThreading({ thread_id: ctx.thread_id, in_reply_to: ctx.in_reply_to, references: ctx.references, forward_gmail_id: ctx.forward_gmail_id });
          setForwardFiles(ctx.attachments);
          if (mode === "forward") setDirty(true); // save at once so the original's attachments are attached
        } else {
          const usable = accs.filter((a) => a.status === "active" && !isDemo(a));
          targetAcc = params.get("from") ?? usable[0]?.id ?? "";
          setAccountId(targetAcc);
          const preset = params.get("to");
          if (preset) setTo([preset]);
        }
        const s = await get<Settings>("/settings", targetAcc ? { account_id: targetAcc } : undefined);
        setSettings(s);
        get<AiStatus>("/ai").then(setAi).catch(() => {});
        const sig = s.signature ? `\n\n-- \n${s.signature}` : "";
        if (!draftParam) {
          setBody(mode !== "new" ? sig + replyBody : sig);
        }
        setReady(true);
      } catch (e) { setLoadError(errorText(e)); }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!ready) return;
    document.title = `${subject || title} · Sift`;
    if (mode === "new" || replying) bodyRef.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  // ---- saving --------------------------------------------------------------------------------
  // the latest values, read by saves (including the one when leaving the page)
  const latest = useRef({ fields: { to, cc, bcc, subject, body }, accountId, threading });
  latest.current = { fields: { to, cc, bcc, subject, body }, accountId, threading };

  /** Queue one save; resolves to the draft after it (or null when it failed). */
  function save(overwrite = false): Promise<DraftData | null> {
    const { fields: snapshot, accountId: acc, threading: thr } = latest.current;
    const run = async (): Promise<DraftData | null> => {
      if (conflictRef.current && !overwrite) return null; // waiting for the user's choice
      setState("saving");
      const current = draftRef.current;
      let r: DraftData | undefined;
      try {
        r = await withWriteAccess(() => current
          ? put<DraftData>(`/compose/drafts/${current.account_id}/${current.draft_id}`, { ...snapshot, base_version: overwrite ? undefined : current.version })
          : post<DraftData>("/compose/drafts", { ...snapshot, account_id: acc, ...thr }), true);
      } catch (e) {
        if (e instanceof ApiError && e.code === "draft_changed") {
          const theirs = (e.body as { detail: { draft: DraftData } }).detail.draft;
          conflictRef.current = theirs;
          setConflict(theirs);
          setState("idle");
          return null;
        }
        toast(errorText(e));
      }
      if (!r) { setState("error"); return null; }
      draftRef.current = r;
      setDraft(r);
      setState("saved");
      return r;
    };
    const p = queue.current.then(run, run);
    queue.current = p.catch(() => null);
    return p;
  }

  useEffect(() => {
    if (!ready || !dirty || !accountId) return;
    const t = window.setTimeout(() => { setDirty(false); save(); }, 1500);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [to, cc, bcc, subject, body, dirty, ready, accountId]);

  // save what's typed when leaving the page
  const dirtyRef = useRef(false);
  dirtyRef.current = dirty;
  useEffect(() => () => { if (dirtyRef.current) save(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const edit = <T,>(set: (v: T) => void) => (v: T) => { set(v); setDirty(true); if (state === "saved") setState("idle"); };

  async function flush(): Promise<DraftData | null> {
    setDirty(false);
    return save();
  }

  function loadTheirs() {
    const d = conflictRef.current;
    if (!d) return;
    conflictRef.current = null;
    setConflict(null);
    draftRef.current = d;
    setDraft(d); setTo(d.to); setCc(d.cc); setBcc(d.bcc); setSubject(d.subject); setBody(d.body);
    setDirty(false);
    setState("saved");
  }

  function keepMine() {
    conflictRef.current = null;
    setConflict(null);
    setDirty(false);
    save(true);
  }

  async function changeAccount(id: string) {
    if (id === accountId) return;
    const d = draftRef.current;
    if (d) {
      if (d.attachments.length && !(await confirmDialog({ title: "Send from another account?", body: "The draft moves to the other account. Its attachments stay behind; add them again.", confirm: "Switch" }))) return;
      try { await del(`/compose/drafts/${d.account_id}/${d.draft_id}`); } catch { /* it may already be gone */ }
      draftRef.current = null;
      setDraft(null);
    }
    setAccountId(id);
    setDirty(true);
    try {
      const accSettings = await get<Settings>("/settings", { account_id: id });
      const prevSig = settings?.signature ? `\n\n-- \n${settings.signature}` : "";
      const newSig = accSettings.signature ? `\n\n-- \n${accSettings.signature}` : "";
      setSettings(accSettings);
      setBody((b) => {
        if (prevSig && b.endsWith(prevSig)) {
          return b.slice(0, b.length - prevSig.length) + newSig;
        } else if (!b || b === prevSig) {
          return newSig;
        }
        return b;
      });
    } catch { /* keep current settings */ }
  }

  // ---- attachments ---------------------------------------------------------------------------
  async function attach(files: File[]) {
    const d = (await flush()) ?? draftRef.current;
    if (!d) return;
    for (const f of files) {
      if ((draftRef.current?.attachments_size ?? 0) + f.size > (draftRef.current?.attachments_limit ?? 25 * 1024 * 1024)) {
        toast(`${f.name} is too big: attachments are limited to 25 MB in total`);
        continue;
      }
      setState("saving");
      const run = async () => {
        const cur = draftRef.current!;
        const r = await withWriteAccess(() => upload<DraftData>(`/compose/drafts/${cur.account_id}/${cur.draft_id}/attachments`, f, { filename: f.name }));
        if (r) { draftRef.current = r; setDraft(r); setState("saved"); } else setState("error");
      };
      const p = queue.current.then(run, run);
      queue.current = p.catch(() => null);
      await p;
    }
  }

  async function removeAttachment(index: number) {
    const run = async () => {
      const cur = draftRef.current!;
      const r = await withWriteAccess(() => del<DraftData>(`/compose/drafts/${cur.account_id}/${cur.draft_id}/attachments/${index}`));
      if (r) { draftRef.current = r; setDraft(r); }
    };
    const p = queue.current.then(run, run);
    queue.current = p.catch(() => null);
    await p;
  }

  // ---- send ----------------------------------------------------------------------------------
  const badRecipients = [...to, ...cc, ...bcc].filter((a) => !EMAIL.test(bareOf(a)));
  const canSend = ready && !busy && to.length + cc.length + bcc.length > 0 && badRecipients.length === 0 && !!accountId;

  async function send(when?: Date) {
    if (!canSend) return;
    if (!subject.trim() && !(await confirmDialog({ title: "Send without a subject?", confirm: "Send anyway" }))) return;
    setBusy(true);
    try {
      const d = await flush();
      if (!d) return;
      const body_ = { send_at: when ? when.toISOString() : undefined, follow_up_days: Number(followUp) || undefined };
      const r = await withWriteAccess(() => post<OutboxItem & { undo_seconds: number }>(`/compose/drafts/${d.account_id}/${d.draft_id}/send`, body_), true);
      if (!r) return;
      setDirty(false);
      dirtyRef.current = false;
      leave();
      if (r.status === "sent") toast("Sent");
      else if (r.later) toast(`Scheduled for ${fullTime(r.send_at)}`);
      else if (r.status === "scheduled") {
        actionToast(`Sending in ${r.undo_seconds} s…`, { label: "Undo", run: () => undoSend(r) }, r.undo_seconds * 1000);
      }
    } catch (e) {
      toast(e instanceof ApiError ? e.message : errorText(e));
    } finally { setBusy(false); }
  }

  async function undoSend(r: OutboxItem) {
    try {
      await post(`/outbox/${r.id}/cancel`);
      toast("Not sent. It's back in your drafts");
      navigate(`/compose?draft=${r.account_id}:${r.draft_id}`);
    } catch (e) { toast(errorText(e)); }
  }

  async function unschedule() {
    if (!scheduled) return;
    try { await post(`/outbox/${scheduled.id}/cancel`); setScheduled(null); toast("Unscheduled. It stays a draft"); } catch (e) { toast(errorText(e)); }
  }

  /** Back to the page the composer was opened from; the composer leaves the history. */
  function leave() {
    navigate(lastPage, { replace: true });
  }

  async function discard() {
    if (!(await confirmDialog({ title: "Discard this draft?", body: "It's removed from your Gmail drafts too.", confirm: "Discard", danger: true }))) return;
    setDirty(false);
    dirtyRef.current = false;
    await queue.current;
    const d = draftRef.current;
    if (d) {
      const ok = await withWriteAccess(() => del(`/compose/drafts/${d.account_id}/${d.draft_id}`).then(() => true));
      if (!ok) return;
    }
    toast("Draft discarded");
    leave();
  }

  // ---- AI ------------------------------------------------------------------------------------
  async function aiDraft(instructions: string) {
    setAiBusy(true);
    try {
      const r = await post<{ body: string }>("/compose/ai-draft", { message_id: original.message ?? undefined, account_id: original.account ?? undefined, gmail_id: original.gmail ?? undefined, instructions });
      setBody((b) => r.body + "\n" + b.replace(/^\s*/, "\n"));
      setDirty(true);
      setAiOpen(false);
      toast("Draft written. Read it and change anything before sending");
      bodyRef.current?.focus();
      bodyRef.current?.setSelectionRange(0, 0);
    } catch (e) { toast(errorText(e)); } finally { setAiBusy(false); }
  }

  // ---- keyboard ------------------------------------------------------------------------------
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); send(); } };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  });

  const accountOptions = useMemo(() => accounts.filter((a) => a.status === "active" && !isDemo(a)).map((a) => ({ value: a.id, label: a.email, hint: a.can_modify ? undefined : "Asks Google for permission on first save" })), [accounts]);
  const laters = useMemo(laterChoices, []);

  if (loadError) return (<><Top title={title} back /><section className="page"><Banner tone="err" action="Back" onAction={() => navigate(-1)}>{loadError}</Banner></section></>);
  if (!ready) return (<><Top title={title} back /><section className="page"><p className="dim">Loading…</p></section></>);
  if (!accountOptions.length) return (<><Top title={title} back /><section className="page"><Banner tone="warn" action="Accounts" onAction={() => navigate("/accounts")}>Connect a Gmail account to write mail. The demo account can't send.</Banner></section></>);

  const saveText = { idle: dirty ? "Not saved yet" : "", saving: "Saving to Gmail drafts…", saved: "Saved in Gmail drafts", error: "Couldn't save" }[state];
  const aiLocked = !ai?.ai_enabled;

  return (
    <>
      <Top title={title} back>
        <button className="btn btn-primary btn-sm" disabled={!canSend} onClick={() => send()} data-tip={canSend ? "Send  (Ctrl + Enter)" : "Add a recipient first"}>{busy ? "Sending…" : "Send"}</button>
        <button className="btn btn-ghost btn-sm" onClick={discard} data-tip="Delete this draft">Discard</button>
      </Top>
      <section className="page" style={{ maxWidth: 1000 }}>
        {scheduled && (
          <Banner tone="ok" action="Unschedule" onAction={unschedule}>Scheduled to send {fullTime(scheduled.send_at)}. Changes you make here are sent too.</Banner>
        )}
        {conflict && (
          <div className="banner warn" role="alert">
            <span>This draft was changed on another device or in Gmail{conflict.subject ? ` (“${conflict.subject}”)` : ""}. Saving is paused so neither version is lost.</span>
            <button className="btn btn-ghost btn-sm" onClick={loadTheirs} data-tip="Replace what's here with the other device's version">Load that version</button>
            <button className="btn btn-ghost btn-sm" onClick={keepMine} data-tip="Save what's here over the other version">Keep mine</button>
          </div>
        )}
        {badRecipients.length > 0 && <Banner tone="err">Check {badRecipients.map(bareOf).join(", ")}: not an email address.</Banner>}
        <div className="compose">
          <div className="compose-row">
            <label htmlFor="from">From</label>
            {replying || mode === "forward" || threading.in_reply_to || (draft?.attachments.length ?? 0) > 0
              ? <span data-tip="Replies, forwards and drafts with attachments go out from this account">{accounts.find((a) => a.id === accountId)?.email}</span>
              : <Select id="from" value={accountId} options={accountOptions} onChange={changeAccount} ariaLabel="Send from" />}
            <span />
          </div>
          <div className="compose-row">
            <label>To</label>
            <Recipients value={to} onChange={edit(setTo)} label="To" autoFocus={mode === "forward" || (mode === "new" && !to.length)} />
            {!showCc && <button className="btn btn-ghost btn-sm" onClick={() => setShowCc(true)} data-tip="Add Cc and Bcc">Cc Bcc</button>}
          </div>
          {showCc && <>
            <div className="compose-row"><label>Cc</label><Recipients value={cc} onChange={edit(setCc)} label="Cc" /><span /></div>
            <div className="compose-row"><label>Bcc</label><Recipients value={bcc} onChange={edit(setBcc)} label="Bcc" /><span data-tip="Recipients don't see who is in Bcc" className="dim" style={{ fontSize: 12 }}>hidden</span></div>
          </>}
          <div className="compose-row">
            <label htmlFor="subj">Subject</label>
            <TextField id="subj" value={subject} onChange={edit(setSubject)} maxLength={998} ariaLabel="Subject" />
            <span />
          </div>
          {aiOpen && (
            <div className="ai-box">
              <div className="inline" style={{ marginBottom: 8 }}>
                {["Accept and confirm", "Decline politely", "Ask for more details", "Say thanks"].map((q) => (
                  <button key={q} className="chip" disabled={aiBusy} onClick={() => aiDraft(q)}>{q}</button>
                ))}
              </div>
              <div className="inline" style={{ alignItems: "flex-start" }}>
                <div style={{ flex: 1 }}><TextField value={aiText} onChange={setAiText} onEnter={() => aiDraft(aiText)} placeholder="Or say what to write, e.g. yes to Friday 3 PM, ask about the dress code" maxLength={600} ariaLabel="What the reply should say" /></div>
                <button className="btn btn-primary btn-sm" style={{ height: 42 }} disabled={aiBusy} onClick={() => aiDraft(aiText)}>{aiBusy ? "Writing…" : "Write it"}</button>
              </div>
              <p className="dim" style={{ fontSize: 12.5, marginTop: 8 }}>Uses your own AI key. Phone numbers and IDs are hidden from it. It only fills the text box; you read it and press Send.</p>
            </div>
          )}
          <textarea ref={bodyRef} className="compose-body" value={body} onChange={(e) => edit(setBody)(e.target.value)} aria-label="Message" rows={14} spellCheck />
          {mode === "forward" && forwardFiles.length > 0 && !draft && <p className="dim" style={{ padding: "0 14px 10px", fontSize: 13 }}>Attaching {forwardFiles.length} file{forwardFiles.length === 1 ? "" : "s"} from the original…</p>}
          {draft && draft.attachments.length > 0 && (
            <div className="compose-atts">
              {draft.attachments.map((a) => (
                <span key={`${a.index}-${a.filename}`} className="chip" data-tip={`${a.mime} · ${size(a.size)}`}>📎 {a.filename} <span className="dim">{size(a.size)}</span>
                  <span className="x" role="button" tabIndex={0} aria-label={`Remove ${a.filename}`} onClick={() => removeAttachment(a.index)} onKeyDown={(e) => e.key === "Enter" && removeAttachment(a.index)}>✕</span></span>
              ))}
              <span className="dim" style={{ fontSize: 12, alignSelf: "center" }}>{size(draft.attachments_size)} of 25 MB</span>
            </div>
          )}
          <div className="compose-foot">
            <button className="btn btn-primary btn-sm" disabled={!canSend} onClick={() => send()} data-tip={`Send. You can undo for ${settings?.undo_send_seconds ?? 10} s  (Ctrl + Enter)`}>{busy ? "Sending…" : "Send"}</button>
            <Select value={later} ariaLabel="Send later" onChange={(v) => {
              if (v === "custom") { setLater("custom"); return; }
              const c = laters.find((x) => x.value === v);
              if (c) send(c.when);
            }} options={[{ value: "", label: "Send later…" }, ...laters.map((l) => ({ value: l.value, label: l.label })), { value: "custom", label: "Pick a date and time…" }]} disabled={!canSend} />
            {later === "custom" && <>
              <input type="datetime-local" className="input" style={{ width: 220 }} value={customLater} onChange={(e) => setCustomLater(e.target.value)} aria-label="Send at" min={new Date(Date.now() + 120000).toISOString().slice(0, 16)} />
              <button className="btn btn-ghost btn-sm" disabled={!canSend || !customLater} onClick={() => { const d = new Date(customLater); if (d.getTime() < Date.now() + 60000) toast("Pick a time at least a minute from now"); else send(d); }}>Schedule</button>
            </>}
            <Select value={followUp} ariaLabel="Remind me if no reply" onChange={setFollowUp} options={[
              { value: "0", label: "No reminder" }, { value: "1", label: "Remind me if no reply in 1 day" }, { value: "2", label: "…in 2 days" },
              { value: "3", label: "…in 3 days" }, { value: "7", label: "…in a week" }]} />
            <button className="btn btn-ghost btn-sm" onClick={() => fileInput.current?.click()} data-tip="Attach files (25 MB in total)">Attach…</button>
            <button className="btn btn-ghost btn-sm" onClick={() => setTemplatesOpen(true)} data-tip="Insert a reusable canned reply snippet">📋 Templates</button>
            <input ref={fileInput} type="file" multiple hidden onChange={(e) => { const files = Array.from(e.target.files ?? []); e.target.value = ""; if (files.length) attach(files); }} />
            {replying && (
              <button className="btn btn-ghost btn-sm" disabled={aiLocked} onClick={() => setAiOpen((o) => !o)}
                data-tip={aiLocked ? "Add an API key to enable (Settings → AI provider)" : "Let your AI key draft the reply; you review it"}>✦ Draft with AI{aiLocked && <span className="dim" style={{ fontSize: 11.5, marginLeft: 8, color: "var(--warn)" }}>Add an API key to enable</span>}</button>
            )}
            <span className="save-state" aria-live="polite">{saveText}</span>
          </div>
        </div>
        {templatesOpen && (
          <TemplateDialog
            onClose={() => setTemplatesOpen(false)}
            onSelect={(tpl) => {
              edit(setBody)(body ? `${body}\n\n${tpl}` : tpl);
              toast("Template inserted");
            }}
          />
        )}
      </section>
    </>
  );
}

function TemplateDialog({
  onClose,
  onSelect,
}: {
  onClose: () => void;
  onSelect: (body: string) => void;
}) {
  const [list, setList] = useState<ReplyTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<ReplyTemplate | "new" | null>(null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [shortcut, setShortcut] = useState("");
  const [saving, setSaving] = useState(false);

  const load = async () => {
    try {
      const res = await get<ReplyTemplateListResult>("/templates");
      setList(res.templates);
    } catch (e) {
      toast(errorText(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const openEditor = (t: ReplyTemplate | "new") => {
    setEditing(t);
    if (t === "new") {
      setTitle("");
      setBody("");
      setShortcut("");
    } else {
      setTitle(t.title);
      setBody(t.body);
      setShortcut(t.shortcut || "");
    }
  };

  const save = async () => {
    if (!title.trim() || !body.trim()) {
      toast("Title and body are required");
      return;
    }
    setSaving(true);
    try {
      if (editing === "new") {
        await post("/templates", { title, body, shortcut: shortcut.trim() || null });
        toast("Template created");
      } else if (editing) {
        await patch(`/templates/${editing.id}`, { title, body, shortcut: shortcut.trim() || null });
        toast("Template updated");
      }
      setEditing(null);
      load();
    } catch (e) {
      toast(errorText(e));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (t: ReplyTemplate) => {
    if (!(await confirmDialog({ title: `Delete "${t.title}"?`, body: "This canned reply template will be permanently removed.", confirm: "Delete", danger: true }))) return;
    try {
      await del(`/templates/${t.id}`);
      toast("Template deleted");
      load();
    } catch (e) {
      toast(errorText(e));
    }
  };

  return (
    <Modal title={editing ? (editing === "new" ? "New Template" : "Edit Template") : "Reply Templates (Canned Replies)"} onClose={onClose}>
      {editing ? (
        <div className="stack" style={{ gap: 14 }}>
          <div className="field">
            <label>Title</label>
            <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Interview Availability" autoFocus />
          </div>
          <div className="field">
            <label>Shortcut (optional)</label>
            <input className="input" value={shortcut} onChange={(e) => setShortcut(e.target.value)} placeholder="e.g. /avail" />
          </div>
          <div className="field">
            <label>Template Body</label>
            <textarea
              className="compose-body"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={8}
              placeholder="Write the canned reply text here..."
              style={{ width: "100%", marginTop: 6 }}
            />
          </div>
          <div className="inline" style={{ justifyContent: "flex-end", marginTop: 8 }}>
            <button className="btn btn-ghost btn-sm" onClick={() => setEditing(null)}>Cancel</button>
            <button className="btn btn-primary btn-sm" disabled={saving || !title.trim() || !body.trim()} onClick={save}>
              {saving ? "Saving…" : "Save Template"}
            </button>
          </div>
        </div>
      ) : (
        <div className="stack" style={{ gap: 12 }}>
          <div className="inline" style={{ justifyContent: "space-between" }}>
            <span className="dim" style={{ fontSize: 13 }}>Choose a template to insert into your email, or manage templates.</span>
            <button className="btn btn-primary btn-sm" onClick={() => openEditor("new")}>+ New Template</button>
          </div>
          {loading && <div className="card dim">Loading templates…</div>}
          {!loading && list.length === 0 && (
            <div className="card dim" style={{ textAlign: "center", padding: "24px 12px" }}>
              No reply templates saved yet. Create one to insert pre-written replies with a single click.
            </div>
          )}
          {!loading && list.length > 0 && (
            <div className="list" style={{ maxHeight: 380, overflowY: "auto" }}>
              {list.map((t) => (
                <div key={t.id} className="row" style={{ alignItems: "flex-start", gap: 10 }}>
                  <div className="main" style={{ flex: 1 }}>
                    <div className="inline" style={{ gap: 8 }}>
                      <span className="who" style={{ fontWeight: 700 }}>{t.title}</span>
                      {t.shortcut && <span className="chip" style={{ fontSize: 11, padding: "2px 6px" }}>{t.shortcut}</span>}
                    </div>
                    <div className="subj" style={{ whiteSpace: "pre-wrap", maxHeight: 54, overflow: "hidden", textOverflow: "ellipsis", fontSize: 13, marginTop: 4, color: "var(--text-2)" }}>
                      {t.body}
                    </div>
                  </div>
                  <div className="inline" style={{ gap: 6 }}>
                    <button className="btn btn-primary btn-sm" onClick={() => { onSelect(t.body); onClose(); }} title="Insert into message">
                      Insert
                    </button>
                    <button className="chip" onClick={() => openEditor(t)} title="Edit template">Edit</button>
                    <button className="chip" onClick={() => remove(t)} title="Delete template">✕</button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}

/** To / Cc / Bcc: addresses as chips. Comma, Enter, Tab or leaving the field turns typed text
 * into chips; Backspace on an empty field removes the last one; senders you've had mail from are
 * suggested as you type. */
function Recipients({ value, onChange, label, autoFocus }: { value: string[]; onChange: (v: string[]) => void; label: string; autoFocus?: boolean }) {
  const [text, setText] = useState("");
  const [hints, setHints] = useState<{ label: string; detail: string }[]>([]);
  const [sel, setSel] = useState(0);

  useEffect(() => {
    const q = text.trim();
    if (q.length < 2) { setHints([]); return; }
    const t = window.setTimeout(() => {
      get<{ senders: { label: string; detail: string }[] }>("/search/suggest", { q })
        .then((r) => { setHints(r.senders.filter((s) => !value.some((v) => bareOf(v).toLowerCase() === s.detail.toLowerCase()))); setSel(0); })
        .catch(() => setHints([]));
    }, 180);
    return () => window.clearTimeout(t);
  }, [text, value]);

  function add(raw: string) {
    const parts = raw.split(/[,;\n]+/).map((s) => s.trim()).filter(Boolean);
    if (!parts.length) return;
    const next = [...value];
    for (const p of parts) if (!next.some((v) => bareOf(v).toLowerCase() === bareOf(p).toLowerCase())) next.push(p);
    onChange(next);
    setText("");
    setHints([]);
  }
  const pick = (h: { label: string; detail: string }) => add(h.label && h.label !== h.detail ? `${h.label.replace(/[<>",]/g, "")} <${h.detail}>` : h.detail);

  return (
    <div className="rcpt">
      {value.map((v, i) => (
        <span key={v + i} className={`chip ${EMAIL.test(bareOf(v)) ? "" : "bad"}`} data-tip={bareOf(v)}>
          {v.replace(/\s*<[^>]+>/, "") || v}
          <span className="x" role="button" tabIndex={0} aria-label={`Remove ${v}`} onClick={() => onChange(value.filter((_, j) => j !== i))}>✕</span>
        </span>
      ))}
      <input value={text} aria-label={label} autoFocus={autoFocus} placeholder={value.length ? "" : "Name or address"} inputMode="email"
        onChange={(e) => { const v = e.target.value; if (/[,;]/.test(v)) add(v); else setText(v); }}
        onBlur={() => window.setTimeout(() => add(text), 120)}
        onPaste={(e) => { const t = e.clipboardData.getData("text"); if (/[,;\n]/.test(t)) { e.preventDefault(); add(text + t); } }}
        onKeyDown={(e) => {
          if (hints.length && (e.key === "ArrowDown" || e.key === "ArrowUp")) { e.preventDefault(); setSel((s) => (s + (e.key === "ArrowDown" ? 1 : hints.length - 1)) % hints.length); }
          else if ((e.key === "Enter" || e.key === "Tab") && hints.length && text.trim()) { e.preventDefault(); pick(hints[sel]); }
          else if ((e.key === "Enter" || (e.key === "Tab" && text.trim())) && text.trim()) { e.preventDefault(); add(text); }
          else if (e.key === "Backspace" && !text && value.length) onChange(value.slice(0, -1));
          else if (e.key === "Escape") setHints([]);
        }} />
      {hints.length > 0 && (
        <div className="rcpt-menu" role="listbox">
          {hints.map((h, i) => (
            <button key={h.detail} role="option" aria-selected={i === sel} className={i === sel ? "on" : ""} onMouseDown={(e) => { e.preventDefault(); pick(h); }}>
              {h.label}{h.label !== h.detail && <small>{h.detail}</small>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

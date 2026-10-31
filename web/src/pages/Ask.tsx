import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, get, post, type Mail } from "../api";
import { Icon, MailRow, Tag, errorText, toast } from "../components";
import { fullTime } from "../util";
import type { AskSelection } from "../bulk";

/** Sift AI / Ask Sift (backend: app/assistant.py). One box for anything the app can do, in plain
 * words. Each request is one small AI call that makes a plan of the app's own actions. Before
 * anything changes the plan shows every step, what it will touch (folders, groups, timelines,
 * rules, the first mails) and the tokens it may use; lookups run at once, changes wait for Run
 * (Gmail changes are marked; replies and forwards become drafts, never sent). Sidebar or "a". */

interface Step { action: string; kind: "read" | "write" | "gmail"; preview: string | null; error: string | null; targets: string[]; tokens: number }
interface Result {
  ok: boolean; text: string; mail?: Mail[]; task_id?: string;
  todos?: { id: string; title: string; due_at: string | null; done: boolean }[];
  timelines?: { id: string; company: string; last: string | null; deadline: string | null }[];
  timeline?: { id: string; kind: string; occurred_at: string; title?: string | null; summary?: string | null }[];
  items?: { id: string; name: string; page: string; detail?: string | null }[];
  link?: { page: string; id?: string; q?: string };
  rule_draft?: unknown;
}
export interface Run {
  id: string; text: string; reply: string | null; status: string; steps: Step[]; results: Result[];
  needs_confirm: boolean; changes_gmail: boolean; tokens: number; estimate: number; created_at: string | null;
}

const THESE_EXAMPLES = [
  "Mark these read and file them in a folder Later",
  "Put these on the Acme timeline",
  "Make to-dos from these",
];

const EXAMPLES = [
  "Make a group Internships for internship offers and add old ones too",
  "New mail from Nvidia goes to the Nvidia folder and a group Nvidia updates",
  "What's due this week?",
  "Draft a reply to Riya saying Thursday 4 pm works",
  "Archive bank alerts older than a month",
  "Close every timeline that has a result and delete done to-dos",
];

const PAGES: Record<string, string> = {
  feed: "/", todo: "/todo", opportunities: "/opportunities", folders: "/folders", groups: "/groups", rules: "/rules",
  settings: "/settings", outbox: "/outbox", silenced: "/silenced", usage: "/usage", search: "/search",
};

function linkTo(l: Result["link"]): { to: string; state?: unknown } | null {
  if (!l) return null;
  if (l.page === "opportunity" && l.id) return { to: `/opportunities/${l.id}` };
  if (l.page === "folder" && l.id) return { to: `/folders/${l.id}` };
  if (l.page === "group" && l.id) return { to: `/groups/${l.id}` };
  if (l.page === "draft" && l.id) return { to: `/compose?draft=${l.id}` };
  if (l.page === "search") return { to: l.q ? `/search?q=${encodeURIComponent(l.q)}` : "/search" };
  return PAGES[l.page] ? { to: PAGES[l.page] } : null;
}

export function AskPanel({ onClose, selection = null, onDropSelection }: { onClose: () => void; selection?: AskSelection | null; onDropSelection?: () => void }) {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  // what asking costs, shown before asking (no AI call); what running costs is shown with the plan
  const [cost, setCost] = useState<{ tokens: number; ai_enabled: boolean } | null>(null);
  const ids = selection ? { message_ids: selection.message_ids ?? [], group_ids: selection.group_ids ?? [], opportunity_ids: selection.opportunity_ids ?? [], folder_ids: selection.folder_ids ?? [] } : null;
  const selKey = JSON.stringify(ids);
  useEffect(() => {
    post<{ tokens: number; ai_enabled: boolean }>("/assistant/estimate", ids ?? undefined).then(setCost).catch(() => setCost(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selKey]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [busy, setBusy] = useState<string | null>(null);  // "ask" or a run id
  const box = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => { get<Run[]>("/assistant/runs").then((r) => setRuns(r.slice(0, 8).reverse())).catch(() => {}); box.current?.focus(); }, []);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [runs.length, busy]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [onClose]);

  const replace = (r: Run) => setRuns((rs) => rs.map((x) => (x.id === r.id ? r : x)));

  async function ask(words?: string) {
    const t = (words ?? text).trim();
    if (!t || busy) return;
    setBusy("ask");
    try {
      const r = await post<Run>("/assistant", { text: t, ...(ids ? { selection: ids } : {}) });
      setRuns((rs) => [...rs.slice(-7), r]);
      setText("");
    } catch (e) {
      toast(e instanceof ApiError && e.status === 0 ? "Ask Sift needs the server." : errorText(e));
    } finally { setBusy(null); box.current?.focus(); }
  }
  async function run(r: Run) {
    setBusy(r.id);
    try { replace(await post<Run>(`/assistant/${r.id}/run`)); dispatchEvent(new Event("sift:folders")); } catch (e) { toast(errorText(e)); } finally { setBusy(null); }
  }
  async function cancel(r: Run) {
    try { replace(await post<Run>(`/assistant/${r.id}/cancel`)); } catch (e) { toast(errorText(e)); }
  }
  function open(l: Result["link"], result: Result) {
    if (l?.page === "rule_draft") { navigate("/rules/new", { state: { draft: result.rule_draft, origin: "english" } }); onClose(); return; }
    const target = linkTo(l);
    if (target) { navigate(target.to); onClose(); }
  }

  return (
    <div className="scrim ask-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <aside className="ask" role="dialog" aria-modal="true" aria-label="Ask Sift">
        <header className="ask-h">
          <Icon name="spark" /><h3>Ask Sift</h3>
          <span className="dim ask-sub">Anything the app can do. You see what it touches and the tokens first; changes wait for your OK.</span>
          <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close" data-tip="Close  (Esc)">✕</button>
        </header>
        <div className="ask-log">
          {runs.length === 0 && !busy && (
            <div className="ask-empty">
              <p>Tell Sift what to do, like you'd tell a person. Each request is one small AI call with your own key.</p>
              <div className="ask-ex">{(selection ? THESE_EXAMPLES : EXAMPLES).map((x) => <button key={x} className="chip" onClick={() => setText(x)}>{x}</button>)}</div>
            </div>
          )}
          {runs.map((r) => <RunView key={r.id} r={r} busy={busy === r.id} onRun={() => run(r)} onCancel={() => cancel(r)} onOpen={open}
            onMail={(id) => { navigate(`/mail/${id}`); onClose(); }} />)}
          {busy === "ask" && <div className="ask-me thinking"><span className="dot-pulse" /> Planning…</div>}
          <div ref={end} />
        </div>
        <div className="ask-bottom">
          {selection && (
            <div className="ask-sel">
              <span>✦ <b>{selection.label}</b> selected. Say <i>these</i> to act on them; the AI only sees how many.</span>
              <button className="btn btn-ghost btn-sm" onClick={onDropSelection} aria-label="Ask without the selection" data-tip="Ask without the selection">✕</button>
            </div>
          )}
          <div className="ask-cost-before" aria-live="polite">
            {cost && !cost.ai_enabled ? "Add your AI key in Settings to use Ask Sift."
              : cost ? `Asking uses about ${cost.tokens.toLocaleString()} tokens of your key. Changes show their own estimate before you press Run.` : ""}
          </div>
          <form className="ask-in" onSubmit={(e) => { e.preventDefault(); ask(); }}>
            <textarea ref={box} value={text} maxLength={600} rows={2} placeholder={selection ? "e.g. archive these and add them to the Bank group" : "e.g. make timelines from Placements → Nvidia"}
              onChange={(e) => setText(e.target.value)} aria-label="What should Sift do?"
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); } }} />
            <button className="btn btn-primary" disabled={!text.trim() || !!busy} data-tip="Plan it  (Enter)">Ask</button>
          </form>
        </div>
      </aside>
    </div>
  );
}

function RunView({ r, busy, onRun, onCancel, onOpen, onMail }: {
  r: Run; busy: boolean; onRun: () => void; onCancel: () => void; onOpen: (l: Result["link"], res: Result) => void; onMail: (id: string) => void;
}) {
  const ran = r.results.length > 0;
  return (
    <div className="ask-turn">
      <div className="ask-me">{r.text}</div>
      <div className="ask-sift">
        {r.reply && <p className="ask-reply">{r.reply}</p>}
        {r.steps.length > 0 && (
          <ol className="ask-steps">
            {r.steps.map((s, i) => {
              const res = r.results[i];
              return (
                <li key={i} className={s.error ? "bad" : res ? (res.ok ? "ok" : "bad") : ""}>
                  <div className="ask-step">
                    <span className="ask-n">{i + 1}</span>
                    <span className="grow">{s.preview}</span>
                    {s.tokens > 0 && !s.error && <Tag tip="AI tokens this step may use with your key when it runs">~{s.tokens.toLocaleString()} tokens</Tag>}
                    {s.kind === "gmail" && <Tag tone="warn" tip="This step changes mail in Gmail (drafts are never sent)">Gmail</Tag>}
                    {s.kind === "write" && !ran && !s.error && <Tag tip="Changes something in Sift when you press Run">Change</Tag>}
                  </div>
                  {s.targets.length > 0 && !s.error && (
                    <ul className="ask-targets" aria-label="What this step touches">{s.targets.map((t, j) => <li key={j}>{t}</li>)}</ul>
                  )}
                  {s.error && <div className="ask-err">Can't do this step: {s.error}</div>}
                  {res && <ResultView res={res} onOpen={onOpen} onMail={onMail} />}
                </li>
              );
            })}
          </ol>
        )}
        <div className="ask-foot">
          {r.needs_confirm && <span className="ask-est" data-tip="What running may use, on top of the planning shown at the right">
            {r.estimate > 0 ? `Running may use about ${r.estimate.toLocaleString()} more tokens` : "Running uses no more AI tokens"}</span>}
          {r.needs_confirm && <>
            <button className="btn btn-primary btn-sm" onClick={onRun} disabled={busy}>{busy ? "Running…" : r.changes_gmail ? "Run, including Gmail changes" : "Run"}</button>
            <button className="btn btn-ghost btn-sm" onClick={onCancel} disabled={busy}>Cancel</button>
          </>}
          {r.status === "cancelled" && <span className="dim">Cancelled. Nothing changed.</span>}
          <span className="dim ask-cost" data-tip="Tokens this request used with your key so far (Token usage → Sift AI lists every request)">{r.tokens.toLocaleString()} tokens used</span>
        </div>
      </div>
    </div>
  );
}

function ResultView({ res, onOpen, onMail }: { res: Result; onOpen: (l: Result["link"], res: Result) => void; onMail: (id: string) => void }) {
  return (
    <div className="ask-res">
      <div className="ask-res-t">
        <span>{res.ok ? "✓" : "✕"} {res.text}</span>
        {res.link && (linkTo(res.link) || res.link.page === "rule_draft") && (
          <button className="link" onClick={() => onOpen(res.link, res)}>{res.link.page === "rule_draft" ? "Review rule" : res.link.page === "draft" ? "Open draft" : "Open"}</button>
        )}
      </div>
      {res.mail && res.mail.length > 0 && <div className="list ask-list">{res.mail.map((m) => <MailRow key={m.id} m={m} draggable={false} onOpen={() => onMail(m.id)} />)}</div>}
      {res.todos && res.todos.length > 0 && (
        <ul className="ask-mini">{res.todos.map((t) => <li key={t.id}>{t.title}{t.due_at && <span className="dim"> · due {fullTime(t.due_at)}</span>}</li>)}</ul>
      )}
      {res.timelines && res.timelines.length > 0 && (
        <ul className="ask-mini">{res.timelines.map((o) => <li key={o.id}><button className="link" onClick={() => onOpen({ page: "opportunity", id: o.id }, res)}>{o.company}</button>
          {o.last && <span className="dim"> · {o.last}</span>}{o.deadline && <span className="dim"> · deadline {fullTime(o.deadline)}</span>}</li>)}</ul>
      )}
      {res.items && res.items.length > 0 && (
        <ul className="ask-mini">{res.items.map((x) => <li key={x.id}><button className="link" onClick={() => onOpen({ page: x.page, id: x.id }, res)}>{x.name}</button>
          {x.detail && <span className="dim"> · {x.detail}</span>}</li>)}</ul>
      )}
      {res.timeline && res.timeline.length > 0 && (
        <ul className="ask-mini">{res.timeline.map((e) => <li key={e.id}><b>{e.kind}</b> {e.title || e.summary || ""}<span className="dim"> · {fullTime(e.occurred_at)}</span></li>)}</ul>
      )}
    </div>
  );
}

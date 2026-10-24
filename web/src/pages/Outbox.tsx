/** Outbox (Phase 4): Gmail drafts of every account, mail scheduled to send later, follow-up
 * reminders, and what Sift sent recently (or couldn't send). */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Top } from "../App";
import { del, get, patch, post, type DraftSummary, type FollowUpItem, type OutboxItem } from "../api";
import { Banner, Modal, Tag, confirmDialog, errorText, toast, useLoad } from "../components";
import { withWriteAccess } from "../mailActions";
import { fullTime, relativeTime } from "../util";

type Tab = "drafts" | "scheduled" | "follow" | "recent";

export function OutboxPage() {
  const [tab, setTab] = useState<Tab>("drafts");
  const navigate = useNavigate();
  const drafts = useLoad(() => get<{ drafts: DraftSummary[]; failed_accounts: string[] }>("/compose/drafts"), []);
  const box = useLoad(() => get<{ scheduled: OutboxItem[]; recent: OutboxItem[] }>("/outbox"), []);
  const follows = useLoad(() => get<{ follow_ups: FollowUpItem[] }>("/follow-ups"), []);
  const [moving, setMoving] = useState<OutboxItem | null>(null);
  const reload = () => { drafts.reload(); box.reload(); follows.reload(); };

  const open = (account: string, draft: string) => navigate(`/compose?draft=${account}:${draft}`);
  async function act(fn: () => Promise<unknown>, done: string) {
    try { await fn(); toast(done); reload(); } catch (e) { toast(errorText(e)); }
  }
  async function discard(d: DraftSummary) {
    if (!(await confirmDialog({ title: "Discard this draft?", body: "It's removed from your Gmail drafts too.", confirm: "Discard", danger: true }))) return;
    if (await withWriteAccess(() => del(`/compose/drafts/${d.account_id}/${d.draft_id}`).then(() => true))) { toast("Draft discarded"); reload(); }
  }

  const waiting = (follows.data?.follow_ups ?? []).filter((f) => f.status === "waiting").length;
  const counts: Record<Tab, number | undefined> = {
    drafts: drafts.data?.drafts.length, scheduled: box.data?.scheduled.length, follow: waiting, recent: undefined,
  };
  const TABS: [Tab, string, string][] = [
    ["drafts", "Drafts", "Gmail drafts of every connected account"],
    ["scheduled", "Scheduled", "Mail waiting to be sent later"],
    ["follow", "Follow-ups", "Sent mail you asked to be reminded about if nobody replies"],
    ["recent", "Sent by Sift", "What Sift sent lately, and anything it couldn't send"],
  ];

  return (
    <>
      <Top title="Outbox">
        <button className="btn btn-primary btn-sm" onClick={() => navigate("/compose")} data-tip="Write a new mail  (C)">New mail</button>
      </Top>
      <section className="page">
        <div className="tabs" role="tablist">
          {TABS.map(([t, label, tip]) => (
            <button key={t} role="tab" aria-selected={tab === t} className={`chip ${tab === t ? "on" : ""}`} onClick={() => setTab(t)} data-tip={tip}>
              {label}{counts[t] ? ` · ${counts[t]}` : ""}
            </button>
          ))}
        </div>

        {tab === "drafts" && (
          <>
            {drafts.error && <Banner tone="err" action="Retry" onAction={drafts.reload}>{drafts.error}</Banner>}
            {drafts.data?.failed_accounts.length ? <Banner tone="warn">Couldn't load drafts of {drafts.data.failed_accounts.join(", ")}.</Banner> : null}
            {!drafts.data ? <p className="dim">Loading drafts from Gmail…</p> : !drafts.data.drafts.length ? <div className="list"><p className="empty">No drafts.</p></div> : (
              <div className="list">
                {drafts.data.drafts.map((d) => (
                  <div key={d.account_id + d.draft_id} className="row" style={{ cursor: "pointer" }} onClick={() => open(d.account_id, d.draft_id)}>
                    <div className="main">
                      <div className="who">{d.to || <span className="dim">No recipient</span>}{d.outbox && <Tag tone="normal" tip={`Sends ${fullTime(d.outbox.send_at)}`}>Scheduled</Tag>}</div>
                      <div className="subj"><b>{d.subject || "(no subject)"}</b> <span className="dim">{d.snippet}</span></div>
                    </div>
                    <span className="dim" style={{ fontSize: 12 }} data-tip={d.account_email}>{d.account_email}</span>
                    <span className="time" data-tip={fullTime(new Date(d.updated_ms).toISOString())}>{relativeTime(new Date(d.updated_ms).toISOString())}</span>
                    <button className="btn btn-ghost btn-sm" onClick={(e) => { e.stopPropagation(); discard(d); }} data-tip="Delete this draft">Discard</button>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {tab === "scheduled" && (
          !box.data ? <p className="dim">Loading…</p> : !box.data.scheduled.length ? <div className="list"><p className="empty">Nothing scheduled. In a draft, use "Send later…".</p></div> : (
            <div className="list">
              {box.data.scheduled.map((r) => (
                <div key={r.id} className="row">
                  <div className="main" style={{ cursor: "pointer" }} onClick={() => open(r.account_id, r.draft_id)}>
                    <div className="who">{r.recipients}{r.follow_up_days ? <Tag tip="Reminds you if nobody replies">Follow-up {r.follow_up_days} d</Tag> : null}</div>
                    <div className="subj"><b>{r.subject || "(no subject)"}</b> <span className="dim">· {r.account_email}</span></div>
                    {r.error && <div className="err-text">{r.error}</div>}
                  </div>
                  <span className="time" style={{ color: "var(--text)" }} data-tip="When it sends">{r.status === "sending" ? "Sending…" : fullTime(r.send_at)}</span>
                  {r.status === "scheduled" && <>
                    <button className="btn btn-ghost btn-sm" onClick={() => act(() => post(`/outbox/${r.id}/send-now`), "Sending now")} data-tip="Send it within a few seconds">Send now</button>
                    <button className="btn btn-ghost btn-sm" onClick={() => setMoving(r)} data-tip="Pick another time">Change time</button>
                    <button className="btn btn-ghost btn-sm" onClick={() => act(() => post(`/outbox/${r.id}/cancel`), "Unscheduled. It stays a draft")} data-tip="Don't send; keep it as a draft">Unschedule</button>
                  </>}
                </div>
              ))}
            </div>
          )
        )}

        {tab === "follow" && (
          !follows.data ? <p className="dim">Loading…</p> : !follows.data.follow_ups.length ? <div className="list"><p className="empty">No follow-ups. When sending, pick "Remind me if no reply".</p></div> : (
            <div className="list">
              {follows.data.follow_ups.map((f) => (
                <div key={f.id} className="row">
                  <div className="main" style={{ cursor: "pointer" }} onClick={() => navigate(`/read/${f.account_id}/${f.thread_id}`)}>
                    <div className="who">{f.recipients}</div>
                    <div className="subj"><b>{f.subject || "(no subject)"}</b> <span className="dim">· sent {relativeTime(f.sent_at)} ago</span></div>
                  </div>
                  <Tag tone={f.status === "replied" ? "ok" : f.status === "reminded" ? "warn" : undefined}
                    tip={f.status === "waiting" ? `Reminds you ${fullTime(f.due_at)} unless someone replies` : undefined}>
                    {{ waiting: `Reminds ${fullTime(f.due_at)}`, replied: "Replied", reminded: "No reply, reminded", cancelled: "Cancelled" }[f.status]}
                  </Tag>
                  {f.status === "waiting" && <button className="btn btn-ghost btn-sm" onClick={() => act(() => post(`/follow-ups/${f.id}/cancel`), "Reminder cancelled")}>Cancel</button>}
                </div>
              ))}
            </div>
          )
        )}

        {tab === "recent" && (
          !box.data ? <p className="dim">Loading…</p> : !box.data.recent.length ? <div className="list"><p className="empty">Nothing sent through Sift yet.</p></div> : (
            <div className="list">
              {box.data.recent.map((r) => (
                <div key={r.id} className="row">
                  <div className="main" style={{ cursor: r.status !== "sent" ? "pointer" : r.thread_id ? "pointer" : "default" }}
                    onClick={() => r.status === "sent" ? r.thread_id && navigate(`/read/${r.account_id}/${r.thread_id}`) : open(r.account_id, r.draft_id)}>
                    <div className="who">{r.recipients}</div>
                    <div className="subj"><b>{r.subject || "(no subject)"}</b> <span className="dim">· {r.account_email}</span></div>
                    {r.error && r.status === "failed" && <div className="err-text">{r.error}</div>}
                  </div>
                  <Tag tone={r.status === "failed" ? "urgent" : r.status === "sent" ? "ok" : undefined}>{{ sent: "Sent", failed: "Not sent", cancelled: "Undone", scheduled: "Scheduled", sending: "Sending" }[r.status]}</Tag>
                  <span className="time">{relativeTime(r.sent_at ?? r.send_at)}</span>
                </div>
              ))}
            </div>
          )
        )}
      </section>
      {moving && <MoveDialog item={moving} onClose={() => setMoving(null)} onDone={() => { setMoving(null); reload(); }} />}
    </>
  );
}

function MoveDialog({ item, onClose, onDone }: { item: OutboxItem; onClose: () => void; onDone: () => void }) {
  const local = (iso: string) => { const d = new Date(iso); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };
  const [value, setValue] = useState(local(item.send_at));
  async function save() {
    const d = new Date(value);
    if (Number.isNaN(d.getTime()) || d.getTime() < Date.now() + 60000) { toast("Pick a time at least a minute from now"); return; }
    try { await patch(`/outbox/${item.id}`, { send_at: d.toISOString() }); toast(`Sends ${fullTime(d.toISOString())}`); onDone(); } catch (e) { toast(errorText(e)); }
  }
  return (
    <Modal title="Send at another time" onClose={onClose} foot={<>
      <button className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
      <button className="btn btn-primary btn-sm" onClick={save}>Save</button>
    </>}>
      <div className="field"><label htmlFor="when">Send at</label>
        <input id="when" type="datetime-local" className="input" value={value} onChange={(e) => setValue(e.target.value)} /></div>
    </Modal>
  );
}

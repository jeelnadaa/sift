import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { del, get, patch, post, type Opportunity, type OpportunityDetail, type TimelineEvent } from "../api";
import { Top } from "../App";
import { AskButton, SelectBox, ThingBar, runBulk, runMany, useSelection } from "../bulk";
import { Avatar, Banner, confirmDialog, errorText, inputDialog, Modal, Select, Tag, TextField, toast, Toggle, useLoad } from "../components";
import { fullTime, googleCalendarUrl, humanize, safeUrl, toLocalInput } from "../util";

export const STAGES: { value: string; label: string }[] = [
  { value: "announcement", label: "Announcement" }, { value: "registration", label: "Registration" }, { value: "assessment", label: "Test" },
  { value: "interview", label: "Interview" }, { value: "result", label: "Result" }, { value: "update", label: "Update" },
];

const KIND_TONE: Record<string, string> = { assessment_link: "urgent", interview: "urgent", result: "ok", registration: "normal", placement_announcement: "normal" };

export function Opportunities() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState<"active" | "closed">("active");
  const list = useLoad(() => get<Opportunity[]>("/opportunities", { status }), [status], ["new_mail"]);
  const [creating, setCreating] = useState(false);
  const selected = id ?? list.data?.[0]?.id;
  const sel = useSelection(status);
  const keys = (list.data ?? []).map((o) => o.id);
  async function many(done: string, fn: (id: string) => Promise<unknown>, confirm?: { title: string; body: string }) {
    const ids = [...sel.keys];
    if (confirm && !(await confirmDialog({ ...confirm, confirm: "Delete", danger: true }))) return;
    const ok = await runMany(ids, fn);
    toast(ok === ids.length ? `${done}: ${ok}` : `${done}: ${ok} of ${ids.length}. Try the rest again.`);
    sel.clear();
    list.reload();
  }
  const theirMail = (action: string) => runBulk({ opportunity_ids: [...sel.keys] }, action);

  return (
    <>
      <Top title="Opportunities" refresh><button className="btn btn-primary btn-sm" onClick={() => setCreating(true)} data-tip="Start a company timeline by hand">+ New opportunity</button></Top>
      <section className="page">
        <div className="tabs">
          <button className={`chip ${status === "active" ? "on" : ""}`} onClick={() => setStatus("active")} data-tip="Companies you're still hearing from">Active</button>
          <button className={`chip ${status === "closed" ? "on" : ""}`} onClick={() => setStatus("closed")} data-tip="Timelines you closed">Closed</button>
        </div>
        {list.error && <Banner tone="err">{list.error}</Banner>}
        <ThingBar sel={sel} keys={keys} noun={["timeline", "timelines"]}>
          {status === "active"
            ? <button className="btn btn-ghost btn-sm" onClick={() => many("Closed", (o) => patch(`/opportunities/${o}`, { status: "closed" }))}>Close</button>
            : <button className="btn btn-ghost btn-sm" onClick={() => many("Reopened", (o) => patch(`/opportunities/${o}`, { status: "active" }))}>Reopen</button>}
          <button className="btn btn-ghost btn-sm" onClick={() => theirMail("read")} data-tip="Mark every mail on these timelines read">Mark mail read</button>
          <button className="btn btn-ghost btn-sm" onClick={() => theirMail("archive")} data-tip="Archive every mail on these timelines in Gmail">Archive mail</button>
          <button className="btn btn-ghost btn-sm danger-text" onClick={() => many("Deleted", (o) => del(`/opportunities/${o}`),
            { title: `Delete ${sel.size} timeline${sel.size === 1 ? "" : "s"}?`, body: "The timelines go; the mail on them stays." })}>Delete</button>
          <AskButton sel={{ opportunity_ids: [...sel.keys], label: `${sel.size} timeline${sel.size === 1 ? "" : "s"}` }} />
        </ThingBar>
        <div className="split">
          <div className={`list ${sel.size ? "selecting" : ""}`}>
            {list.data?.length === 0 && <div className="empty">No company drives yet. They appear when placement or hiring mail arrives, or add one by hand.</div>}
            {list.data?.map((o) => (
              <div key={o.id} className={`row click ${o.id === selected ? "sel" : ""}`} onClick={() => navigate(`/opportunities/${o.id}`)}>
                <SelectBox sel={sel} k={o.id} ordered={keys} label={`Select ${o.company}`} />
                <Avatar text={o.company} />
                <div className="main"><div className="who">{o.company}</div><div className="subj">{o.last_kind ? humanize(o.last_kind) : "No mail yet"} · {o.events} event{o.events === 1 ? "" : "s"}</div></div>
                {o.deadline && <Tag tone="warn">{fullTime(o.deadline)}</Tag>}
              </div>
            ))}
          </div>
          {selected ? <Timeline key={selected} id={selected} onChanged={list.reload} /> : <div />}
        </div>
      </section>
      {creating && <NewOpportunity onClose={() => setCreating(false)} onCreated={(o) => { setCreating(false); list.reload(); navigate(`/opportunities/${o.id}`); }} />}
    </>
  );
}

function Timeline({ id, onChanged }: { id: string; onChanged: () => void }) {
  const navigate = useNavigate();
  const o = useLoad(() => get<OpportunityDetail>(`/opportunities/${id}`), [id], ["new_mail"]);
  const [editing, setEditing] = useState(false);
  const [aliases, setAliases] = useState("");
  const [section, setSection] = useState<TimelineEvent | "new" | null>(null);
  if (o.error) return <Banner tone="err">{o.error}</Banner>;
  const d = o.data;
  if (!d) return <div className="card dim">Loading…</div>;

  async function save(changes: object) {
    try { await patch(`/opportunities/${id}`, changes); o.reload(); onChanged(); } catch (e) { toast(errorText(e)); }
  }
  async function rename() {
    const name = await inputDialog({ title: "Rename company", label: "Company", initial: d!.company, confirm: "Rename" });
    if (name && name.trim() && name.trim() !== d!.company) save({ company: name.trim() });
  }
  async function remove(e: TimelineEvent) {
    const what = e.manual ? `the section “${e.title}”` : "this mail from the timeline (the mail itself stays)";
    if (!(await confirmDialog({ title: e.manual ? "Remove this section?" : "Take this mail off the timeline?", body: `Removes ${what}.`, confirm: "Remove", danger: true }))) return;
    try { o.setData(await del<OpportunityDetail>(`/opportunities/${id}/events/${e.id}`)); onChanged(); } catch (err) { toast(errorText(err)); }
  }
  return (
    <div className="card">
      <div className="inline" style={{ marginBottom: 6 }}>
        <h2 style={{ margin: 0, fontSize: 34 }}>{d.company}</h2>
        <Tag tone={d.status === "active" ? "ok" : undefined}>{d.status}</Tag>
      </div>
      <div className="muted" style={{ marginBottom: 24 }}>
        {d.aliases.length > 0 && <>Aliases: {d.aliases.join(", ")} · </>}
        {d.deadline ? (
          <>
            Deadline <b style={{ color: "var(--warn)" }}>{fullTime(d.deadline)}</b>
            {googleCalendarUrl({ title: `${d.company} deadline`, deadlineIso: d.deadline, details: `From your ${d.company} timeline in Sift` }) && (
              <a
                className="link"
                style={{ marginLeft: 8 }}
                href={googleCalendarUrl({ title: `${d.company} deadline`, deadlineIso: d.deadline, details: `From your ${d.company} timeline in Sift` })!}
                target="_blank"
                rel="noopener noreferrer"
              >
                📅 Add to Google Calendar ↗
              </a>
            )}
          </>
        ) : "No deadline"}
      </div>
      <div style={{ borderLeft: "2px solid var(--line-2)", marginLeft: 10, paddingLeft: 28, display: "flex", flexDirection: "column", gap: 26 }}>
        {d.timeline.length === 0 && <p className="dim">Nothing on this timeline yet. Mail about {d.company} lands here, or add a section.</p>}
        {d.timeline.map((e) => (
          <div key={e.id} style={{ position: "relative" }}>
            <i className={`dot ${KIND_TONE[e.kind] === "urgent" ? "urgent" : "ok"}`} style={{ position: "absolute", left: -35, top: 6, width: 12, height: 12 }} />
            <Tag tone={KIND_TONE[e.kind]}>{STAGES.find((s) => s.value === e.kind)?.label ?? e.kind}</Tag> <span className="dim mono">{fullTime(e.occurred_at)}</span>
            {e.manual && <span className="dim" style={{ fontSize: 12 }}> · added by you{e.remind ? " · reminds you" : ""}</span>}
            {!e.manual && e.matched_by !== "user" && <span className="dim" style={{ fontSize: 12 }}> · matched by {humanize(e.matched_by)}</span>}
            <span className="tl-tools">
              <button className="chip" onClick={() => setSection(e)} data-tip={e.manual ? "Change this section" : "Change the stage of this mail"}>Edit</button>
              <button className="chip" onClick={() => remove(e)} data-tip={e.manual ? "Remove this section" : "Take this mail off the timeline"}>✕</button>
            </span>
            <div className="who" style={{ marginTop: 4, fontWeight: 700 }}>{e.manual ? e.title : e.summary || e.subject}</div>
            {e.manual && e.note && <div className="muted" style={{ fontSize: 14, whiteSpace: "pre-wrap" }}>{e.note}</div>}
            <div className="muted" style={{ fontSize: 14 }}>
              {e.sender_name && <>From {e.sender_name}{e.account ? ` · ${e.account}` : ""}</>}
              {e.deadline && (
                <>
                  {" "}· Deadline {fullTime(e.deadline)}
                  {googleCalendarUrl({
                    title: `${d.company}: ${e.manual ? e.title : (e.summary || e.subject)}`,
                    deadlineIso: e.deadline,
                    details: e.note || `Stage: ${e.kind}\nFrom: ${e.sender_name || e.account || d.company}\nTimeline in Sift`,
                    location: e.links[0]?.url,
                  }) && (
                    <a
                      className="link"
                      style={{ marginLeft: 6 }}
                      href={googleCalendarUrl({
                        title: `${d.company}: ${e.manual ? e.title : (e.summary || e.subject)}`,
                        deadlineIso: e.deadline,
                        details: e.note || `Stage: ${e.kind}\nFrom: ${e.sender_name || e.account || d.company}\nTimeline in Sift`,
                        location: e.links[0]?.url,
                      })!}
                      target="_blank"
                      rel="noopener noreferrer"
                      title="Add this timeline event to Google Calendar"
                    >
                      📅 Calendar ↗
                    </a>
                  )}
                </>
              )}
              {e.links.map((l) => { const u = safeUrl(l.url); return u && <span key={u}> · <a className="link" href={u} target="_blank" rel="noopener noreferrer">{l.label} ↗</a></span>; })}
              {e.message_id && <> · <a className="link dim" onClick={() => navigate(`/mail/${e.message_id}`)} data-tip="Open the mail this came from">Open mail</a></>}
            </div>
          </div>
        ))}
      </div>
      <div className="inline" style={{ marginTop: 28 }}>
        <button className="btn btn-primary btn-sm" onClick={() => setSection("new")} data-tip="Add a step (test, interview, result…) with its date and time; it takes its place on the timeline">+ Add section</button>
        <button className="btn btn-ghost btn-sm" onClick={rename} data-tip="Change the company's name">Rename</button>
        <button className="btn btn-ghost btn-sm" onClick={() => { setAliases(d.aliases.join(", ")); setEditing(true); }} data-tip="Other names this company goes by, so its mail lands here">Edit aliases</button>
        <button className="btn btn-ghost btn-sm" onClick={() => save({ status: d.status === "active" ? "closed" : "active" })}>{d.status === "active" ? "Close" : "Reopen"}</button>
        <button className="btn btn-danger btn-sm" style={{ marginLeft: "auto" }} onClick={async () => {
          if (!(await confirmDialog({ title: `Delete the ${d.company} timeline?`, body: "Only the timeline goes. The mail stays in Gmail and in Sift.", confirm: "Delete timeline", danger: true }))) return;
          try { await del(`/opportunities/${id}`); onChanged(); navigate("/opportunities"); } catch (e) { toast(errorText(e)); }
        }} data-tip="Delete for good (mail itself is never deleted)">Delete</button>
      </div>
      {section && <SectionDialog oppId={id} company={d.company} event={section === "new" ? null : section} onClose={() => setSection(null)}
        onSaved={(r) => { setSection(null); o.setData(r); onChanged(); }} />}
      {editing && (
        <Modal title={`Aliases for ${d.company}`} onClose={() => setEditing(false)}
          foot={<><button className="btn btn-ghost btn-sm" onClick={() => setEditing(false)} data-tip="Close without saving">Cancel</button><button className="btn btn-primary btn-sm" onClick={() => { setEditing(false); save({ aliases: aliases.split(",").map((s) => s.trim()).filter(Boolean) }); }} data-tip="Save changes">Save</button></>}>
          <div className="field"><label htmlFor="al">Other names, comma separated</label><TextField id="al" value={aliases} onChange={setAliases} placeholder="Acme, ACME Ltd" /></div>
          <p className="dim" style={{ fontSize: 13, marginTop: 8 }}>Mail naming any of these lands on this timeline.</p>
        </Modal>
      )}
    </div>
  );
}

function NewOpportunity({ onClose, onCreated }: { onClose: () => void; onCreated: (o: Opportunity) => void }) {
  const [company, setCompany] = useState("");
  return (
    <Modal title="New opportunity" onClose={onClose}
      foot={<><button className="btn btn-ghost btn-sm" onClick={onClose} data-tip="Close without saving">Cancel</button><button className="btn btn-primary btn-sm" disabled={!company.trim()} onClick={async () => {
        try { onCreated(await post<Opportunity>("/opportunities", { company: company.trim(), aliases: [] })); } catch (e) { toast(errorText(e)); }
      }}>Create</button></>}>
      <div className="field"><label htmlFor="co">Company</label><TextField id="co" value={company} onChange={setCompany} autoFocus maxLength={200} /></div>
    </Modal>
  );
}

/** Add or change a section by hand. For a mail on the timeline only its stage changes. */
function SectionDialog({ oppId, company, event, onClose, onSaved }: {
  oppId: string; company: string; event: TimelineEvent | null; onClose: () => void; onSaved: (r: OpportunityDetail) => void;
}) {
  const mail = !!event && !event.manual;
  const [kind, setKind] = useState(event?.kind ?? "interview");
  const [title, setTitle] = useState(event?.title ?? "");
  const [note, setNote] = useState(event?.note ?? "");
  const [when, setWhen] = useState(toLocalInput(event?.occurred_at ?? new Date(Date.now() + 86400000).toISOString()));
  const [remind, setRemind] = useState(event?.remind ?? false);
  const future = when && new Date(when).getTime() > Date.now();
  const ok = mail || (title.trim() && when);

  async function save() {
    const body = mail ? { kind } : { kind, title: title.trim(), note: note.trim() || null, at: new Date(when).toISOString(), remind: remind && !!future };
    try {
      onSaved(event
        ? await patch<OpportunityDetail>(`/opportunities/${oppId}/events/${event.id}`, body)
        : await post<OpportunityDetail>(`/opportunities/${oppId}/sections`, body));
    } catch (e) { toast(errorText(e)); }
  }
  return (
    <Modal title={event ? (mail ? "Change the stage" : "Edit section") : `Add a section to ${company}`} onClose={onClose}
      foot={<><button className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button><button className="btn btn-primary btn-sm" disabled={!ok} onClick={save}>{event ? "Save" : "Add"}</button></>}>
      <div className="stack">
        <div className="field"><label htmlFor="sk">Stage</label><Select id="sk" value={kind} options={STAGES} onChange={setKind} ariaLabel="Stage" /></div>
        {mail ? <p className="dim" style={{ fontSize: 13 }}>A mail keeps its own subject and time.</p> : <>
          <div className="field"><label htmlFor="st">Title</label><TextField id="st" value={title} onChange={setTitle} autoFocus maxLength={200} placeholder="e.g. Technical interview, round 2" /></div>
          <div className="field"><label htmlFor="sw">Date and time</label>
            <input id="sw" className="input" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} /></div>
          <p className="dim" style={{ fontSize: 13, marginTop: -4 }}>The section takes its place on the timeline by this date and time.</p>
          <div className="field"><label htmlFor="sn">Note (optional)</label>
            <textarea id="sn" className="input" rows={3} value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} placeholder="Venue, link, what to prepare…" /></div>
          <span className="inline dim" style={{ fontSize: 13.5 }} data-tip={future ? "Reminders 24 h and 2 h before; it can become the company's next deadline" : "Only for a date in the future"}>
            <Toggle on={remind && !!future} disabled={!future} onChange={setRemind} label="Remind me" /> Remind me before it
          </span>
        </>}
      </div>
    </Modal>
  );
}

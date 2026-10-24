import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { del, get, patch, post, type Opportunity, type OpportunityDetail } from "../api";
import { Top } from "../App";
import { Avatar, Banner, Modal, Tag, errorText, toast, useLoad } from "../components";
import { fullTime, humanize, safeUrl } from "../util";

const KIND_TONE: Record<string, string> = { assessment_link: "urgent", interview: "urgent", result: "ok", registration: "normal", placement_announcement: "normal" };

export function Opportunities() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState<"active" | "closed">("active");
  const list = useLoad(() => get<Opportunity[]>("/opportunities", { status }), [status]);
  const [creating, setCreating] = useState(false);
  const selected = id ?? list.data?.[0]?.id;

  return (
    <>
      <Top title="Opportunities"><button className="btn btn-primary btn-sm" onClick={() => setCreating(true)}>+ New opportunity</button></Top>
      <section className="page">
        <div className="tabs">
          <button className={`chip ${status === "active" ? "on" : ""}`} onClick={() => setStatus("active")}>Active</button>
          <button className={`chip ${status === "closed" ? "on" : ""}`} onClick={() => setStatus("closed")}>Closed</button>
        </div>
        {list.error && <Banner tone="err">{list.error}</Banner>}
        <div className="split">
          <div className="list">
            {list.data?.length === 0 && <div className="empty">No company drives yet. They appear when placement or hiring mail arrives, or add one by hand.</div>}
            {list.data?.map((o) => (
              <div key={o.id} className={`row click ${o.id === selected ? "sel" : ""}`} onClick={() => navigate(`/opportunities/${o.id}`)}>
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
  const o = useLoad(() => get<OpportunityDetail>(`/opportunities/${id}`), [id]);
  const [editing, setEditing] = useState(false);
  const [aliases, setAliases] = useState("");
  if (o.error) return <Banner tone="err">{o.error}</Banner>;
  const d = o.data;
  if (!d) return <div className="card dim">Loading…</div>;

  async function save(changes: object) {
    try { await patch(`/opportunities/${id}`, changes); o.reload(); onChanged(); } catch (e) { toast(errorText(e)); }
  }
  return (
    <div className="card">
      <div className="inline" style={{ marginBottom: 6 }}>
        <h2 style={{ margin: 0, fontSize: 34 }}>{d.company}</h2>
        <Tag tone={d.status === "active" ? "ok" : undefined}>{d.status}</Tag>
      </div>
      <div className="muted" style={{ marginBottom: 24 }}>
        {d.aliases.length > 0 && <>Aliases: {d.aliases.join(", ")} · </>}
        {d.deadline ? <>Deadline <b style={{ color: "var(--warn)" }}>{fullTime(d.deadline)}</b></> : "No deadline"}
      </div>
      <div style={{ borderLeft: "2px solid var(--line-2)", marginLeft: 10, paddingLeft: 28, display: "flex", flexDirection: "column", gap: 26 }}>
        {d.timeline.length === 0 && <p className="dim">No mail on this timeline yet.</p>}
        {d.timeline.map((e) => (
          <div key={e.id} style={{ position: "relative" }}>
            <i className={`dot ${KIND_TONE[e.kind] === "urgent" ? "urgent" : "ok"}`} style={{ position: "absolute", left: -35, top: 6, width: 12, height: 12 }} />
            <Tag tone={KIND_TONE[e.kind]}>{e.kind}</Tag> <span className="dim mono">{fullTime(e.occurred_at)}</span>
            {e.matched_by !== "user" && <span className="dim" style={{ fontSize: 12 }}> · matched by {humanize(e.matched_by)}</span>}
            <div className="who" style={{ marginTop: 4, fontWeight: 700 }}>{e.summary || e.subject}</div>
            <div className="muted" style={{ fontSize: 14 }}>
              {e.sender_name && <>From {e.sender_name}{e.account ? ` · ${e.account}` : ""}</>}
              {e.deadline && <> · Deadline {fullTime(e.deadline)}</>}
              {e.links.map((l) => { const u = safeUrl(l.url); return u && <span key={u}> · <a className="link" href={u} target="_blank" rel="noopener noreferrer">{l.label} ↗</a></span>; })}
              {e.message_id && <> · <a className="link dim" onClick={() => navigate(`/mail/${e.message_id}`)}>Open mail</a></>}
            </div>
          </div>
        ))}
      </div>
      <div className="inline" style={{ marginTop: 28 }}>
        <button className="btn btn-ghost btn-sm" onClick={() => { setAliases(d.aliases.join(", ")); setEditing(true); }}>Edit aliases</button>
        <button className="btn btn-ghost btn-sm" onClick={() => save({ status: d.status === "active" ? "closed" : "active" })}>{d.status === "active" ? "Close" : "Reopen"}</button>
        <button className="btn btn-danger btn-sm" style={{ marginLeft: "auto" }} onClick={async () => {
          if (!confirm(`Delete the ${d.company} timeline? The mail stays.`)) return;
          try { await del(`/opportunities/${id}`); onChanged(); navigate("/opportunities"); } catch (e) { toast(errorText(e)); }
        }}>Delete</button>
      </div>
      {editing && (
        <Modal title={`Aliases for ${d.company}`} onClose={() => setEditing(false)}
          foot={<><button className="btn btn-ghost btn-sm" onClick={() => setEditing(false)}>Cancel</button><button className="btn btn-primary btn-sm" onClick={() => { setEditing(false); save({ aliases: aliases.split(",").map((s) => s.trim()).filter(Boolean) }); }}>Save</button></>}>
          <div className="field"><label htmlFor="al">Other names, comma separated</label><input id="al" className="input" value={aliases} onChange={(e) => setAliases(e.target.value)} placeholder="Acme, ACME Ltd" /></div>
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
      foot={<><button className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button><button className="btn btn-primary btn-sm" disabled={!company.trim()} onClick={async () => {
        try { onCreated(await post<Opportunity>("/opportunities", { company: company.trim(), aliases: [] })); } catch (e) { toast(errorText(e)); }
      }}>Create</button></>}>
      <div className="field"><label htmlFor="co">Company</label><input id="co" className="input" value={company} onChange={(e) => setCompany(e.target.value)} autoFocus /></div>
    </Modal>
  );
}

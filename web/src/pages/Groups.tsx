import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { get, patch, post, put, type Draft, type Group, type GroupingStatus } from "../api";
import { Top } from "../App";
import { Banner, FolderPicker, GroupRow, MailRow, Modal, Toggle, errorText, toast, useLoad } from "../components";

export function Groups() {
  const navigate = useNavigate();
  const status = useLoad(() => get<GroupingStatus>("/grouping"));
  const on = status.data?.grouping_enabled === "yes";
  const groups = useLoad(async () => (on ? get<Group[]>("/groups") : []), [on]);

  async function set(answer: "yes" | "no") {
    try { await post("/grouping", { answer }); status.reload(); toast(answer === "yes" ? "Grouping on. The last 30 days are being grouped." : "Grouping off"); } catch (e) { toast(errorText(e)); }
  }
  return (
    <>
      <Top title="Groups">
        {on && <button className="btn btn-ghost btn-sm" onClick={async () => { await post("/groups/collapse-all", { collapsed: true }).catch(() => {}); groups.reload(); }}>Collapse all</button>}
      </Top>
      <section className="page">
        {status.data && (on
          ? <Banner tone="warn" action="Turn off" onAction={() => set("no")}>Grouping is <b>on</b>. It only changes how mail is displayed. Notifications are unaffected.</Banner>
          : <Banner tone="ok" action="Turn on" onAction={() => set("yes")}>Grouping is <b>off</b>. Turn it on to stack similar mail (bank alerts, newsletters, one company's drive) into one row. Display only.</Banner>)}
        {on && (
          <div className="list">
            {groups.data?.length === 0 && <div className="empty">No groups yet. A group shows once three similar mails arrive.</div>}
            {groups.data?.map((g) => <GroupRow key={g.id} g={g} onOpen={() => navigate(`/groups/${g.id}`)} />)}
          </div>
        )}
      </section>
    </>
  );
}

export function GroupDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const g = useLoad(() => get<Group>(`/groups/${id}`), [id]);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [filing, setFiling] = useState<"file" | "rule" | null>(null);
  const [merging, setMerging] = useState(false);
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  async function run(done: string | null, fn: () => Promise<unknown>) {
    try { await fn(); if (done) toast(done); g.reload(); } catch (e) { toast(errorText(e)); }
  }
  async function ruleDraft(action: "silent" | "file", folderId?: string) {
    try {
      const r = await post<{ draft: Draft }>(`/groups/${id}/rule`, { action, folder_id: folderId });
      navigate("/rules/new", { state: { draft: r.draft, origin: "one_tap" } });
    } catch (e) { toast(errorText(e)); }
  }
  const d = g.data;
  const sender = d?.items?.[0]?.sender;
  return (
    <>
      <Top title={d?.title ?? "Group"}>
        <button className="btn btn-ghost btn-sm" onClick={() => navigate(-1)}>Back</button>
        {d && <button className="btn btn-ghost btn-sm" onClick={() => setRenaming(d.title)}>Rename</button>}
      </Top>
      <section className="page">
        {g.error && <Banner tone="err">{g.error}</Banner>}
        {d && (
          <>
            <p className="lede">{d.count} mails · {d.unread} unread{d.urgent ? ` · ${d.urgent} urgent` : ""}. A group only changes how mail is shown; nothing changes in Gmail.</p>
            <div className="set-row" style={{ borderTop: "1px solid var(--line)", marginBottom: 16 }}>
              <div>Mute this group<small>New mail in it won't notify. Urgent mail still does.</small></div>
              <Toggle on={d.muted} label="Mute group" onChange={(v) => run(null, () => patch(`/groups/${id}`, { muted: v }))} />
            </div>
            <div className="tabs">
              <button className="chip" onClick={() => setFiling("file")}>File all in folder</button>
              <button className="chip" onClick={() => setFiling("rule")}>File mail like this…</button>
              <button className="chip" onClick={() => ruleDraft("silent")}>Silence mail like this</button>
              <button className={`chip ${selecting ? "on" : ""}`} onClick={() => { setSelecting(!selecting); setSelected(new Set()); }}>Split</button>
              <button className="chip" onClick={() => setMerging(true)}>Merge into…</button>
              <button className="chip" onClick={async () => {
                const name = prompt("Tag every mail in this group as:");
                if (name?.trim()) run(`Tagged ${d.count} mails`, () => post(`/groups/${id}/tag`, { name: name.trim() }));
              }}>Tag</button>
              {sender && <button className="chip" onClick={() => run(`Mail from ${sender} won't be grouped`, () => put("/grouping/preferences", { sender_or_domain: sender, mode: "never" }))}>Never group {sender}</button>}
            </div>
            {selecting && (
              <Banner tone="ok" action={selected.size ? `Split off ${selected.size}` : undefined}
                onAction={() => run("Split into a new group", () => post(`/groups/${id}/split`, { message_ids: [...selected] })).then(() => { setSelecting(false); setSelected(new Set()); })}>
                Pick the mails to move into a new group.
              </Banner>
            )}
            <div className="list">
              {d.items?.map((m) => (
                <MailRow key={m.id} m={m}
                  onOpen={() => selecting ? setSelected((s) => { const n = new Set(s); if (n.has(m.id)) n.delete(m.id); else n.add(m.id); return n; }) : navigate(`/mail/${m.id}`)}
                  extra={selecting
                    ? <span className="ok-text">{selected.has(m.id) ? "☑" : "☐"}</span>
                    : <button className="chip" onClick={(e) => { e.stopPropagation(); run("Taken out of the group", () => post(`/groups/${id}/remove`, { message_id: m.id })); }}>Take out</button>} />
              ))}
            </div>
          </>
        )}
      </section>
      {renaming !== null && (
        <Modal title="Rename group" onClose={() => setRenaming(null)} foot={<><button className="btn btn-ghost btn-sm" onClick={() => setRenaming(null)}>Cancel</button>
          <button className="btn btn-primary btn-sm" disabled={!renaming.trim()} onClick={() => { const t = renaming.trim(); setRenaming(null); run(null, () => patch(`/groups/${id}`, { title: t })); }}>Save</button></>}>
          <input className="input" style={{ width: "100%" }} value={renaming} onChange={(e) => setRenaming(e.target.value)} autoFocus aria-label="Group name" />
        </Modal>
      )}
      {filing && <FolderPicker title={filing === "file" ? "File the whole group in…" : "File mail like this in…"}
        note={filing === "rule" ? "Makes a rule: mail like this group's is classified as usual and filed there." : undefined}
        onClose={() => setFiling(null)} onPick={(f) => {
          const mode = filing; setFiling(null);
          if (!f) return;
          if (mode === "file") run(`Filed in ${f.name}`, () => post(`/groups/${id}/file`, { folder_id: f.id })); else ruleDraft("file", f.id);
        }} />}
      {merging && <MergePicker id={id} onClose={() => setMerging(false)} onMerged={() => { setMerging(false); navigate("/groups"); }} />}
    </>
  );
}

function MergePicker({ id, onClose, onMerged }: { id: string; onClose: () => void; onMerged: () => void }) {
  const groups = useLoad(() => get<Group[]>("/groups"));
  const others = (groups.data ?? []).filter((x) => x.id !== id);
  return (
    <Modal title="Merge into…" onClose={onClose}>
      {groups.data && others.length === 0 && <p className="dim">No other groups yet.</p>}
      {others.map((o) => (
        <div key={o.id} className="pick" onClick={async () => {
          try { await post(`/groups/${id}/merge`, { target_id: o.id }); toast(`Merged into ${o.title}`); onMerged(); } catch (e) { toast(errorText(e)); }
        }}>{o.title} <span className="dim">({o.count})</span></div>
      ))}
    </Modal>
  );
}

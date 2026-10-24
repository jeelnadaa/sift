import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { get, patch, post, put, type Draft, type Group, type GroupingStatus } from "../api";
import { Top } from "../App";
import { Banner, errorText, FolderPicker, GroupRow, inputDialog, MailRow, Modal, TextField, toast, Toggle, useLoad } from "../components";

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
        {on && <button className="btn btn-ghost btn-sm" onClick={async () => { await post("/groups/collapse-all", { collapsed: true }).catch(() => {}); groups.reload(); }} data-tip="Fold every group into a single row">Collapse all</button>}
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
      <Top title={d?.title ?? "Group"} back="/groups">
        {d && <button className="btn btn-ghost btn-sm" onClick={() => setRenaming(d.title)} data-tip="Give it a new name">Rename</button>}
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
              <button className="chip" onClick={() => setFiling("file")} data-tip="File every conversation in this group into a folder">File all in folder</button>
              <button className="chip" onClick={() => setFiling("rule")} data-tip="Make a rule that files future mail like this group's into a folder">File mail like this…</button>
              <button className="chip" onClick={() => ruleDraft("silent")} data-tip="Draft a rule that silences mail like this group's (you check it first)">Silence mail like this</button>
              <button className={`chip ${selecting ? "on" : ""}`} onClick={() => { setSelecting(!selecting); setSelected(new Set()); }} data-tip="Pick mails to move into a new group">Split</button>
              <button className="chip" onClick={() => setMerging(true)} data-tip="Move everything here into another one, then remove this">Merge into…</button>
              <button className="chip" onClick={async () => {
                const name = await inputDialog({ title: "Tag this group", label: "Tag every mail in it as", placeholder: "e.g. Money", confirm: "Tag" });
                if (name) run(`Tagged ${d.count} mails`, () => post(`/groups/${id}/tag`, { name }));
              }} data-tip="Tag every mail in this group">Tag</button>
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
                    : <button className="chip" onClick={(e) => { e.stopPropagation(); run("Taken out of the group", () => post(`/groups/${id}/remove`, { message_id: m.id })); }} data-tip="Remove this mail from the group; it won't be added back">Take out</button>} />
              ))}
            </div>
          </>
        )}
      </section>
      {renaming !== null && (
        <Modal title="Rename group" onClose={() => setRenaming(null)} foot={<><button className="btn btn-ghost btn-sm" onClick={() => setRenaming(null)} data-tip="Close without saving">Cancel</button>
          <button className="btn btn-primary btn-sm" disabled={!renaming.trim()} onClick={() => { const t = renaming.trim(); setRenaming(null); run(null, () => patch(`/groups/${id}`, { title: t })); }} data-tip="Save changes">Save</button></>}>
          <TextField value={renaming} onChange={setRenaming} autoFocus ariaLabel="Group name" maxLength={200}
            onEnter={() => { const t = renaming.trim(); if (t) { setRenaming(null); run(null, () => patch(`/groups/${id}`, { title: t })); } }} />
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

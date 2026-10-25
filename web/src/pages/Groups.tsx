import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { del, get, patch, post, put, type AiStatus, type Draft, type Group, type GroupingStatus } from "../api";
import { Top } from "../App";
import { Banner, confirmDialog, errorText, FolderPicker, GroupRow, inputDialog, MailRow, Modal, TextField, toast, Toggle, useLoad } from "../components";

export function Groups() {
  const navigate = useNavigate();
  const status = useLoad(() => get<GroupingStatus>("/grouping"));
  const on = status.data?.grouping_enabled === "yes";
  const groups = useLoad(() => get<Group[]>("/groups"), [on], ["mail", "new_mail", "assistant"]);
  const [making, setMaking] = useState(false);
  const mine = (groups.data ?? []).filter((g) => g.custom);
  const auto = (groups.data ?? []).filter((g) => !g.custom);

  async function set(answer: "yes" | "no") {
    try { await post("/grouping", { answer }); status.reload(); toast(answer === "yes" ? "Grouping on. The last 30 days are being grouped." : "Grouping off"); } catch (e) { toast(errorText(e)); }
  }
  return (
    <>
      <Top title="Groups">
        <button className="btn btn-primary btn-sm" onClick={() => setMaking(true)} data-tip="A group of your own: say which mail belongs in it">+ New group</button>
        {on && <button className="btn btn-ghost btn-sm" onClick={async () => { await post("/groups/collapse-all", { collapsed: true }).catch(() => {}); groups.reload(); }} data-tip="Fold every group into a single row">Collapse all</button>}
      </Top>
      <section className="page">
        <h3 className="sec-h">Your groups</h3>
        <div className="list">
          {groups.data && mine.length === 0 && <div className="empty">No groups of your own yet. <b>+ New group</b>: give it a search (free) or describe the mail in words (the AI checks each new mail), and new mail joins it on its own, next to its folders and timeline.</div>}
          {mine.map((g) => <GroupRow key={g.id} g={g} onOpen={() => navigate(`/groups/${g.id}`)} />)}
        </div>
        <h3 className="sec-h">Automatic groups</h3>
        {status.data && (on
          ? <Banner tone="warn" action="Turn off" onAction={() => set("no")}>Automatic grouping is <b>on</b>. It only changes how mail is displayed. Notifications are unaffected.</Banner>
          : <Banner tone="ok" action="Turn on" onAction={() => set("yes")}>Automatic grouping is <b>off</b>. Turn it on to stack similar mail (bank alerts, newsletters, one company's drive) into one row. Display only.</Banner>)}
        {on && (
          <div className="list">
            {auto.length === 0 && <div className="empty">No automatic groups yet. A group shows once three similar mails arrive.</div>}
            {auto.map((g) => <GroupRow key={g.id} g={g} onOpen={() => navigate(`/groups/${g.id}`)} />)}
          </div>
        )}
      </section>
      {making && <GroupForm onClose={() => setMaking(false)} onSaved={(g) => { setMaking(false); navigate(`/groups/${g.id}`); }} />}
    </>
  );
}

/** New group, or a custom group's criteria: a search (exact, free) and/or a description (the AI
 * checks it while reading each new mail, no extra call). Mail can sit in several groups and folders. */
export function GroupForm({ g, onClose, onSaved }: { g?: Group; onClose: () => void; onSaved: (g: Group) => void }) {
  const ai = useLoad(() => get<AiStatus>("/ai"), []);
  const [title, setTitle] = useState(g?.title ?? "");
  const [query, setQuery] = useState(g?.query ?? "");
  const [instruction, setInstruction] = useState(g?.instruction ?? "");
  const [fill, setFill] = useState(!g);
  const [busy, setBusy] = useState(false);
  const aiOn = !!ai.data?.ai_enabled;
  async function save() {
    setBusy(true);
    try {
      const body = { title: title.trim(), query: query.trim(), instruction: instruction.trim() };
      const out = g ? await patch<Group>(`/groups/${g.id}`, body)
        : await post<Group & { fill_task?: { status: string; changed?: number } | null }>("/groups", { ...body, query: body.query || null, instruction: body.instruction || null, fill: fill && !!(body.query || body.instruction) });
      const ft = (out as { fill_task?: { status: string; changed?: number } | null }).fill_task;
      toast(ft ? (ft.status === "done" ? `Made it, with ${ft.changed} mail already here` : "Made it. The AI is adding matching mail that's already here") : g ? "Saved" : "Group made");
      onSaved(out);
    } catch (e) { toast(errorText(e)); } finally { setBusy(false); }
  }
  return (
    <Modal title={g ? "Which mail joins this group" : "New group"} onClose={onClose} foot={<>
      <button className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
      <button className="btn btn-primary btn-sm" disabled={busy || !title.trim()} onClick={save}>{g ? "Save" : "Make group"}</button></>}>
      <div className="stack" style={{ gap: 12 }}>
        {!g && <div className="field"><label>Name</label><TextField value={title} onChange={setTitle} maxLength={200} autoFocus placeholder="e.g. Internships" ariaLabel="Group name" /></div>}
        <div className="field"><label>New mail matching this search <span className="dim">· free, exact</span></label>
          <TextField value={query} onChange={setQuery} maxLength={500} placeholder="e.g. from:nvidia.com  or  folder:Placements subject:intern" ariaLabel="Search" code /></div>
        <div className="field"><label>And/or mail described as <span className="dim">· the AI checks each new mail it reads, no extra call</span></label>
          <TextField value={instruction} onChange={(v) => { if (aiOn || !v) setInstruction(v); }} maxLength={200}
            placeholder={aiOn ? "e.g. internship offers and stipend details" : "Add an AI key in Settings to describe mail in words"} ariaLabel="Description" /></div>
        <p className="dim" style={{ fontSize: 13, margin: 0 }}>With both, mail must match the search and fit the description. Leave both empty to add mail by hand only. A mail can be in this group and in its folders, other groups and its company timeline at the same time.</p>
        {!g && (query.trim() || instruction.trim()) && (
          <span className="inline"><Toggle on={fill} onChange={setFill} label="Also add matching mail already here" /> Also add matching mail already here
            <span className="dim" style={{ fontSize: 12.5 }}>{instruction.trim() ? "(last 30 days; the AI checks 25 mails per small call)" : "(free)"}</span></span>
        )}
      </div>
    </Modal>
  );
}

export function GroupDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const g = useLoad(() => get<Group>(`/groups/${id}`), [id], ["mail", "new_mail"]);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [filing, setFiling] = useState<"file" | "rule" | null>(null);
  const [merging, setMerging] = useState(false);
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [editing, setEditing] = useState(false);

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
        {d?.custom && <button className="btn btn-ghost btn-sm" onClick={() => setEditing(true)} data-tip="Change which new mail joins it">Criteria…</button>}
        {d?.custom && (d.query || d.instruction) && <button className="btn btn-ghost btn-sm" data-tip="Add matching mail that's already in Sift (last 30 days)" onClick={async () => {
          try { const r = await post<{ status: string; changed?: number }>(`/groups/${id}/fill`, {}); toast(r.status === "done" ? `Added ${r.changed} mail` : "The AI is adding matching mail. You'll get a notification"); g.reload(); } catch (e) { toast(errorText(e)); }
        }}>Fill now</button>}
        {d && <button className="btn btn-danger btn-sm" data-tip="Remove the group; its mail stays where it is" onClick={async () => {
          if (!(await confirmDialog({ title: `Delete ${d.title}?`, body: "The group goes away; every mail in it stays in your feed, folders and timelines.", confirm: "Delete", danger: true }))) return;
          try { await del(`/groups/${id}`); toast("Group deleted"); navigate("/groups"); } catch (e) { toast(errorText(e)); }
        }}>Delete</button>}
      </Top>
      <section className="page">
        {g.error && <Banner tone="err">{g.error}</Banner>}
        {d && (
          <>
            <p className="lede">{d.count} mails · {d.unread} unread{d.urgent ? ` · ${d.urgent} urgent` : ""}. A group only changes how mail is shown; nothing changes in Gmail.</p>
            {d.custom && (
              <div className="card crit" style={{ marginBottom: 14 }}>
                <b>New mail joins when it</b>
                {d.query && <div>matches <code className="mono">{d.query}</code></div>}
                {d.instruction && <div>{d.query ? "and " : ""}fits “{d.instruction}” <span className="dim">(the AI checks)</span></div>}
                {!d.query && !d.instruction && <div className="dim">Nothing automatic: you add mail by hand (a mail's “Add to group…”).</div>}
              </div>
            )}
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
      {editing && d && <GroupForm g={d} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); g.reload(); }} />}
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

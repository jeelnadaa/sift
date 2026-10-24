import { useEffect, useState, type DragEvent } from "react";
import { FolderAi } from "./FolderAi";
import { useNavigate, useParams } from "react-router-dom";
import { del, get, patch, post, type Folder, type FolderTree, type FolderView } from "../api";
import { Top, fileDropped, foldersChanged } from "../App";
import { Banner, errorText, FolderPicker, MailRow, Modal, Pager, TextField, toast, Toggle, useLoad, usePages } from "../components";
import { FOLDER_COLORS, findFolder, flatten, subtreeIds } from "../util";

const MAIL = "application/x-sift-mail";
const FOLDER = "application/x-sift-folder";
const NOTIFY: [Folder["notify_mode"], string, string][] = [
  ["default", "As usual", "Mail notifies by its own priority."],
  ["always", "Always notify", "Digest mail filed here notifies with sound too."],
  ["mute", "Mute", "Mail filed here doesn't notify. Urgent mail still does."],
];

export function Folders() {
  const { id } = useParams();
  const navigate = useNavigate();
  const tree = useLoad(() => get<FolderTree>("/folders"));
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [creating, setCreating] = useState<{ parent: Folder | null } | null>(null);
  const [overTop, setOverTop] = useState(false);
  const folders = tree.data?.folders ?? [];
  const current = findFolder(folders, id);

  // keep the selected folder's ancestors open
  useEffect(() => {
    if (!current) return;
    const ids = new Set(open);
    let p = current.parent_id;
    while (p) { ids.add(p); p = findFolder(folders, p)?.parent_id ?? null; }
    if (ids.size !== open.size) setOpen(ids);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.id, tree.data]);

  const refresh = () => { tree.reload(); foldersChanged(); };
  async function moveFolder(folderId: string, parentId: string | null) {
    if (folderId === parentId) return;
    try { await post(`/folders/${folderId}/move`, { parent_id: parentId }); refresh(); } catch (e) { toast(errorText(e)); }
  }

  return (
    <>
      <Top title="Folders"><button className="btn btn-primary btn-sm" onClick={() => setCreating({ parent: null })} data-tip="Make a folder. Folders live in Sift; Gmail is never changed">+ New folder</button></Top>
      <section className="page">
        {tree.error && <Banner tone="err">{tree.error}</Banner>}
        <div className="split">
          <div className="card tree" style={{ padding: 12 }}>
            {tree.data && folders.length === 0 && <p className="dim" style={{ padding: 8 }}>No folders yet. Make one, then drag mail onto it or let a rule file it.</p>}
            {flatten(folders, open).map(([f, depth]) => (
              <TreeItem key={f.id} f={f} depth={depth} on={f.id === current?.id} open={open.has(f.id)}
                onToggle={() => setOpen((s) => { const n = new Set(s); if (n.has(f.id)) n.delete(f.id); else n.add(f.id); return n; })}
                onOpen={() => navigate(`/folders/${f.id}`)}
                onDropMail={(mid) => fileDropped(mid, f).then(refresh)}
                onDropFolder={(fid) => moveFolder(fid, f.id)} />
            ))}
            <div className={`it ${overTop ? "drop" : ""}`} style={{ marginTop: 6, fontSize: 12.5 }}
              onDragOver={(e) => { if (e.dataTransfer.types.includes(FOLDER)) { e.preventDefault(); setOverTop(true); } }}
              onDragLeave={() => setOverTop(false)}
              onDrop={(e) => { e.preventDefault(); setOverTop(false); moveFolder(e.dataTransfer.getData(FOLDER), null); }}>
              <span className="tw">⌂</span><span className="dim">Drop a folder here to move it to the top level</span>
            </div>
            <p className="dim" style={{ fontSize: 12.5, padding: "10px 8px 0" }}>Drag mail onto a folder to file it, or a folder onto another to nest it. Up to {tree.data?.max_depth ?? 10} levels.</p>
          </div>
          <div>
            {current ? <FolderPane key={current.id} f={current} all={folders} onChanged={refresh} onAddChild={() => setCreating({ parent: current })} />
              : <div className="card dim">Pick a folder to see what's filed in it. Filing never moves or changes mail in Gmail.</div>}
          </div>
        </div>
      </section>
      {creating && <FolderForm title={creating.parent ? `New folder in ${creating.parent.name}` : "New folder"} onClose={() => setCreating(null)}
        onSave={async (name, color) => {
          try {
            const f = await post<Folder>("/folders", { name, color, parent_id: creating.parent?.id ?? null });
            setCreating(null); refresh(); navigate(`/folders/${f.id}`);
          } catch (e) { toast(errorText(e)); }
        }} />}
    </>
  );
}

function TreeItem({ f, depth, on, open, onToggle, onOpen, onDropMail, onDropFolder }: {
  f: Folder; depth: number; on: boolean; open: boolean; onToggle: () => void; onOpen: () => void;
  onDropMail: (id: string) => void; onDropFolder: (id: string) => void;
}) {
  const [over, setOver] = useState(false);
  const accept = (e: DragEvent) => e.dataTransfer.types.includes(MAIL) || (e.dataTransfer.types.includes(FOLDER) && !f.smart);
  return (
    <div className={`it ${on ? "on" : ""} ${over ? "drop" : ""}`} style={{ paddingLeft: 8 + depth * 18 }} onClick={onOpen}
      draggable onDragStart={(e) => { e.dataTransfer.setData(FOLDER, f.id); e.dataTransfer.effectAllowed = "move"; }}
      onDragOver={(e) => { if (accept(e)) { e.preventDefault(); setOver(true); } }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault(); setOver(false);
        const mail = e.dataTransfer.getData(MAIL);
        if (mail) onDropMail(mail); else onDropFolder(e.dataTransfer.getData(FOLDER));
      }}>
      <span className="tw" onClick={(e) => { e.stopPropagation(); if (f.children.length) onToggle(); }}>{f.children.length ? (open ? "▾" : "▸") : ""}</span>
      <span className="sw" style={{ background: f.color ?? "var(--text-3)" }} />
      <span className="nm">{f.name}</span>
      {f.pinned && <span className="dim" data-tip="Pinned to the top">📌</span>}
      {f.notify_mode === "mute" && <span className="dim" data-tip="Muted: mail filed here doesn't notify (urgent still does)">🔕</span>}
      {f.notify_mode === "always" && <span data-tip="Always notify, even digest mail">🔔</span>}
      <span className={`ct ${(open ? f.unread : f.unread_total) ? "u" : ""}`}>{(open ? f.unread : f.unread_total) || f.threads || ""}</span>
    </div>
  );
}

function FolderPane({ f, all, onChanged, onAddChild }: { f: Folder; all: Folder[]; onChanged: () => void; onAddChild: () => void }) {
  const navigate = useNavigate();
  const [includeSub, setIncludeSub] = useState(false);
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [dialog, setDialog] = useState<"edit" | "move" | "merge" | "delete" | null>(null);
  useEffect(() => { const t = setTimeout(() => setQuery(q.trim()), 300); return () => clearTimeout(t); }, [q]);
  const view = usePages((before) => get<FolderView>(`/folders/${f.id}/threads`, { include_subfolders: includeSub, q: query || undefined, before, limit: 30 }), [f.id, includeSub, query]);

  async function edit(changes: object) {
    try { await patch(`/folders/${f.id}`, changes); onChanged(); } catch (e) { toast(errorText(e)); }
  }
  async function unfile(messageId: string) {
    try { await post(`/folders/${f.id}/threads/remove`, { message_ids: [messageId] }); view.reload(); onChanged(); } catch (e) { toast(errorText(e)); }
  }
  return (
    <>
      <div className="crumbs">
        <a onClick={() => navigate("/folders")} data-tip="All folders">Folders</a>
        {view.data?.path.map((p, i) => <span key={p.id}>/ {i === view.data!.path.length - 1 ? <b style={{ color: "var(--text)" }}>{p.name}</b> : <a onClick={() => navigate(`/folders/${p.id}`)}>{p.name}</a>}</span>)}
      </div>
      <div className="tabs">
        {NOTIFY.map(([mode, label]) => <button key={mode} className={`chip ${f.notify_mode === mode ? "on" : ""}`} onClick={() => edit({ notify_mode: mode })}>{label}</button>)}
        <span className="spacer" />
        <button className="chip" onClick={() => edit({ pinned: !f.pinned })}>{f.pinned ? "Unpin" : "Pin to top"}</button>
        <button className="chip" onClick={() => setDialog("edit")} data-tip="Change this folder's name or color">Rename or recolor</button>
        <button className="chip" onClick={onAddChild} data-tip="Make a folder inside this one">+ Subfolder</button>
        <button className="chip" onClick={() => setDialog("move")} data-tip="Move this folder (with everything in it) under another folder">Move</button>
        <button className="chip" onClick={() => setDialog("merge")} data-tip="Move this folder's mail and subfolders into another folder">Merge</button>
        <button className="chip" style={{ color: "var(--urgent)" }} onClick={() => setDialog("delete")} data-tip="Delete for good (mail itself is never deleted)">Delete</button>
      </div>
      <p className="dim" style={{ fontSize: 13, margin: "-8px 0 14px" }}>{NOTIFY.find(([m]) => m === f.notify_mode)?.[2]}</p>
      <FolderAi f={f} onChanged={() => { onChanged(); view.reload(); }} />
      <div className="inline" style={{ marginBottom: 14 }}>
        <TextField placeholder="Search this folder: sender or subject words" value={q} onChange={setQ} ariaLabel="Search this folder" maxLength={200} />
        <span className="inline dim" style={{ fontSize: 13 }}><Toggle on={includeSub} onChange={setIncludeSub} label="Include subfolders" /> Include subfolders</span>
      </div>
      {view.error && <Banner tone="err">{view.error}</Banner>}
      {view.data && <Pager page={view.page} pages={view.pages} total={view.total} noun="conversations" onPrev={view.onPrev} onNext={view.onNext} />}
      <div className="list">
        {view.data?.items.length === 0 && <div className="empty">{query ? "No mail here matches." : "Nothing filed here yet. Drag mail onto this folder, or open a mail and choose File in folder."}</div>}
        {view.data?.items.map((m, n) => (
          <MailRow key={m.id} m={m} n={n + 1} onOpen={() => navigate(`/mail/${m.id}`)}
            extra={!includeSub && <button className="chip" onClick={(e) => { e.stopPropagation(); unfile(m.id); }} data-tip="Take this conversation out of the folder (mail stays)">Unfile</button>} />
        ))}
      </div>
      {view.data && <Pager bottom page={view.page} pages={view.pages} total={view.total} noun="conversations" onPrev={view.onPrev} onNext={view.onNext} />}
      <p className="dim" style={{ marginTop: 12, fontSize: 13 }}>Filing never changes mail in Gmail. <a className="link dim" onClick={() => navigate("/settings")} data-tip="Backup lives in Settings">Import or export folders and rules as JSON</a></p>

      {dialog === "edit" && <FolderForm title="Edit folder" initialName={f.name} initialColor={f.color} onClose={() => setDialog(null)}
        onSave={(name, color) => { setDialog(null); edit({ name, color, clear_color: color === null }); }} />}
      {dialog === "move" && <FolderPicker title={`Move ${f.name} to…`} exclude={subtreeIds(f)} allowTop onClose={() => setDialog(null)}
        onPick={async (t) => { setDialog(null); try { await post(`/folders/${f.id}/move`, { parent_id: t?.id ?? null }); onChanged(); } catch (e) { toast(errorText(e)); } }} />}
      {dialog === "merge" && <FolderPicker title={`Merge ${f.name} into…`} exclude={subtreeIds(f)}
        note={`Its mail and subfolders move into the folder you pick, and rules that filed here file there. Then ${f.name} is removed.`}
        onClose={() => setDialog(null)} onPick={async (t) => {
          setDialog(null);
          if (!t) return;
          try { await post(`/folders/${f.id}/merge`, { target_id: t.id }); onChanged(); navigate(`/folders/${t.id}`); } catch (e) { toast(errorText(e)); }
        }} />}
      {dialog === "delete" && (
        <Modal title={`Delete ${f.name}?`} onClose={() => setDialog(null)} foot={<>
          <button className="btn btn-ghost btn-sm" onClick={() => setDialog(null)} data-tip="Close without saving">Cancel</button>
          {f.children.length > 0 && <button className="btn btn-ghost btn-sm" onClick={() => remove("move_up")} data-tip="Delete this folder; its subfolders move up one level. Mail stays">Delete, move subfolders up</button>}
          <button className="btn btn-danger btn-sm" onClick={() => remove("delete")}>{f.children.length ? "Delete with subfolders" : "Delete"}</button>
        </>}>
          <p className="muted">Only the folder and its filing go. Mail stays in Gmail and in Sift.{f.children.length > 0 && ` It has ${f.children.length} subfolder(s).`}</p>
        </Modal>
      )}
    </>
  );

  async function remove(subfolders: "delete" | "move_up") {
    setDialog(null);
    try {
      const r = await del<{ rules_updated: number }>(`/folders/${f.id}`, { subfolders });
      toast(r.rules_updated ? `Deleted. ${r.rules_updated} rule(s) no longer file anywhere.` : "Deleted");
      onChanged();
      navigate(f.parent_id && findFolder(all, f.parent_id) ? `/folders/${f.parent_id}` : "/folders");
    } catch (e) { toast(errorText(e)); }
  }
}

function FolderForm({ title, initialName = "", initialColor = null, onSave, onClose }: {
  title: string; initialName?: string; initialColor?: string | null; onSave: (name: string, color: string | null) => void; onClose: () => void;
}) {
  const [name, setName] = useState(initialName);
  const [color, setColor] = useState<string | null>(initialColor);
  return (
    <Modal title={title} onClose={onClose} foot={<><button className="btn btn-ghost btn-sm" onClick={onClose} data-tip="Close without saving">Cancel</button>
      <button className="btn btn-primary btn-sm" disabled={!name.trim()} onClick={() => onSave(name.trim(), color)} data-tip="Save changes">Save</button></>}>
      <div className="stack">
        <div className="field"><label htmlFor="fn">Name</label><TextField id="fn" value={name} onChange={setName} placeholder="e.g. Placements" autoFocus maxLength={120}
          onEnter={() => { if (name.trim()) onSave(name.trim(), color); }} /></div>
        <div className="field"><label>Color</label>
          <div className="inline">
            {FOLDER_COLORS.map((c) => (
              <button key={c} aria-label={`Color ${c}`} onClick={() => setColor(color === c ? null : c)}
                style={{ width: 28, height: 28, borderRadius: "var(--r-sm)", background: c, outline: color === c ? "2px solid var(--text)" : "none", outlineOffset: 2 }} />
            ))}
          </div>
        </div>
      </div>
    </Modal>
  );
}

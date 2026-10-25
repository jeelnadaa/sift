import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { get, post, type Draft, type Folder, type FolderTree, type Group, type Mail, type Preview } from "../api";
import { Top, foldersChanged } from "../App";
import { Thread } from "./Thread";
import { LabelDialog, SnoozeDialog, mailAction, type MailAction } from "../mailActions";
import { Avatar, Banner, FolderPicker, Modal, Tag, TextField, errorText, setReadState, toast, useLoad } from "../components";
import { findFolder, fullTime, safeUrl } from "../util";

const DECIDED: Record<string, string> = {
  rule: "one of your rules", llm: "the AI", heuristic: "Sift's built-in checks", fingerprint: "a template you silenced before",
  default: "default (no rule matched, AI off)", existing: "an earlier check", gone: "Gmail (it was deleted)",
};

/** Mail detail: Sift's view of the mail (priority, extracted facts, filing) and the whole
 * conversation below it, fetched live from Gmail and never stored. */
export function MailDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const mail = useLoad(() => get<Mail>(`/messages/${id}`), [id], ["mail", "folders"]);
  const inFoldersLive = ["folders"] as const;
  // opening a mail reads it: the whole conversation is marked read (in Gmail when the account
  // allows changes), once per visit, and every other open device updates live
  const autoRead = useRef<string | null>(null);
  useEffect(() => {
    const m = mail.data;
    if (!m || autoRead.current === id) return;
    autoRead.current = id;
    if (m.unread) {
      mail.setData({ ...m, unread: false });
      setReadState([id], false).catch(() => mail.reload());
    }
  }, [mail.data, id]); // eslint-disable-line react-hooks/exhaustive-deps
  async function toggleRead() {
    const m = mail.data;
    if (!m) return;
    mail.setData({ ...m, unread: !m.unread });
    try {
      const r = await setReadState([id], !m.unread);
      toast((m.unread ? "Marked read" : "Marked unread") + (r.sift_only.length ? " in Sift (Gmail unchanged: this account is read-only)" : ""));
    } catch (e) { mail.reload(); toast(errorText(e)); }
  }
  const tree = useLoad(() => get<FolderTree>("/folders"), [id]);
  const inFolders = useLoad(() => get<Folder[]>(`/folders/for-message/${id}`), [id], [...inFoldersLive]);
  const [picking, setPicking] = useState(false);
  const [likeThis, setLikeThis] = useState<{ draft: Draft; preview: Preview } | null>(null);
  const [grouping, setGrouping] = useState(false);
  const [snoozing, setSnoozing] = useState(false);
  const [labelling, setLabelling] = useState(false);
  async function gmail(action: MailAction, leave = false, label?: string) {
    if (await mailAction({ message_ids: [id] }, action, label)) {
      if (leave) navigate(-1); else mail.reload();
    }
  }

  const m = mail.data;
  const reply = (mode: string) => navigate(`/compose?mode=${mode}&message=${id}`);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (/INPUT|TEXTAREA|SELECT/.test((e.target as HTMLElement).tagName) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === "r") { e.preventDefault(); reply("reply"); }
      if (e.key === "a") { e.preventDefault(); reply("reply_all"); }
      if (e.key === "f") { e.preventDefault(); reply("forward"); }
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  });
  async function file(f: Folder) {
    try {
      await post(`/folders/${f.id}/threads`, { message_ids: [id] });
      toast(`Filed in ${f.name}`);
      inFolders.reload(); tree.reload(); foldersChanged();
    } catch (e) { toast(errorText(e)); }
  }
  async function unfile(f: Folder) {
    try { await post(`/folders/${f.id}/threads/remove`, { message_ids: [id] }); inFolders.reload(); foldersChanged(); } catch (e) { toast(errorText(e)); }
  }
  async function fileLikeThis(f: Folder) {
    try {
      const r = await post<{ draft: Draft }>(`/folders/${f.id}/rule-from-message`, { message_id: id });
      navigate("/rules/new", { state: { draft: r.draft, origin: "one_tap" } });
    } catch (e) { toast(errorText(e)); }
  }
  async function unsilence() {
    try {
      const r = await post<{ rule_id: string | null }>(`/messages/${id}/unsilence`);
      mail.reload();
      toast(r.rule_id ? "Back in your feed. A rule silenced it: edit the rule so it doesn't happen again." : "Back in your feed");
    } catch (e) { toast(errorText(e)); }
  }

  const last = findFolder(tree.data?.folders ?? [], tree.data?.last_used_id);
  return (
    <>
      <Top title={m?.subject ?? "Mail"} back />
      <section className="page">
        {mail.error && <Banner tone="err">{mail.error}</Banner>}
        {m && (
          <div className="stack" style={{ maxWidth: 860 }}>
            <div className="inline">
              {m.priority && <Tag tone={m.priority}>{m.priority}</Tag>}
              {m.category && m.category !== "other" && <Tag>{m.category}</Tag>}
              {m.company && <Tag>{m.company}</Tag>}
              {m.status !== "processed" && <Tag tone="warn">{m.status}</Tag>}
            </div>
            <div className="inline">
              <Avatar text={m.sender_name || m.sender} />
              <div>
                <b>{m.sender_name || m.sender}</b>
                <div className="dim" style={{ fontSize: 13 }}>{m.sender} · {fullTime(m.received_at)}{m.account ? ` · to ${m.account}` : ""}</div>
              </div>
            </div>

            {(m.summary || m.deadline || m.links.length > 0) && (
              <div className="card">
                <div className="field"><label>Extracted</label></div>
                {m.summary && <p style={{ marginTop: 6 }}>{m.summary}</p>}
                {m.deadline && <p style={{ color: "var(--warn)", fontWeight: 700, marginTop: 6 }}>Deadline {fullTime(m.deadline)}</p>}
                <div className="inline" style={{ marginTop: 10 }}>
                  {m.links.map((l) => { const u = safeUrl(l.url); return u && <a key={u} className="btn btn-primary btn-sm" href={u} target="_blank" rel="noopener noreferrer">{l.label} ↗</a>; })}
                </div>
              </div>
            )}
            {m.opportunity_id && <Banner tone="ok" action="Open timeline" onAction={() => navigate(`/opportunities/${m.opportunity_id}`)}>On the <b>{m.company ?? "company"}</b> timeline</Banner>}

            <div className="inline mail-toolbar" role="toolbar" aria-label="Change this conversation in Gmail">
              <button className="btn btn-primary btn-sm" onClick={() => reply("reply")} data-tip="Reply to the sender  (R)">↩ Reply</button>
              <button className="btn btn-ghost btn-sm" onClick={() => reply("reply_all")} data-tip="Reply to everyone  (A)">Reply all</button>
              <button className="btn btn-ghost btn-sm" onClick={() => reply("forward")} data-tip="Forward with attachments  (F)">Forward</button>
              {m.in_inbox === false
                ? <button className="btn btn-ghost btn-sm" onClick={() => gmail("unarchive")} data-tip="Put it back in Gmail's inbox">Move to inbox</button>
                : <button className="btn btn-ghost btn-sm" onClick={() => gmail("archive", true)} data-tip="Archive in Gmail: out of the inbox, still searchable  (Z to undo)">Archive</button>}
              <button className="btn btn-ghost btn-sm" onClick={toggleRead} data-tip={m.unread ? "Mark the conversation read  (also in Gmail when the account allows changes)" : "Mark it unread, to come back to it"}>{m.unread ? "Mark read" : "Mark unread"}</button>
              <button className="btn btn-ghost btn-sm" onClick={() => gmail(m.starred ? "unstar" : "star")} data-tip={m.starred ? "Remove the star in Gmail" : "Star it in Gmail"}>{m.starred ? "★ Starred" : "☆ Star"}</button>
              <button className="btn btn-ghost btn-sm" onClick={() => setLabelling(true)} data-tip="Add a Gmail label">Label…</button>
              <button className="btn btn-ghost btn-sm" onClick={() => setSnoozing(true)} data-tip="Hide it until later; it comes back and notifies you">Snooze…</button>
              <button className="btn btn-ghost btn-sm" onClick={() => gmail("spam", true)} data-tip="Report as spam in Gmail (Z to undo)">Spam</button>
              <button className="btn btn-danger btn-sm" onClick={() => gmail("trash", true)} data-tip="Move to Gmail's trash. Gmail keeps it 30 days; Sift never deletes (Z to undo)">Trash</button>
            </div>
            <div className="inline">
              <button className="btn btn-ghost btn-sm" onClick={() => setPicking(true)} data-tip="File this conversation into one of your folders">File in folder</button>
              <button className="btn btn-ghost btn-sm" onClick={() => setGrouping(true)} data-tip="Put this mail in a group of yours (it can be in several)">Add to group…</button>
              {last && !(inFolders.data ?? []).some((f) => f.id === last.id) && <button className="btn btn-ghost btn-sm" onClick={() => file(last)}>Move to {last.name}</button>}
              {m.status === "silenced" || m.status === "ignored"
                ? <button className="btn btn-ghost btn-sm" onClick={unsilence} data-tip="Bring it back to the feed and stop silencing mail like it">Not like this</button>
                : <button className="btn btn-ghost btn-sm" onClick={async () => {
                    try { setLikeThis(await post(`/messages/${id}/like-this`, { action: "silent", save: false })); } catch (e) { toast(errorText(e)); }
                  }} data-tip="Silence future mail from this sender with this kind of subject">Ignore mails like this</button>}
            </div>
            {(m.groups ?? []).length > 0 && (
              <div className="inline">
                <span className="dim">In group</span>
                {m.groups!.map((g) => <button key={g.id} className="chip" onClick={() => navigate(`/groups/${g.id}`)} data-tip="Open the group">{g.title}</button>)}
              </div>
            )}
            {(inFolders.data ?? []).length > 0 && (
              <div className="inline">
                <span className="dim">In</span>
                {inFolders.data!.map((f) => (
                  <button key={f.id} className="chip" onClick={() => unfile(f)} data-tip={`Take this conversation out of ${f.name}`}>
                    <i style={{ width: 8, height: 8, borderRadius: 3, background: f.color ?? "var(--text-3)" }} />{f.name} <span className="x">✕</span>
                  </button>
                ))}
                <a className="link" onClick={() => fileLikeThis(inFolders.data![0])}>File mail like this in {inFolders.data![0].name} automatically</a>
              </div>
            )}

            <div className="field" style={{ marginTop: 10 }}><label>Conversation</label></div>
            <Thread messageId={id} />
            <p className="dim" style={{ fontSize: 13 }}>Decided by {DECIDED[m.decided_by ?? ""] ?? m.decided_by ?? "default"}{m.delivered_at ? ` · delivered ${fullTime(m.delivered_at)}` : ""}. Mail is shown in a locked frame where scripts never run; its images come through your Sift server, so senders never see your address.</p>
          </div>
        )}
      </section>

      {grouping && <GroupPicker messageId={id} exclude={new Set((m?.groups ?? []).map((g) => g.id))} onClose={() => setGrouping(false)}
        onDone={() => { setGrouping(false); mail.reload(); }} />}
      {snoozing && <SnoozeDialog target={{ message_ids: [id] }} onClose={() => setSnoozing(false)} onDone={() => { setSnoozing(false); navigate(-1); }} />}
      {labelling && m && <LabelDialog accountId={m.account_id} onClose={() => setLabelling(false)} onPick={(name) => { setLabelling(false); gmail("label", false, name); }} />}
      {picking && <FolderPicker title="File in folder" exclude={new Set((inFolders.data ?? []).map((f) => f.id))}
        note="The whole conversation is filed, so replies show up there too. Nothing changes in Gmail."
        onClose={() => setPicking(false)} onPick={(f) => { setPicking(false); if (f) file(f); }} />}
      {likeThis && (
        <Modal title="Silence mails like this?" onClose={() => setLikeThis(null)} foot={<>
          <button className="btn btn-ghost btn-sm" onClick={() => { setLikeThis(null); navigate("/rules/new", { state: { draft: likeThis.draft, origin: "one_tap" } }); }} data-tip="Open the draft in the rule editor to change it first">Adjust…</button>
          <button className="btn btn-primary btn-sm" onClick={async () => {
            setLikeThis(null);
            try { await post(`/messages/${id}/like-this`, { action: "silent", save: true }); mail.reload(); toast("Mails like this will be stored silently"); } catch (e) { toast(errorText(e)); }
          }} data-tip="Store mail like this silently from now on">Silence</button></>}>
          <p className="muted">New mail from the same verified sender with the same kind of subject will be stored silently: searchable, never notified.</p>
          <p className="ok-text" style={{ marginTop: 10 }}>{likeThis.preview.matches} of your last {likeThis.preview.checked} mails match.</p>
          {likeThis.preview.samples.slice(0, 3).map((s) => <p key={s.id} className="dim" style={{ fontSize: 13 }}>· {s.subject}</p>)}
        </Modal>
      )}
    </>
  );
}

/** Your groups to put this mail in, or a new one by name. */
function GroupPicker({ messageId, exclude, onClose, onDone }: { messageId: string; exclude: Set<string>; onClose: () => void; onDone: () => void }) {
  const groups = useLoad(() => get<Group[]>("/groups"));
  const [name, setName] = useState("");
  const mine = (groups.data ?? []).filter((g) => g.custom && !exclude.has(g.id));
  async function add(id: string, title: string) {
    try { await post(`/groups/${id}/add`, { message_ids: [messageId] }); toast(`Added to ${title}`); onDone(); } catch (e) { toast(errorText(e)); }
  }
  return (
    <Modal title="Add to group" onClose={onClose}>
      <div className="stack" style={{ gap: 6 }}>
        {groups.data && mine.length === 0 && <p className="dim">No groups of your own yet. Make one below, or on the Groups page with rules for new mail.</p>}
        {mine.map((g) => <button key={g.id} className="chip" style={{ justifyContent: "flex-start" }} onClick={() => add(g.id, g.title)}>{g.title} <span className="dim">· {g.count} mails</span></button>)}
        <div className="inline" style={{ marginTop: 8 }}>
          <div style={{ flex: 1 }}><TextField value={name} onChange={setName} maxLength={200} placeholder="New group name" ariaLabel="New group name"
            onEnter={async () => { if (!name.trim()) return; try { const g = await post<Group>("/groups", { title: name.trim() }); add(g.id, g.title); } catch (e) { toast(errorText(e)); } }} /></div>
          <button className="btn btn-primary btn-sm" style={{ height: 42 }} disabled={!name.trim()} onClick={async () => {
            try { const g = await post<Group>("/groups", { title: name.trim() }); add(g.id, g.title); } catch (e) { toast(errorText(e)); }
          }}>Make and add</button>
        </div>
      </div>
    </Modal>
  );
}

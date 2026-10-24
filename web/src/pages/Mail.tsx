import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { get, post, type Draft, type Folder, type FolderTree, type Mail, type Preview } from "../api";
import { Top, foldersChanged } from "../App";
import { Avatar, Banner, FolderPicker, Modal, Tag, errorText, toast, useLoad } from "../components";
import { findFolder, fullTime, safeUrl } from "../util";

/** Mail detail: plain text body fetched live (never stored). The sandboxed HTML reader is Phase 3. */
export function MailDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const mail = useLoad(() => get<Mail>(`/messages/${id}`), [id]);
  const body = useLoad(() => get<{ text: string; attachments: string[] }>(`/messages/${id}/body`), [id]);
  const tree = useLoad(() => get<FolderTree>("/folders"), [id]);
  const inFolders = useLoad(() => get<Folder[]>(`/folders/for-message/${id}`), [id]);
  const [picking, setPicking] = useState(false);
  const [likeThis, setLikeThis] = useState<{ draft: Draft; preview: Preview } | null>(null);

  const m = mail.data;
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
      <Top title={m?.subject ?? "Mail"}>
        <button className="btn btn-ghost btn-sm" onClick={() => navigate(-1)} data-tip="Go back to the previous page">Back</button>
      </Top>
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

            <div className="inline">
              <button className="btn btn-ghost btn-sm" onClick={() => setPicking(true)} data-tip="File this conversation into one of your folders">File in folder</button>
              {last && !(inFolders.data ?? []).some((f) => f.id === last.id) && <button className="btn btn-ghost btn-sm" onClick={() => file(last)}>Move to {last.name}</button>}
              {m.status === "silenced" || m.status === "ignored"
                ? <button className="btn btn-ghost btn-sm" onClick={unsilence} data-tip="Bring it back to the feed and stop silencing mail like it">Not like this</button>
                : <button className="btn btn-ghost btn-sm" onClick={async () => {
                    try { setLikeThis(await post(`/messages/${id}/like-this`, { action: "silent", save: false })); } catch (e) { toast(errorText(e)); }
                  }} data-tip="Silence future mail from this sender with this kind of subject">Ignore mails like this</button>}
            </div>
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

            <div className="field" style={{ marginTop: 10 }}><label>Message</label></div>
            {body.data ? <div className="mail-body">{body.data.text.trim() || m.snippet}</div>
              : body.error ? <div className="mail-body">{m.snippet}{"\n\n"}<span className="dim">({body.error})</span></div>
              : <p className="dim">Loading…</p>}
            {body.data && body.data.attachments.length > 0 && <div className="inline">{body.data.attachments.map((a) => <Tag key={a}>{`📎 ${a}`}</Tag>)}</div>}
            <p className="dim" style={{ fontSize: 13 }}>Decided by {m.decided_by ?? "default"}{m.delivered_at ? ` · delivered ${fullTime(m.delivered_at)}` : ""}. Shown as plain text; links and images in the mail are not loaded.</p>
          </div>
        )}
      </section>

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

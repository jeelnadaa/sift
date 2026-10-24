import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { get } from "../api";
import { Avatar, Banner, useLoad } from "../components";
import { fullTime, relativeTime } from "../util";

interface Addr { name: string; email: string }
interface ThreadAttachment { filename: string; mime: string; size: number; url: string; view_url: string | null }
interface ThreadMessage {
  gmail_id: string; id: string | null; from: Addr | null; to: Addr[]; cc: Addr[]; subject: string; date: string | null;
  unread: boolean; snippet: string; text: string; html_url: string | null; images_blocked: number; attachments: ThreadAttachment[];
}
interface ThreadData { thread_id: string; account: string; account_id: string; subject: string; images: boolean; messages: ThreadMessage[] }

const who = (a: Addr | null) => (a ? a.name || a.email : "Unknown");
const list = (xs: Addr[]) => xs.map((x) => x.name ? `${x.name} <${x.email}>` : x.email).join(", ");

export function size(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/** The whole conversation, fetched live. The newest message (and the one you opened) start open;
 * older ones show a one-line preview until clicked. Remote images stay blocked until asked for. */
export function Thread({ messageId, accountId, threadId }: { messageId?: string; accountId?: string; threadId?: string }) {
  const [images, setImages] = useState(false);
  const path = messageId ? `/messages/${messageId}/thread` : `/accounts/${accountId}/threads/${threadId}`;
  const t = useLoad(() => get<ThreadData>(path, { images: images || undefined }), [path, images]);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const navigate = useNavigate();
  const d = t.data;
  const write = (mode: string, m: ThreadMessage) => navigate(`/compose?mode=${mode}&account=${d?.account_id}&gmail=${m.gmail_id}`);

  useEffect(() => {
    if (!d) return;
    const last = d.messages[d.messages.length - 1]?.gmail_id;
    const mine = d.messages.find((m) => m.id === messageId)?.gmail_id;
    setOpen((s) => new Set([...s, ...[last, mine].filter((x): x is string => !!x), ...d.messages.filter((m) => m.unread).map((m) => m.gmail_id)]));
  }, [d, messageId]);

  if (t.error) return <Banner tone="err" action="Retry" onAction={t.reload}>{t.error}</Banner>;
  if (!d) return <p className="dim">Loading the conversation…</p>;
  const blocked = d.messages.reduce((n, m) => n + m.images_blocked, 0);

  return (
    <div className="thread">
      {!images && blocked > 0 && (
        <Banner tone="warn" action="Load images" onAction={() => setImages(true)}>
          {blocked} remote image{blocked === 1 ? "" : "s"} blocked. They can tell the sender you opened the mail. Loading goes through your Sift server, so the sender never sees your address.
        </Banner>
      )}
      {d.messages.length > 1 && <p className="dim" style={{ fontSize: 13, marginBottom: 10 }}>{d.messages.length} messages in this conversation</p>}
      {d.messages.map((m) => {
        const isOpen = open.has(m.gmail_id);
        return (
          <article key={m.gmail_id} className={`msg ${isOpen ? "open" : ""} ${m.id === messageId ? "current" : ""}`}>
            <header onClick={() => setOpen((s) => { const n = new Set(s); if (n.has(m.gmail_id)) n.delete(m.gmail_id); else n.add(m.gmail_id); return n; })}
              data-tip={isOpen ? "Collapse this message" : "Show this message"}>
              <Avatar text={who(m.from)} tip={m.from?.email} />
              <div className="main">
                <div className="who">{who(m.from)}{m.unread && <span className="tag normal" data-tip="Unread in Gmail">Unread</span>}</div>
                <div className="subj">{isOpen ? <>to {list(m.to) || "me"}{m.cc.length > 0 && <> · cc {list(m.cc)}</>}</> : m.snippet}</div>
              </div>
              {m.attachments.length > 0 && <span className="dim" data-tip={`${m.attachments.length} attachment${m.attachments.length === 1 ? "" : "s"}`}>📎</span>}
              <span className="time" data-tip={fullTime(m.date)}>{relativeTime(m.date)}</span>
            </header>
            {isOpen && (
              <div className="msg-body">
                {m.html_url ? <MailFrame src={m.html_url} title={`Message from ${who(m.from)}`} /> : <div className="mail-body">{m.text || m.snippet}</div>}
                {d.account_id && (
                  <div className="reply-bar">
                    <button className="btn btn-ghost btn-sm" onClick={() => write("reply", m)} data-tip="Reply to the sender">↩ Reply</button>
                    {m.to.length + m.cc.length > 1 && <button className="btn btn-ghost btn-sm" onClick={() => write("reply_all", m)} data-tip="Reply to everyone on this message">↩ Reply all</button>}
                    <button className="btn btn-ghost btn-sm" onClick={() => write("forward", m)} data-tip="Forward it, with its attachments">↪ Forward</button>
                  </div>
                )}
                {m.attachments.length > 0 && (
                  <div className="atts">
                    {m.attachments.map((a) => (
                      <div key={a.url} className="att">
                        <span className="att-ico" aria-hidden="true">{a.mime.startsWith("image/") ? "🖼" : a.mime === "application/pdf" ? "📄" : "📎"}</span>
                        <div className="main"><div className="nm" data-tip={a.filename}>{a.filename}</div><div className="dim" style={{ fontSize: 12 }}>{size(a.size)}</div></div>
                        {a.view_url && <a className="chip" href={a.view_url} target="_blank" rel="noopener noreferrer" data-tip="Open the image in a new tab">View</a>}
                        <a className="chip" href={a.url} download={a.filename} data-tip="Download (fetched live from Gmail, never stored by Sift)">Download</a>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
}

/** Sanitized mail HTML in a locked frame: no scripts (no allow-scripts, and the document's own
 * policy forbids them). Same-origin is allowed only so the page can size the frame to its content.
 * The frame stays invisible until its document has loaded, so nothing flashes while it arrives.
 * Mail is shown in the app's dark colours; "Original colours" shows it as the sender made it. */
function MailFrame({ src, title }: { src: string; title: string }) {
  const ref = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(160);
  const [loaded, setLoaded] = useState(false);
  const [original, setOriginal] = useState(false);
  const url = original ? `${src}?colors=original` : src;

  function measure() {
    const doc = ref.current?.contentDocument;
    if (doc?.documentElement) setHeight(Math.min(Math.max(doc.documentElement.scrollHeight, 60), 20000));
  }
  useEffect(() => {
    const frame = ref.current;
    if (!frame) return;
    setLoaded(false);
    let ro: ResizeObserver | null = null;
    const onLoad = () => {
      measure();
      setLoaded(true);
      const body = frame.contentDocument?.body;
      if (body) { ro = new ResizeObserver(measure); ro.observe(body); }
    };
    frame.addEventListener("load", onLoad);
    return () => { frame.removeEventListener("load", onLoad); ro?.disconnect(); };
  }, [url]);

  return (
    <>
      <iframe ref={ref} src={url} title={title} className={`mail-frame${loaded ? " loaded" : ""}`} style={{ height }}
        sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox" referrerPolicy="no-referrer" />
      <div className="frame-tools">
        <button type="button" className="chip" onClick={() => setOriginal((o) => !o)}
          data-tip={original ? "Show it in Sift's dark colours" : "Show the mail exactly as the sender styled it"}>
          {original ? "Dark colours" : "Original colours"}
        </button>
      </div>
    </>
  );
}

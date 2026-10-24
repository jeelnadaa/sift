import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError, get, type Folder, type Mail, type Group } from "./api";
import { accountColor, flatten, humanize, relativeTime } from "./util";

/** Load data with loading/error state; `reload` re-runs it. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);
  const reload = useCallback(async () => {
    const n = ++seq.current;
    setLoading(true);
    try {
      const d = await fn();
      if (n === seq.current) { setData(d); setError(null); }
    } catch (e) {
      if (n === seq.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (n === seq.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { reload(); }, [reload]);
  return { data, setData, error, setError, loading, reload };
}

export const errorText = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message : String(e));

let toastFn: (s: string) => void = () => {};
export function toast(s: string) { toastFn(s); }
export function Toaster() {
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    let timer: number | undefined;
    toastFn = (s) => { setMsg(s); window.clearTimeout(timer); timer = window.setTimeout(() => setMsg(null), 2600); };
    return () => window.clearTimeout(timer);
  }, []);
  return msg ? <div className="toast" role="status">{msg}</div> : null;
}

export function Icon({ name }: { name: string }) {
  return <svg className="ico" aria-hidden="true"><use href={`#i-${name}`} /></svg>;
}

export function Dot({ tier }: { tier?: string | null }) {
  return <span className={`dot ${tier ?? "silent"}`} />;
}

export function Tag({ children, tone }: { children: ReactNode; tone?: string }) {
  return <span className={`tag ${tone ?? ""}`}>{typeof children === "string" ? humanize(children) : children}</span>;
}

export function Toggle({ on, onChange, label, disabled }: { on: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <span role="switch" aria-checked={on} aria-label={label} aria-disabled={disabled} tabIndex={disabled ? -1 : 0}
      className={`toggle ${on ? "on" : ""}`}
      onClick={() => !disabled && onChange(!on)}
      onKeyDown={(e) => { if (!disabled && (e.key === " " || e.key === "Enter")) { e.preventDefault(); onChange(!on); } }} />
  );
}

export function Banner({ tone, children, action, onAction }: { tone: "warn" | "err" | "ok"; children: ReactNode; action?: string; onAction?: () => void }) {
  return (
    <div className={`banner ${tone}`}>
      <span className={`dot ${tone === "err" ? "urgent" : tone === "ok" ? "ok" : "silent"}`} />
      <span>{children}</span>
      {action && <button className="btn btn-ghost btn-sm" onClick={onAction}>{action}</button>}
    </div>
  );
}

export function Modal({ title, children, foot, onClose }: { title: string; children: ReactNode; foot?: ReactNode; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <h3>{title}</h3>
        {children}
        <div className="foot">{foot ?? <button className="btn btn-ghost btn-sm" onClick={onClose}>Close</button>}</div>
      </div>
    </div>
  );
}

export function Avatar({ text, tone }: { text: string | null | undefined; tone?: string }) {
  const style = tone === "urgent" ? { background: "rgba(255,90,60,.15)", color: "var(--urgent)" } : undefined;
  return <div className="avatar" style={style}>{(text ?? "?").trim().charAt(0).toUpperCase() || "?"}</div>;
}

export function Acct({ name, color, id }: { name: string | null; color: string | null; id: string }) {
  if (!name) return null;
  return <span className="acct"><i style={{ background: accountColor(color, id) }} />{name}</span>;
}

/** A mail row. Draggable so it can be dropped on a folder (web UI only). */
export function MailRow({ m, onOpen, extra, draggable = true }: { m: Mail; onOpen?: () => void; extra?: ReactNode; draggable?: boolean }) {
  const [dragging, setDragging] = useState(false);
  const who = m.sender_name || m.sender || "Unknown";
  return (
    <div className={`row ${m.unread ? "unread" : ""} ${onOpen ? "click" : ""} ${dragging ? "dragging" : ""}`} onClick={onOpen}
      draggable={draggable}
      onDragStart={(e) => { e.dataTransfer.setData("application/x-sift-mail", m.id); e.dataTransfer.effectAllowed = "copy"; setDragging(true); }}
      onDragEnd={() => setDragging(false)}>
      <Dot tier={m.priority} />
      <Avatar text={who} tone={m.priority === "urgent" ? "urgent" : undefined} />
      <div className="main">
        <div className="who">
          {who}{m.thread_count && m.thread_count > 1 ? <span className="dim"> ({m.thread_count})</span> : null}
          {m.category && m.category !== "other" && <Tag tone={m.priority ?? undefined}>{m.category}</Tag>}
          {m.company && <Tag>{m.company}</Tag>}
        </div>
        <div className="subj">{m.summary || m.subject || "(no subject)"}</div>
      </div>
      {extra}
      <Acct name={m.account} color={m.account_color} id={m.account_id} />
      <span className="time">{relativeTime(m.received_at)}</span>
    </div>
  );
}

export function GroupRow({ g, onOpen }: { g: Group; onOpen: () => void }) {
  return (
    <div className="row group-row click" onClick={onOpen}>
      <Dot tier={g.urgent ? "urgent" : "digest"} />
      <div className="avatar">▤</div>
      <div className="main">
        <div className="who">{g.title} <Tag>{`${g.count} mails`}</Tag>{g.muted && <Tag>Muted</Tag>}
          {g.unread > 0 && <Tag tone="digest">{`${g.unread} unread`}</Tag>}{g.urgent > 0 && <Tag tone="urgent">{`${g.urgent} urgent`}</Tag>}</div>
        <div className="subj">Latest: {[g.latest_sender, g.latest_subject].filter(Boolean).join(" · ")}</div>
      </div>
      <span className="time">{relativeTime(g.received_at)}</span>
    </div>
  );
}

/** Choose a folder (or "Top level" when allowTop). */
export function FolderPicker({ title, exclude, allowTop, note, onPick, onClose }: {
  title: string; exclude?: Set<string>; allowTop?: boolean; note?: string; onPick: (f: Folder | null) => void; onClose: () => void;
}) {
  const { data, error } = useLoad(() => get<{ folders: Folder[] }>("/folders"));
  const rows = flatten(data?.folders ?? []).filter(([f]) => !exclude?.has(f.id) && !f.smart);
  return (
    <Modal title={title} onClose={onClose}>
      {note && <p className="dim" style={{ fontSize: 13, marginBottom: 10 }}>{note}</p>}
      {error && <p className="err-text">{error}</p>}
      {allowTop && <div className="pick" onClick={() => onPick(null)}><span className="dim">⌂</span>Top level</div>}
      {data && rows.length === 0 && !allowTop && <p className="dim">No folders yet. Make one under Folders.</p>}
      {rows.map(([f, depth]) => (
        <div key={f.id} className="pick" style={{ paddingLeft: 8 + depth * 18 }} onClick={() => onPick(f)}>
          <span className="sw" style={{ width: 10, height: 10, borderRadius: 3, background: f.color ?? "var(--text-3)", flex: "none" }} />{f.name}
        </div>
      ))}
    </Modal>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return <div className="field"><label>{label}</label>{children}</div>;
}

import { useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { ApiError, get, type Folder, type Mail, type Group } from "./api";
import { accountColor, flatten, fullTime, humanize, relativeTime } from "./util";

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

interface ToastAction { label: string; run: () => void }
let toastFn: (s: string, action?: ToastAction, ms?: number) => void = () => {};
export function toast(s: string) { toastFn(s); }
/** A toast with one button (e.g. "Undo" after Send), shown for `ms`. */
export function actionToast(s: string, action: ToastAction, ms: number) { toastFn(s, action, ms); }
export function Toaster() {
  const [msg, setMsg] = useState<{ text: string; action?: ToastAction } | null>(null);
  useEffect(() => {
    let timer: number | undefined;
    toastFn = (text, action, ms = 2600) => { setMsg({ text, action }); window.clearTimeout(timer); timer = window.setTimeout(() => setMsg(null), ms); };
    return () => window.clearTimeout(timer);
  }, []);
  if (!msg) return null;
  return (
    <div className="toast" role="status">
      {msg.text}
      {msg.action && <button className="toast-act" onClick={() => { const a = msg.action; setMsg(null); a?.run(); }}>{msg.action.label}</button>}
    </div>
  );
}

/** One custom tooltip for the whole app. Any element with `data-tip` (or a plain `title`,
 * which is converted so the browser's own tooltip never shows) gets it on hover or keyboard
 * focus, after a short delay. Placed above the element, flipped below near the top edge,
 * kept inside the window. */
export function TooltipLayer() {
  const [tip, setTip] = useState<{ text: string; x: number; y: number; below: boolean } | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const timer = useRef<number>();
  const current = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const find = (t: EventTarget | null) => {
      const el = (t as HTMLElement | null)?.closest?.("[data-tip],[title]") as HTMLElement | null;
      if (el?.hasAttribute("title")) {
        const t2 = el.getAttribute("title");
        el.removeAttribute("title");
        if (t2 && !el.dataset.tip) el.dataset.tip = t2;
      }
      return el?.dataset.tip ? el : null;
    };
    const hide = () => { window.clearTimeout(timer.current); current.current?.removeAttribute("aria-describedby"); current.current = null; setTip(null); };
    const show = (el: HTMLElement, delay: number) => {
      if (current.current === el) return;
      hide();
      current.current = el;
      timer.current = window.setTimeout(() => {
        if (!el.isConnected || !el.dataset.tip) return;
        const r = el.getBoundingClientRect();
        const below = r.top < 56;
        el.setAttribute("aria-describedby", "sift-tip");
        setTip({ text: el.dataset.tip, x: r.left + r.width / 2, y: below ? r.bottom + 8 : r.top - 8, below });
      }, delay);
    };
    const over = (e: MouseEvent) => { const el = find(e.target); if (el) show(el, 300); else if (current.current && !current.current.contains(e.target as Node)) hide(); };
    const focus = (e: FocusEvent) => { const el = find(e.target); if (el && (e.target as HTMLElement).matches(":focus-visible")) show(el, 0); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") hide(); };
    addEventListener("mouseover", over);
    addEventListener("focusin", focus);
    addEventListener("focusout", hide);
    addEventListener("mousedown", hide);
    addEventListener("scroll", hide, true);
    addEventListener("keydown", key);
    return () => {
      removeEventListener("mouseover", over); removeEventListener("focusin", focus); removeEventListener("focusout", hide);
      removeEventListener("mousedown", hide); removeEventListener("scroll", hide, true); removeEventListener("keydown", key);
    };
  }, []);

  // keep it inside the window once its size is known
  useEffect(() => {
    const el = box.current;
    if (!el || !tip) return;
    const w = el.offsetWidth;
    const left = Math.min(Math.max(8, tip.x - w / 2), innerWidth - w - 8);
    el.style.left = `${left}px`;
    el.style.setProperty("--arrow-x", `${tip.x - left}px`);
    el.style.visibility = "visible";
  }, [tip]);

  if (!tip) return null;
  return (
    <div ref={box} id="sift-tip" role="tooltip" className={`tip ${tip.below ? "below" : ""}`}
      style={{ top: tip.y, left: 0, visibility: "hidden" }}>{tip.text}</div>
  );
}

export function Icon({ name }: { name: string }) {
  return <svg className="ico" aria-hidden="true"><use href={`#i-${name}`} /></svg>;
}

const TIER_TIPS: Record<string, string> = {
  urgent: "Urgent: notified right away, re-sent until your phone confirms",
  normal: "Normal: notified once",
  digest: "Digest: quiet notification, kept for a batch look",
  silent: "Silent: stored and searchable, never notified",
  ok: "All good",
};

export function Dot({ tier, tip }: { tier?: string | null; tip?: string }) {
  return <span className={`dot ${tier ?? "silent"}`} data-tip={tip ?? TIER_TIPS[tier ?? "silent"]} />;
}

export function Tag({ children, tone, tip }: { children: ReactNode; tone?: string; tip?: string }) {
  return <span className={`tag ${tone ?? ""}`} data-tip={tip}>{typeof children === "string" ? humanize(children) : children}</span>;
}

export function Toggle({ on, onChange, label, disabled }: { on: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <span role="switch" aria-checked={on} aria-label={label} aria-disabled={disabled} tabIndex={disabled ? -1 : 0} data-tip={`${label}: ${on ? "on" : "off"}`}
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

export function Avatar({ text, tone, tip }: { text: string | null | undefined; tone?: string; tip?: string }) {
  const style = tone === "urgent" ? { background: "rgba(255,90,60,.15)", color: "var(--urgent)" } : undefined;
  return <div className="avatar" style={style} data-tip={tip}>{(text ?? "?").trim().charAt(0).toUpperCase() || "?"}</div>;
}

export function Acct({ name, color, id }: { name: string | null; color: string | null; id: string }) {
  if (!name) return null;
  return <span className="acct" data-tip={`Arrived in your ${name} account`}><i style={{ background: accountColor(color, id) }} />{name}</span>;
}

/** A mail row. Draggable so it can be dropped on a folder (web UI only). */
export function MailRow({ m, onOpen, extra, draggable = true, n, highlight, lead }: { m: Mail; onOpen?: () => void; extra?: ReactNode; draggable?: boolean; n?: number; highlight?: string[]; lead?: ReactNode }) {
  const [dragging, setDragging] = useState(false);
  const who = m.sender_name || m.sender || "Unknown";
  return (
    <div className={`row ${m.unread ? "unread" : ""} ${onOpen ? "click" : ""} ${dragging ? "dragging" : ""}`} onClick={onOpen}
      draggable={draggable}
      onDragStart={(e) => { e.dataTransfer.setData("application/x-sift-mail", m.id); e.dataTransfer.effectAllowed = "copy"; setDragging(true); }}
      onDragEnd={() => setDragging(false)}>
      {lead}
      {n !== undefined && <span className="num" data-tip={`Mail ${n} on this page`}>{n}</span>}
      <Dot tier={m.priority} tip={m.priority ? undefined : "Not in Sift: older mail found in Gmail"} />
      <Avatar text={who} tone={m.priority === "urgent" ? "urgent" : undefined} tip={m.sender ?? undefined} />
      <div className="main">
        <div className="who">
          {who}{m.thread_count && m.thread_count > 1 ? <span className="dim"> ({m.thread_count})</span> : null}
          {m.category && m.category !== "other" && <Tag tone={m.priority ?? undefined} tip="Category Sift gave this mail">{m.category}</Tag>}
          {m.company && <Tag tip={`On the ${m.company} company timeline`}>{m.company}</Tag>}
          {m.has_attachment && <span className="dim" data-tip="Has an attachment">📎</span>}
        </div>
        <div className="subj" data-tip={m.summary && m.subject ? `Subject: ${m.subject}` : undefined}><Highlight text={m.summary || m.subject || "(no subject)"} words={highlight} /></div>
      </div>
      {extra}
      <Acct name={m.account} color={m.account_color} id={m.account_id} />
      <span className="time" data-tip={fullTime(m.received_at) + (draggable ? "\nDrag the row onto a folder to file it" : "")}>{relativeTime(m.received_at)}</span>
    </div>
  );
}

const GROUP_KIND: Record<string, string> = {
  opportunity: "same company", list: "same mailing list", template: "same sender and kind of subject",
  similar: "similar subjects from one sender domain", sender: "a sender you chose to always group", thread: "same conversation",
};

export function GroupRow({ g, onOpen, n }: { g: Group; onOpen: () => void; n?: number }) {
  return (
    <div className="row group-row click" onClick={onOpen}>
      {n !== undefined && <span className="num" data-tip={`Row ${n} on this page`}>{n}</span>}
      <Dot tier={g.urgent ? "urgent" : "digest"} tip={g.urgent ? "Has urgent mail (also shown on its own row)" : "A group of similar mail"} />
      <div className="avatar" data-tip={`Grouped by ${GROUP_KIND[g.kind] ?? "similarity"}. Display only: nothing changes in Gmail.`}>▤</div>
      <div className="main">
        <div className="who">{g.title} <Tag tip="Mails in this group">{`${g.count} mails`}</Tag>{g.muted && <Tag tip="New mail in this group doesn't notify (urgent still does)">Muted</Tag>}
          {g.unread > 0 && <Tag tone="digest" tip="Unread in Gmail">{`${g.unread} unread`}</Tag>}{g.urgent > 0 && <Tag tone="urgent" tip="Urgent mail always keeps its own row too">{`${g.urgent} urgent`}</Tag>}</div>
        <div className="subj">Latest: {[g.latest_sender, g.latest_subject].filter(Boolean).join(" · ")}</div>
      </div>
      <span className="time" data-tip={`Latest mail ${fullTime(g.received_at)}`}>{relativeTime(g.received_at)}</span>
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

/** Cursor-based pages: "Page 2 of 7 · 193 mails", previous / next. Page numbers count from 1;
 * any filter change starts again at page 1 (usePages resets its cursor stack). */
export function Pager({ page, pages, total, onPrev, onNext, noun = "mails", bottom }: {
  page: number; pages: number; total: number; onPrev?: () => void; onNext?: () => void; noun?: string; bottom?: boolean;
}) {
  if (bottom && !onPrev && !onNext) return null;
  return (
    <div className={`pager ${bottom ? "bottom" : ""}`}>
      <b>Page {page}</b>
      {total >= 0
        ? <span className="dim">of {Math.max(pages, page)} · {total.toLocaleString()} {total === 1 ? noun.replace(/s$/, "") : noun}</span>
        : <span className="dim" data-tip="Gmail doesn't give an exact count for a search">{onNext ? "· more after this page" : "· last page"}</span>}
      <span className="spacer" />
      <button className="btn btn-ghost btn-sm" disabled={!onPrev} onClick={onPrev} data-tip={onPrev ? `Back to page ${page - 1}` : "This is the first page"}>‹ Previous</button>
      <button className="btn btn-ghost btn-sm" disabled={!onNext} onClick={onNext} data-tip={onNext ? `Older mail: page ${page + 1}` : "No older mail"}>Next ›</button>
    </div>
  );
}

type PageData<T> = { items: T[]; next_before: string | null; total?: number; pages?: number };

/** Pages over a cursor API. Keeps the cursor of every page visited so Previous works;
 * a change in `key` (filters) goes back to page 1, so rows are numbered from 1 again. */
export function usePages<T, P extends PageData<T> = PageData<T>>(load: (before: string | null) => Promise<P>, key: unknown[]) {
  const k = JSON.stringify(key);
  // remembered per list for this tab, so opening a mail and coming back keeps your page
  const store = `sift.pages:${location.pathname}`;
  const [state, setStateRaw] = useState<{ k: string; cursors: (string | null)[] }>(() => {
    try { const saved = JSON.parse(sessionStorage.getItem(store) ?? "null"); if (saved?.k === k) return saved; } catch { /* ignore */ }
    return { k, cursors: [null] };
  });
  const setState = (v: { k: string; cursors: (string | null)[] }) => {
    setStateRaw(v);
    try { sessionStorage.setItem(store, JSON.stringify(v)); } catch { /* ignore */ }
  };
  // any filter change starts again at page 1 (and forgets the old pages)
  useEffect(() => { if (state.k !== k) setState({ k, cursors: [null] }); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [k]);
  const cursors = state.k === k ? state.cursors : [null];
  const cursor = cursors[cursors.length - 1];
  const res = useLoad(() => load(cursor), [k, cursors.length, cursor]);
  const page = cursors.length;
  useEffect(() => { document.querySelector("main")?.scrollTo({ top: 0 }); }, [page, k]);
  const next = res.data?.next_before;
  return {
    ...res, page, pages: res.data?.pages ?? page, total: res.data?.total ?? res.data?.items.length ?? 0,
    onNext: next && !res.loading ? () => setState({ k, cursors: [...cursors, next] }) : undefined,
    onPrev: page > 1 ? () => setState({ k, cursors: cursors.slice(0, -1) }) : undefined,
  };
}

// ---- confirm / input dialogs (replace the browser's confirm() and prompt()) -------------------

type DialogReq =
  | { kind: "confirm"; title: string; body?: ReactNode; confirm: string; danger?: boolean; resolve: (v: boolean) => void }
  | { kind: "input"; title: string; label: string; initial: string; confirm: string; placeholder?: string; resolve: (v: string | null) => void };

let openDialog: (d: DialogReq) => void = () => {};

/** `await confirmDialog({...})` resolves true only when the user confirms. */
export function confirmDialog(o: { title: string; body?: ReactNode; confirm?: string; danger?: boolean }): Promise<boolean> {
  return new Promise((resolve) => openDialog({ kind: "confirm", confirm: "Confirm", ...o, resolve }));
}

/** `await inputDialog({...})` resolves the trimmed text, or null when cancelled. */
export function inputDialog(o: { title: string; label: string; initial?: string; confirm?: string; placeholder?: string }): Promise<string | null> {
  return new Promise((resolve) => openDialog({ kind: "input", initial: "", confirm: "Save", ...o, resolve }));
}

export function DialogHost() {
  const [d, setD] = useState<DialogReq | null>(null);
  const [text, setText] = useState("");
  useEffect(() => { openDialog = (req) => { setText(req.kind === "input" ? req.initial : ""); setD(req); }; }, []);
  if (!d) return null;
  const close = (ok: boolean) => {
    setD(null);
    if (d.kind === "confirm") d.resolve(ok);
    else d.resolve(ok && text.trim() ? text.trim() : null);
  };
  return (
    <Modal title={d.title} onClose={() => close(false)} foot={<>
      <button className="btn btn-ghost btn-sm" onClick={() => close(false)} data-tip="Close without doing anything">Cancel</button>
      <button className={`btn btn-sm ${d.kind === "confirm" && d.danger ? "btn-danger" : "btn-primary"}`} autoFocus={d.kind === "confirm"}
        disabled={d.kind === "input" && !text.trim()} onClick={() => close(true)}>{d.confirm}</button>
    </>}>
      {d.kind === "confirm" ? (typeof d.body === "string" ? <p className="muted">{d.body}</p> : d.body) : (
        <div className="field"><label htmlFor="dlg-in">{d.label}</label>
          <TextField id="dlg-in" value={text} onChange={setText} placeholder={d.placeholder} autoFocus onEnter={() => { if (text.trim()) close(true); }} /></div>
      )}
    </Modal>
  );
}

// ---- text field that wraps and grows instead of scrolling sideways ------------------------------

/** A text input that shows all of its text: long values wrap onto more lines and the box grows
 * (up to `maxRows`, then it scrolls down, never sideways). Enter runs `onEnter` instead of
 * adding a line break; pasted line breaks become spaces. */
export function TextField({ value, onChange, onEnter, onBlur, placeholder, id, className, maxRows = 8, autoFocus, maxLength, ariaLabel, code, inputMode }: {
  value: string; onChange: (v: string) => void; onEnter?: () => void; onBlur?: () => void; placeholder?: string; id?: string; className?: string;
  maxRows?: number; autoFocus?: boolean; maxLength?: number; ariaLabel?: string; code?: boolean; inputMode?: "decimal" | "numeric" | "text";
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    const line = parseFloat(getComputedStyle(el).lineHeight) || 20;
    const max = line * maxRows + 22;
    el.style.height = `${Math.min(el.scrollHeight + 2, max)}px`;
    el.style.overflowY = el.scrollHeight + 2 > max ? "auto" : "hidden";
  }, [value, maxRows]);
  return (
    <textarea ref={ref} id={id} rows={1} className={`input grow ${code ? "code" : ""} ${className ?? ""}`} value={value} placeholder={placeholder}
      autoFocus={autoFocus} maxLength={maxLength} aria-label={ariaLabel} inputMode={inputMode} spellCheck={!code}
      onChange={(e) => onChange(e.target.value.replace(/\r?\n/g, " "))} onBlur={onBlur}
      onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onEnter?.(); } }} />
  );
}

// ---- custom dropdown -----------------------------------------------------------------------

export interface Option { value: string; label: string; hint?: string }

/** Styled dropdown (listbox) replacing the native select: click or Enter/Space opens it,
 * arrows move, Enter picks, Escape closes, typing a letter jumps to the next match. */
export function Select({ value, options, onChange, ariaLabel, id, disabled }: {
  value: string; options: Option[]; onChange: (v: string) => void; ariaLabel?: string; id?: string; disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const uid = id ?? "sel";
  const current = options.find((o) => o.value === value) ?? options[0];

  useEffect(() => {
    if (!open) return;
    setActive(Math.max(0, options.findIndex((o) => o.value === value)));
    const away = (e: MouseEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    addEventListener("mousedown", away);
    return () => removeEventListener("mousedown", away);
  }, [open]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { list.current?.children[active]?.scrollIntoView({ block: "nearest" }); }, [active, open]);

  function pick(i: number) { onChange(options[i].value); setOpen(false); }
  function key(e: ReactKeyboardEvent<HTMLButtonElement>) {
    if (disabled) return;
    if (!open) {
      if (["Enter", " ", "ArrowDown", "ArrowUp"].includes(e.key)) { e.preventDefault(); setOpen(true); }
      return;
    }
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); setOpen(false); }
    else if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(options.length - 1, a + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
    else if (e.key === "Home") { e.preventDefault(); setActive(0); }
    else if (e.key === "End") { e.preventDefault(); setActive(options.length - 1); }
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(active); }
    else if (e.key === "Tab") setOpen(false);
    else if (e.key.length === 1) {
      const k = e.key.toLowerCase();
      const n = options.length;
      for (let s = 1; s <= n; s++) { const i = (active + s) % n; if (options[i].label.toLowerCase().startsWith(k)) { setActive(i); break; } }
    }
  }
  return (
    <div className={`select ${open ? "open" : ""}`} ref={root}>
      <button type="button" id={id} className="input select-btn" aria-haspopup="listbox" aria-expanded={open} aria-label={ariaLabel}
        aria-activedescendant={open ? `${uid}-${active}` : undefined} aria-controls={`${uid}-list`}
        disabled={disabled} onClick={() => setOpen((o) => !o)} onKeyDown={key} data-tip={current?.hint}>
        <span>{current?.label}</span><span className="caret" aria-hidden="true">▾</span>
      </button>
      {open && (
        <ul className="select-menu" role="listbox" id={`${uid}-list`} ref={list} aria-label={ariaLabel}>
          {options.map((o, i) => (
            <li key={o.value} id={`${uid}-${i}`} role="option" aria-selected={o.value === value}
              className={`${i === active ? "active" : ""} ${o.value === value ? "chosen" : ""}`}
              onMouseEnter={() => setActive(i)} onMouseDown={(e) => { e.preventDefault(); pick(i); }}>
              <span>{o.label}</span>{o.hint && <small>{o.hint}</small>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Marks the searched words in a line of text (text only, never HTML). */
export function Highlight({ text, words }: { text: string; words?: string[] }) {
  const ws = (words ?? []).map((w) => w.trim()).filter((w) => w.length > 1);
  if (!ws.length) return <>{text}</>;
  const re = new RegExp(`(${ws.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "ig");
  return <>{text.split(re).map((part, i) => (i % 2 ? <mark key={i}>{part}</mark> : part))}</>;
}

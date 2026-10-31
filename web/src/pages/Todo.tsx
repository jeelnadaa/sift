import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { del, get, patch, post, type Opportunity, type Todo } from "../api";
import { Top } from "../App";
import { Banner, confirmDialog, errorText, Modal, Select, Tag, TextField, toast, Toggle, useLoad } from "../components";
import { fullTime, googleCalendarUrl, toLocalInput } from "../util";

function dueTone(iso: string | null): string {
  if (!iso) return "";
  const h = (new Date(iso).getTime() - Date.now()) / 3.6e6;
  return h < 0 ? "urgent" : h < 24 ? "urgent" : h < 72 ? "warn" : "";
}

export function Todos() {
  const navigate = useNavigate();
  const [state, setState] = useState<"open" | "done">("open");
  const todos = useLoad(() => get<Todo[]>("/todos", { state }), [state], ["new_mail"]);
  const [editing, setEditing] = useState<Todo | "new" | null>(null);

  async function toggle(t: Todo) {
    try { await patch(`/todos/${t.id}`, { done: !t.done }); todos.reload(); } catch (e) { toast(errorText(e)); }
  }

  return (
    <>
      <Top title="To-do" refresh><button className="btn btn-primary btn-sm" onClick={() => setEditing("new")} data-tip="Add a to-do by hand, with an optional deadline">+ Add to-do</button></Top>
      <section className="page">
        <p className="lede">Action-needed mail with deadlines. Built by AI when a key exists, or by hand from any mail. Reminders arrive 24 hours and 2 hours before.</p>
        <div className="tabs">
          <button className={`chip ${state === "open" ? "on" : ""}`} onClick={() => setState("open")} data-tip="To-dos still to do">Open</button>
          <button className={`chip ${state === "done" ? "on" : ""}`} onClick={() => setState("done")} data-tip="To-dos you finished">Done</button>
        </div>
        {todos.error && <Banner tone="err">{todos.error}</Banner>}
        <div className="list">
          {todos.data?.length === 0 && <div className="empty">{state === "open" ? "Nothing to do. Nice." : "Nothing done yet."}</div>}
          {todos.data?.map((t) => (
            <div className="row" key={t.id}>
              <Toggle on={t.done} onChange={() => toggle(t)} label={`Mark ${t.title} ${t.done ? "not done" : "done"}`} />
              <div className="main">
                <div className="who" style={t.done ? { textDecoration: "line-through", color: "var(--text-3)" } : undefined}>{t.title}</div>
                {t.notes && <div className="subj" style={{ whiteSpace: "normal" }}>{t.notes}</div>}
                <div className="subj">{[t.company, t.sender_name && `from ${t.sender_name}`, t.source === "manual" ? "manual" : null].filter(Boolean).join(" · ")}</div>
              </div>
              {t.message_id && <button className="btn btn-ghost btn-sm" onClick={() => navigate(`/mail/${t.message_id}`)} data-tip="Open the mail this came from">Open mail</button>}
              {t.due_at && (
                <span className="inline" style={{ gap: 6 }}>
                  <Tag tone={t.done ? "ok" : dueTone(t.due_at)} tip="Due. Reminders come 24 h and 2 h before">{fullTime(t.due_at)}</Tag>
                  {!t.done && googleCalendarUrl({ title: t.title, deadlineIso: t.due_at, details: t.notes || (t.company ? `Company: ${t.company}` : "To-do from Sift") }) && (
                    <a
                      className="link dim"
                      style={{ fontSize: 13 }}
                      href={googleCalendarUrl({ title: t.title, deadlineIso: t.due_at, details: t.notes || (t.company ? `Company: ${t.company}` : "To-do from Sift") })!}
                      target="_blank"
                      rel="noopener noreferrer"
                      title="Add to Google Calendar"
                    >
                      📅
                    </a>
                  )}
                </span>
              )}
              <button className="chip" onClick={() => setEditing(t)} data-tip="Rename, change the deadline, notes or company">Edit</button>
              <button className="chip" onClick={async () => {
                if (!(await confirmDialog({ title: "Delete this to-do?", body: `"${t.title}" and its reminders go. The mail stays.`, confirm: "Delete", danger: true }))) return;
                try { await del(`/todos/${t.id}`); todos.reload(); } catch (e) { toast(errorText(e)); }
              }} data-tip="Delete this to-do">✕</button>
            </div>
          ))}
        </div>
      </section>
      {editing && <TodoDialog todo={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); todos.reload(); }} />}
    </>
  );
}

/** Add a to-do, or change one (name, notes, deadline, company). Reminders follow the deadline. */
function TodoDialog({ todo, onClose, onSaved }: { todo: Todo | null; onClose: () => void; onSaved: () => void }) {
  const opps = useLoad(() => get<Opportunity[]>("/opportunities", { status: "active" }), []);
  const [title, setTitle] = useState(todo?.title ?? "");
  const [notes, setNotes] = useState(todo?.notes ?? "");
  const [due, setDue] = useState(toLocalInput(todo?.due_at));
  const [company, setCompany] = useState(todo?.opportunity_id ?? "");
  async function save() {
    if (!title.trim()) return;
    const due_at = due ? new Date(due).toISOString() : null;
    try {
      if (todo) await patch(`/todos/${todo.id}`, { title: title.trim(), notes: notes.trim(), ...(due_at ? { due_at } : { clear_due: true }) });
      else await post("/todos", { title: title.trim(), notes: notes.trim() || null, due_at, opportunity_id: company || null });
      onSaved();
    } catch (e) { toast(errorText(e)); }
  }
  return (
    <Modal title={todo ? "Edit to-do" : "Add a to-do"} onClose={onClose}
      foot={<><button className="btn btn-ghost btn-sm" onClick={onClose} data-tip="Close without saving">Cancel</button>
        <button className="btn btn-primary btn-sm" disabled={!title.trim()} onClick={save}>{todo ? "Save" : "Add"}</button></>}>
      <div className="stack">
        <div className="field"><label htmlFor="tt">What</label><TextField id="tt" value={title} onChange={setTitle} autoFocus maxLength={300} onEnter={save} /></div>
        <div className="field"><label htmlFor="td">Due (optional)</label>
          <div className="inline"><input id="td" className="input" type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} />
            {due && <button className="chip" onClick={() => setDue("")} data-tip="No deadline">Clear</button>}</div></div>
        <div className="field"><label htmlFor="tn">Notes (optional)</label>
          <textarea id="tn" className="input" rows={3} maxLength={4000} value={notes} onChange={(e) => setNotes(e.target.value)} /></div>
        {!todo && (opps.data?.length ?? 0) > 0 && (
          <div className="field"><label htmlFor="tc">Company (optional)</label>
            <Select id="tc" value={company} onChange={setCompany} ariaLabel="Company"
              options={[{ value: "", label: "None" }, ...(opps.data ?? []).map((o) => ({ value: o.id, label: o.company }))]} /></div>
        )}
        <p className="dim" style={{ fontSize: 13 }}>Reminders come 24 hours and 2 hours before the deadline.</p>
      </div>
    </Modal>
  );
}

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { del, get, patch, post, type Todo } from "../api";
import { Top } from "../App";
import { Banner, Modal, Tag, Toggle, errorText, toast, useLoad } from "../components";
import { fullTime } from "../util";

function dueTone(iso: string | null): string {
  if (!iso) return "";
  const h = (new Date(iso).getTime() - Date.now()) / 3.6e6;
  return h < 0 ? "urgent" : h < 24 ? "urgent" : h < 72 ? "warn" : "";
}

export function Todos() {
  const navigate = useNavigate();
  const [state, setState] = useState<"open" | "done">("open");
  const todos = useLoad(() => get<Todo[]>("/todos", { state }), [state]);
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");

  async function toggle(t: Todo) {
    try { await patch(`/todos/${t.id}`, { done: !t.done }); todos.reload(); } catch (e) { toast(errorText(e)); }
  }
  async function add() {
    try {
      await post("/todos", { title: title.trim(), due_at: due ? new Date(due).toISOString() : null });
      setAdding(false); setTitle(""); setDue(""); todos.reload();
    } catch (e) { toast(errorText(e)); }
  }

  return (
    <>
      <Top title="To-do"><button className="btn btn-primary btn-sm" onClick={() => setAdding(true)} data-tip="Add a to-do by hand, with an optional deadline">+ Add to-do</button></Top>
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
                <div className="subj">{[t.company, t.sender_name && `from ${t.sender_name}`, t.source === "manual" ? "manual" : null].filter(Boolean).join(" · ")}</div>
              </div>
              {t.message_id && <button className="btn btn-ghost btn-sm" onClick={() => navigate(`/mail/${t.message_id}`)} data-tip="Open the mail this came from">Open mail</button>}
              {t.due_at && <Tag tone={t.done ? "ok" : dueTone(t.due_at)} tip="Due. Reminders come 24 h and 2 h before">{fullTime(t.due_at)}</Tag>}
              <button className="chip" onClick={async () => { try { await del(`/todos/${t.id}`); todos.reload(); } catch (e) { toast(errorText(e)); } }} data-tip="Delete this to-do">✕</button>
            </div>
          ))}
        </div>
      </section>
      {adding && (
        <Modal title="Add a to-do" onClose={() => setAdding(false)}
          foot={<><button className="btn btn-ghost btn-sm" onClick={() => setAdding(false)} data-tip="Close without saving">Cancel</button><button className="btn btn-primary btn-sm" disabled={!title.trim()} onClick={add} data-tip="Save this to-do">Add</button></>}>
          <div className="stack">
            <div className="field"><label htmlFor="tt">What</label><input id="tt" className="input" value={title} onChange={(e) => setTitle(e.target.value)} autoFocus /></div>
            <div className="field"><label htmlFor="td">Due (optional)</label><input id="td" className="input" type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} /></div>
          </div>
        </Modal>
      )}
    </>
  );
}

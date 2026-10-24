import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { del, get, post, put, type Category, type Draft, type Rule, type Suggestion } from "../api";
import { Top } from "../App";
import { Banner, Modal, Tag, Toggle, errorText, toast, useLoad } from "../components";
import { describe } from "../ruleForm";
import { actionLabel, actionTier } from "../util";

export function Rules() {
  const navigate = useNavigate();
  const rules = useLoad(() => get<Rule[]>("/rules"));
  const suggestions = useLoad(() => get<Suggestion[]>("/rules/suggestions"));
  const [text, setText] = useState("");
  const [converting, setConverting] = useState(false);
  const [dragId, setDragId] = useState<string | null>(null);

  async function convert() {
    setConverting(true);
    try {
      const r = await post<{ draft: Draft }>("/rules/from-text", { text: text.trim() });
      navigate("/rules/new", { state: { draft: r.draft, origin: "english" } });
    } catch (e) { toast(errorText(e)); } finally { setConverting(false); }
  }
  async function setEnabled(r: Rule, enabled: boolean) {
    try {
      await put(`/rules/${r.id}`, { name: r.name, enabled, conditions: r.conditions, action: r.action, exceptions: r.exceptions, account_scope: r.account_scope });
      rules.reload();
    } catch (e) { toast(errorText(e)); }
  }
  async function dropOn(target: Rule) {
    const list = rules.data ?? [];
    if (!dragId || dragId === target.id) return;
    const ids = list.map((r) => r.id).filter((i) => i !== dragId);
    ids.splice(ids.indexOf(target.id), 0, dragId);
    rules.setData(ids.map((i) => list.find((r) => r.id === i)!));  // optimistic
    try { rules.setData(await post<Rule[]>("/rules/reorder", { ids })); } catch (e) { toast(errorText(e)); rules.reload(); }
  }

  return (
    <>
      <Top title="Rules & categories"><button className="btn btn-primary btn-sm" onClick={() => navigate("/rules/new", { state: null })} data-tip="Build a rule with conditions, exceptions and an action">+ New rule</button></Top>
      <section className="page">
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="field"><label htmlFor="pe">Plain-English rule</label>
            <div className="inline">
              <input id="pe" className="input" style={{ flex: 1 }} value={text} onChange={(e) => setText(e.target.value)} maxLength={500}
                placeholder="Silence Slice and Kotak transaction mail but keep fraud alerts" onKeyDown={(e) => { if (e.key === "Enter" && text.trim()) convert(); }} />
              <button className="btn btn-primary btn-sm" style={{ height: 42 }} disabled={!text.trim() || converting} onClick={convert}>{converting ? "Drafting…" : "Convert"}</button>
            </div>
          </div>
          <p className="dim" style={{ fontSize: 13, marginTop: 8 }}>Needs your own AI key. Sift drafts the rule and you check it before saving. Without a key, build it below.</p>
        </div>
        {rules.error && <Banner tone="err">{rules.error}</Banner>}
        <div className="list">
          {rules.data?.length === 0 && <div className="empty">No rules yet.</div>}
          {rules.data?.map((r, i) => (
            <div key={r.id} className={`row click ${dragId === r.id ? "dragging" : ""}`} draggable
              onDragStart={() => setDragId(r.id)} onDragEnd={() => setDragId(null)}
              onDragOver={(e) => e.preventDefault()} onDrop={() => dropOn(r)}
              onClick={() => navigate(`/rules/${r.id}`, { state: { rule: r } })}>
              <span className="dim mono" data-tip="Order: the first matching rule wins. Drag the row to reorder">⋮⋮ {i + 1}</span>
              <div className="main">
                <div className="who">{r.name}</div>
                <div className="subj">{describe(r.conditions)} · hits {r.hit_count}{r.exceptions ? " · with exceptions" : ""}</div>
              </div>
              <Tag tone={actionTier(r.action.type)}>{actionLabel(r.action.type)}</Tag>
              {r.action.folder_id && <Tag>File in folder</Tag>}
              <span onClick={(e) => e.stopPropagation()}><Toggle on={r.enabled} label={`Rule ${r.name} enabled`} onChange={(v) => setEnabled(r, v)} /></span>
            </div>
          ))}
        </div>
        <div className="dim" style={{ marginTop: 12 }}>Drag to reorder. First match wins.</div>

        <h2 style={{ marginTop: 36 }}>Repeat-template suggestions</h2>
        <div className="list">
          {suggestions.data?.length === 0 && <div className="empty">No suggestions. They appear when the same kind of mail keeps arriving.</div>}
          {suggestions.data?.map((s) => (
            <div key={s.id} className="row">
              <div className="main"><div className="who">"{s.template}" · {s.domain}</div><div className="subj">Seen {s.count} times in 30 days · latest: {s.sample_subject}</div></div>
              <button className="btn btn-ghost btn-sm" onClick={() => post(`/rules/suggestions/${s.id}/dismiss`).then(suggestions.reload)} data-tip="Hide this suggestion and keep notifying as now">Keep notifying</button>
              <button className="btn btn-ghost btn-sm" onClick={() => post(`/rules/suggestions/${s.id}/accept`, { action: "digest" }).then(() => { suggestions.reload(); rules.reload(); })} data-tip="Future mail like this arrives as a quiet digest notification">Make digest</button>
              <button className="btn btn-primary btn-sm" onClick={() => post(`/rules/suggestions/${s.id}/accept`, { action: "silent" }).then(() => { suggestions.reload(); rules.reload(); })} data-tip="Future mail like this is stored silently, never notified">Silence it</button>
            </div>
          ))}
        </div>

        <h2 style={{ marginTop: 36 }}>Categories</h2>
        <Categories />
      </section>
    </>
  );
}

function Categories() {
  const cats = useLoad(() => get<Category[]>("/categories"));
  const [editing, setEditing] = useState<{ id: string | null; name: string; definition: string } | null>(null);
  async function save() {
    if (!editing) return;
    try {
      const body = { name: editing.name.trim(), definition: editing.definition.trim() };
      if (editing.id) await put(`/categories/${editing.id}`, body); else await post("/categories", body);
      setEditing(null); cats.reload();
    } catch (e) { toast(errorText(e)); }
  }
  return (
    <>
      <div className="tabs">
        {cats.data?.map((c) => (
          <button key={c.name} className={`chip ${c.builtin ? "on" : ""}`} data-tip={c.builtin ? "Built-in category" : `${c.definition ?? ""}\nClick to edit`}
            onClick={() => !c.builtin && setEditing({ id: c.id, name: c.name, definition: c.definition ?? "" })}>{c.name.replace(/_/g, " ").replace(/^./, (x) => x.toUpperCase())}</button>
        ))}
        <button className="chip" onClick={() => setEditing({ id: null, name: "", definition: "" })} data-tip="Describe a category in plain English for the AI to use">+ custom category</button>
      </div>
      <p className="dim" style={{ fontSize: 13 }}>Your own categories tell the AI what to look for, in plain English.</p>
      {editing && (
        <Modal title={editing.id ? "Edit category" : "New category"} onClose={() => setEditing(null)} foot={<>
          {editing.id && <button className="btn btn-danger btn-sm" onClick={async () => { try { await del(`/categories/${editing.id}`); setEditing(null); cats.reload(); } catch (e) { toast(errorText(e)); } }} data-tip="Delete for good (mail itself is never deleted)">Delete</button>}
          <button className="btn btn-ghost btn-sm" onClick={() => setEditing(null)} data-tip="Close without saving">Cancel</button>
          <button className="btn btn-primary btn-sm" disabled={!editing.name.trim() || !editing.definition.trim()} onClick={save} data-tip="Save changes">Save</button></>}>
          <div className="stack">
            <div className="field"><label htmlFor="cn">Name</label><input id="cn" className="input" value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} placeholder="Hostel notices" /></div>
            <div className="field"><label htmlFor="cd">What belongs here</label><textarea id="cd" className="input" rows={3} value={editing.definition} onChange={(e) => setEditing({ ...editing, definition: e.target.value })} placeholder="Mail from the hostel office about timings, fees or rooms" /></div>
          </div>
        </Modal>
      )}
    </>
  );
}

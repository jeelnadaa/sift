import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { del, get, post, put, type Account, type Action, type Cond, type Draft, type FolderTree, type Preview, type Rule } from "../api";
import { Top } from "../App";
import { Banner, confirmDialog, errorText, FolderPicker, Select, TextField, toast, useLoad } from "../components";
import { KINDS, describe, exceptionGroups, groupsToTree, kind, rowsToTree, treeToRows, type Row } from "../ruleForm";
import { ACTION_LABELS, findFolder } from "../util";

const QUIETING = new Set(["silent", "ignore", "digest"]);
const VERB: Record<string, string> = { silent: "stored silently", ignore: "ignored", digest: "sent to the digest", notify_normal: "notified as normal", notify_urgent: "notified as urgent", llm: "classified as usual" };

export function RuleEditor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const state = useLocation().state as { rule?: Rule; draft?: Draft; origin?: string } | null;
  // a rule opened by URL (reload) is fetched; one passed from the list is used directly
  const fetched = useLoad(async () => (id && !state?.rule ? (await get<Rule[]>("/rules")).find((r) => r.id === id) ?? null : null), [id]);
  const existing = state?.rule ?? fetched.data ?? null;
  if (id && !existing) return <><Top title="Edit rule" /><section className="page">{fetched.error ? <Banner tone="err">{fetched.error}</Banner> : fetched.loading ? <p className="dim">Loading…</p> : <Banner tone="err">Rule not found.</Banner>}</section></>;
  return <Editor key={existing?.id ?? "new"} existing={existing} draft={state?.draft ?? null} origin={state?.origin ?? "editor"} onDone={() => navigate("/rules")} />;
}

function Editor({ existing, draft, origin, onDone }: { existing: Rule | null; draft: Draft | null; origin: string; onDone: () => void }) {
  const source: Draft | null = existing ?? draft;
  const parsed = useMemo(() => treeToRows(source?.conditions), [source]);
  const parsedExc = useMemo(() => exceptionGroups(source?.exceptions), [source]);
  const editable = !source || (parsed !== null && parsedExc !== null);

  const [name, setName] = useState(source?.name ?? "");
  const [all, setAll] = useState(parsed?.all ?? true);
  const [rows, setRows] = useState<Row[]>(parsed?.rows.length ? parsed.rows : [{ kind: "sender_domain", text: "" }]);
  const [groups, setGroups] = useState<Row[][]>(parsedExc ?? []);
  const [action, setAction] = useState(source?.action.type ?? "silent");
  const [folderId, setFolderId] = useState<string | null>((source?.action.folder_id as string | undefined) ?? null);
  const [scope, setScope] = useState<string[] | null>(source?.account_scope ?? null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [picking, setPicking] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tree = useLoad(() => get<FolderTree>("/folders"));
  const accounts = useLoad(() => get<Account[]>("/accounts"));

  const conditions: Cond | null = editable ? rowsToTree(all, rows) : source!.conditions;
  const exceptions: Cond | null = editable ? groupsToTree(groups) : source!.exceptions;
  const key = JSON.stringify([conditions, exceptions, scope]);
  useEffect(() => {
    if (!conditions) { setPreview(null); return; }
    const t = setTimeout(() => {
      post<Preview>("/rules/preview", { conditions, exceptions, account_scope: scope }).then(setPreview).catch(() => setPreview(null));
    }, 500);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const folderName = folderId ? findFolder(tree.data?.folders ?? [], folderId)?.name ?? (tree.data ? "a deleted folder" : "…") : null;
  const hidesImportant = !!preview && QUIETING.has(action) && preview.important_matches > 0;

  async function save() {
    if (!conditions) { setError("Add at least one condition."); return; }
    if (hidesImportant && !(await confirmDialog({ title: "Save anyway?", danger: true, confirm: "Save anyway",
      body: `${preview!.important_matches} matching mail(s) look important (urgent, needs action, or on a company timeline). This rule would quiet mail like them.` }))) return;
    setSaving(true);
    // keep extras this form doesn't edit (category, tag); folder comes from the picker
    const { type: _t, folder_id: _f, ...extras } = source?.action ?? ({} as Action);
    const body = { name: name.trim(), enabled: existing?.enabled ?? true, conditions, exceptions,
      action: { ...extras, type: action, ...(folderId ? { folder_id: folderId } : {}) }, account_scope: scope?.length ? scope : null, origin };
    try {
      if (existing) await put(`/rules/${existing.id}`, body); else await post("/rules", body);
      toast("Rule saved");
      onDone();
    } catch (e) { setError(errorText(e)); } finally { setSaving(false); }
  }

  async function remove() {
    if (!existing) return;
    const ok = await confirmDialog({ title: `Delete "${existing.name}"?`, body: "The rule stops working right away. Mail it already handled stays where it is.", confirm: "Delete rule", danger: true });
    if (!ok) return;
    try { await del(`/rules/${existing.id}`); toast("Rule deleted"); onDone(); } catch (e) { toast(errorText(e)); }
  }
  const actions = <>
    <button className="btn btn-primary btn-sm" disabled={saving || !name.trim() || !conditions} onClick={save} data-tip={!conditions ? "Add at least one condition first" : !name.trim() ? "Give the rule a name first" : "Save this rule. It applies to new mail from now on"}>{saving ? "Saving…" : "Save rule"}</button>
    <button className="btn btn-ghost btn-sm" onClick={onDone} data-tip="Close without saving">Cancel</button>
    {existing && <button className="btn btn-danger btn-sm" onClick={remove} data-tip="Delete this rule (mail itself is never deleted)">Delete</button>}
  </>;

  return (
    <>
      <Top title={existing ? "Edit rule" : "New rule"} back="/rules">{actions}</Top>
      <section className="page">
        <div className="split wide">
          <div className="card">
            {origin === "english" && !existing && <Banner tone="ok">Drafted from your sentence. Check it, then save.</Banner>}
            {draft?.notes?.length && !existing ? <Banner tone="warn">{draft.notes.join(" ")}</Banner> : null}
            {error && <Banner tone="err">{error}</Banner>}
            <div className="field" style={{ marginBottom: 16 }}><label htmlFor="rn">Name</label>
              <TextField id="rn" value={name} onChange={setName} placeholder="Bank alerts: silent" maxLength={200} /></div>

            <div className="field" style={{ marginBottom: 16 }}><label>Scope</label>
              <div className="tabs" style={{ margin: 0 }}>
                <button className={`chip ${!scope ? "on" : ""}`} onClick={() => setScope(null)}>All accounts</button>
                {accounts.data?.map((a) => {
                  const on = !!scope?.includes(a.id);
                  return <button key={a.id} className={`chip ${on ? "on" : ""}`} onClick={() => {
                    const next = on ? (scope ?? []).filter((x) => x !== a.id) : [...(scope ?? []), a.id];
                    setScope(next.length ? next : null);
                  }}>{a.label || a.email}</button>;
                })}
              </div>
            </div>

            {editable ? (
              <>
                <div className="field"><label>When</label></div>
                <div className="tabs" style={{ margin: "6px 0 10px" }}>
                  <button className={`chip ${all ? "on" : ""}`} onClick={() => setAll(true)} data-tip="Every condition must match">All of these</button>
                  <button className={`chip ${!all ? "on" : ""}`} onClick={() => setAll(false)} data-tip="One matching condition is enough">Any of these</button>
                </div>
                {rows.map((r, i) => <CondRow key={i} row={r} onChange={(n) => setRows(rows.map((x, j) => (j === i ? n : x)))} onRemove={rows.length > 1 ? () => setRows(rows.filter((_, j) => j !== i)) : undefined} />)}
                <button className="chip" style={{ margin: "4px 0 18px" }} onClick={() => setRows([...rows, { kind: "subject_any", text: "" }])} data-tip="Add another condition">+ condition</button>

                <div className="field"><label>Unless (any of these groups)</label></div>
                {groups.map((g, gi) => (
                  <div key={gi} style={{ border: "1px solid var(--line-2)", borderRadius: "var(--r-lg)", padding: 10, margin: "8px 0" }}>
                    <div className="inline" style={{ marginBottom: 6 }}>
                      <span className="dim" style={{ fontSize: 12.5, fontWeight: 700 }}>{g.length > 1 ? `Exception ${gi + 1}: all of` : `Exception ${gi + 1}`}</span>
                      <span className="spacer" /><a className="link dim" onClick={() => setGroups(groups.filter((_, j) => j !== gi))} data-tip="Delete this exception">Remove</a>
                    </div>
                    {g.map((r, i) => <CondRow key={i} exc row={r}
                      onChange={(n) => setGroups(groups.map((x, j) => (j === gi ? x.map((y, k) => (k === i ? n : y)) : x)))}
                      onRemove={g.length > 1 ? () => setGroups(groups.map((x, j) => (j === gi ? x.filter((_, k) => k !== i) : x))) : undefined} />)}
                    <a className="link" style={{ fontSize: 13 }} onClick={() => setGroups(groups.map((x, j) => (j === gi ? [...x, { kind: "amount_above", text: "" }] : x)))} data-tip="Add another condition that must also be true in this exception">+ and…</a>
                  </div>
                ))}
                <button className="chip" style={{ margin: "4px 0 10px" }} onClick={() => setGroups([...groups, [{ kind: "subject_any", text: "" }]])} data-tip="Mail matching an exception is never handled by this rule">+ exception</button>
                <p className="dim" style={{ fontSize: 13 }}>Sender conditions only match mail Gmail verified (DKIM/SPF), so spoofed senders never match. Amounts are read from the subject or preview text.</p>
              </>
            ) : (
              <>
                <div className="field"><label>When</label></div><p style={{ margin: "6px 0 12px" }}>{describe(source?.conditions)}</p>
                {source?.exceptions && <><div className="field"><label>Unless</label></div><p style={{ margin: "6px 0 12px" }}>{describe(source.exceptions)}</p></>}
                <p className="dim" style={{ fontSize: 13 }}>This rule's shape can't be edited in this form, but you can rename it, change its action, save or delete it.</p>
              </>
            )}

            <div className="field" style={{ marginTop: 18 }}><label>Then</label></div>
            <div className="tabs" style={{ margin: "6px 0 10px" }}>
              {ACTION_LABELS.map(([k, label]) => <button key={k} className={`chip ${action === k ? "on" : ""}`} onClick={() => setAction(k)}>{label}</button>)}
            </div>
            <div className="inline">
              <span className="muted">{folderName ? <>Also file in <b style={{ color: "var(--text)" }}>{folderName}</b></> : "Also file in a folder"}</span>
              <a className="link" onClick={() => setPicking(true)}>{folderId ? "Change" : "Pick"}</a>
              {folderId && <a className="link dim" onClick={() => setFolderId(null)} data-tip="Stop filing matching mail in a folder">Remove</a>}
            </div>
            <div className="inline form-actions">{actions}</div>
          </div>

          <div className="card" style={{ background: "var(--bg-2)", borderColor: hidesImportant ? "rgba(255,90,60,.5)" : undefined, position: "sticky", top: 90 }}>
            {!preview ? <p className="dim">Add a condition to see which of your recent mail it matches.</p> : (
              <>
                <p className="dim" style={{ fontSize: 13 }}>Of the {preview.checked} mails Sift has stored:</p>
                <div className="inline" style={{ alignItems: "baseline" }}>
                  <b style={{ fontFamily: "var(--font-display)", fontSize: 38, color: hidesImportant ? "var(--urgent)" : "var(--signal)" }}>{preview.matches}</b>
                  <span className="muted">would be {VERB[action] ?? action}{folderName ? ` and filed in ${folderName}` : ""}</span>
                </div>
                {hidesImportant && <p style={{ color: "var(--urgent)", fontWeight: 700, marginTop: 4 }}>{preview.important_matches} of them look important (urgent, needs action, or on a company timeline). This rule would quiet them.</p>}
                <div style={{ marginTop: 10 }}>
                  {preview.samples.map((s) => <p key={s.id} style={{ fontSize: 13.5, color: s.important && QUIETING.has(action) ? "var(--urgent)" : "var(--text-2)" }} className="subj">{s.important ? "⚠ " : "· "}{s.sender} · {s.subject}</p>)}
                </div>
                {preview.kept_by_exceptions > 0 && (
                  <>
                    <p style={{ marginTop: 14, fontWeight: 700 }}>{preview.kept_by_exceptions} kept by your exceptions</p>
                    {preview.kept_samples.map((s) => <p key={s.id} style={{ fontSize: 13.5 }} className="subj dim">· {s.sender} · {s.subject}</p>)}
                  </>
                )}
                {preview.body_not_previewed && <p className="dim" style={{ fontSize: 13, marginTop: 10 }}>Body conditions aren't previewed: Sift doesn't store mail bodies.</p>}
              </>
            )}
          </div>
        </div>
      </section>
      {picking && <FolderPicker title="File matching mail in…" note="Filing never changes the mail in Gmail." onClose={() => setPicking(false)}
        onPick={(f) => { setPicking(false); if (f) setFolderId(f.id); }} />}
    </>
  );
}

function CondRow({ row, onChange, onRemove, exc }: { row: Row; onChange: (r: Row) => void; onRemove?: () => void; exc?: boolean }) {
  const k = kind(row.kind);
  return (
    <div className={`cond ${exc ? "exc" : ""}`}>
      <Select value={row.kind} ariaLabel="Condition" options={KINDS.map((x) => ({ value: x.key, label: x.label, hint: x.inputLabel || undefined }))}
        onChange={(v) => onChange({ kind: v, text: row.text })} />
      {k.key !== "attachment" && <TextField value={row.text} placeholder={k.hint} ariaLabel={k.inputLabel} code={k.key === "subject_regex"}
        inputMode={k.field === "amount" ? "decimal" : undefined} onChange={(v) => onChange({ kind: row.kind, text: v })} />}
      {onRemove && <button className="chip" onClick={onRemove} aria-label="Remove condition" data-tip="Remove this condition">✕</button>}
    </div>
  );
}

import { useRef, useState } from "react";
import { del, get, patch, post, put, type AiStatus, type GroupingStatus, type Settings } from "../api";
import { Top, foldersChanged } from "../App";
import { Banner, Tag, Toggle, errorText, toast, useLoad } from "../components";

export function SettingsPage() {
  const ai = useLoad(() => get<AiStatus>("/ai"));
  const settings = useLoad(() => get<Settings>("/settings"));
  const grouping = useLoad(() => get<GroupingStatus>("/grouping"));
  const [model, setModel] = useState<string | null>(null);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [cap, setCap] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const a = ai.data;
  const s = settings.data;

  async function change(changes: Partial<Settings>) {
    try { settings.setData(await patch<Settings>("/settings", changes)); } catch (e) { toast(errorText(e)); }
  }
  async function saveKey() {
    setBusy(true);
    try {
      const r = await put<AiStatus>("/ai/key", { provider: "gemini", model: (model ?? a?.model ?? a?.suggested_model ?? "").trim(), api_key: key.trim() });
      ai.setData(r); setKey("");
      toast(r.status === "valid" ? "Key works. AI is on." : r.status === "invalid" ? "The key was rejected." : r.status === "quota_exceeded" ? "Key saved, but its quota is used up." : "Saved; could not verify yet.");
    } catch (e) { toast(errorText(e)); } finally { setBusy(false); }
  }
  async function exportBackup() {
    try {
      const data = await get<object>("/backup");
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = url; link.download = `sift-backup-${new Date().toISOString().slice(0, 10)}.json`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) { toast(errorText(e)); }
  }
  async function importBackup(file: File) {
    if (file.size > 5_000_000) { toast("That file is too big for a Sift backup."); return; }
    try {
      const data = JSON.parse(await file.text());
      const r = await post<Record<string, number>>("/backup", data);
      toast(`Imported ${r.folders} folders, ${r.rules} rules${r.rules_disabled ? ` (${r.rules_disabled} off: their accounts aren't connected)` : ""}, ${r.tags} tags, ${r.categories} categories.`);
      foldersChanged(); settings.reload();
    } catch (e) { toast(e instanceof SyntaxError ? "That file isn't valid JSON." : errorText(e)); }
  }

  return (
    <>
      <Top title="Settings" />
      <section className="page" style={{ maxWidth: 860 }}>
        {ai.error && <Banner tone="err">{ai.error}</Banner>}
        <div className="settings-sec"><h2>AI provider · your own key</h2>
          <div className="card">
            <div className="inline" style={{ marginBottom: 12 }}>
              <b>{a?.ai_enabled ? "AI on" : "AI off"}</b>
              {a && <Tag tone={{ valid: "ok", missing: "", quota_exceeded: "warn" }[a.status] ?? "urgent"}>{{ missing: "No key", quota_exceeded: "Quota exceeded" }[a.status] ?? a.status}</Tag>}
              {a?.key_last4 && <span className="dim" style={{ fontSize: 13 }}>Gemini · <span className="code">{a.model}</span> · key ••••{a.key_last4}</span>}
            </div>
            {a && !a.ai_enabled && <p style={{ color: "var(--warn)", fontSize: 13.5, marginBottom: 12 }}>Add an API key to enable summaries, deadlines, company matching and plain-English rules. Everything else works without one, and unhandled mail arrives as normal priority.</p>}
            <div className="grid2">
              <div className="field"><label htmlFor="pv">Provider</label><select id="pv" className="input" value="gemini" onChange={() => {}}><option value="gemini">Gemini</option></select></div>
              <div className="field"><label htmlFor="md">Model ID</label><input id="md" className="input code" value={model ?? a?.model ?? a?.suggested_model ?? ""} onChange={(e) => setModel(e.target.value)} /></div>
            </div>
            <div className="field" style={{ marginTop: 16 }}><label htmlFor="ky">{a?.key_last4 ? "Replace API key" : "API key"}</label>
              <div className="inline">
                <input id="ky" className="input code" style={{ flex: 1 }} type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder="Paste a key from aistudio.google.com" />
                <button className="btn btn-primary btn-sm" style={{ height: 42 }} disabled={busy || key.trim().length < 10} onClick={saveKey}>{busy ? "Checking…" : "Save and test"}</button>
                {a?.key_last4 && <button className="btn btn-ghost btn-sm" style={{ height: 42 }} onClick={async () => { try { ai.setData(await post<AiStatus>("/ai/test")); } catch (e) { toast(errorText(e)); } }}>Test</button>}
                {a?.key_last4 && <button className="btn btn-danger btn-sm" style={{ height: 42 }} data-tip="Delete the stored key. Sift keeps working without AI" onClick={async () => { try { await del("/ai/key"); ai.reload(); } catch (e) { toast(errorText(e)); } }}>Remove</button>}
              </div>
            </div>
            <p className="dim" style={{ fontSize: 13, marginTop: 8 }}>Stored encrypted on your server and never shown again after saving.</p>
            {s && (
              <div className="field" style={{ marginTop: 16, maxWidth: 260 }}><label htmlFor="cap">Daily token cap</label>
                <input id="cap" className="input mono" inputMode="numeric" value={cap ?? String(s.daily_token_cap)} onChange={(e) => setCap(e.target.value.replace(/\D/g, ""))}
                  onBlur={() => { if (cap && Number(cap) !== s.daily_token_cap) change({ daily_token_cap: Number(cap) }); setCap(null); }} /></div>
            )}
          </div>
        </div>

        {s && (
          <div className="settings-sec"><h2>Notifications</h2>
            <div className="set-row"><div>Re-send urgent until delivered<small>Every {s.resend_after_minutes} min, up to {s.resend_limit} times</small></div>
              <Toggle on={s.resend_urgent} label="Re-send urgent" onChange={(v) => change({ resend_urgent: v })} /></div>
            <div className="set-row"><div>Re-send every</div>
              <div className="inline">{[2, 5, 10].map((m) => <button key={m} className={`chip ${s.resend_after_minutes === m ? "on" : ""}`} onClick={() => change({ resend_after_minutes: m })}>{m} min</button>)}</div></div>
            <div className="set-row"><div>Time zone<small>For rule time windows and deadlines</small></div><span className="muted">{s.timezone}</span></div>
          </div>
        )}

        <div className="settings-sec"><h2>Mail</h2>
          {grouping.data && (
            <div className="set-row"><div>Group similar emails<small>Display only. Urgent mail keeps its own row; notifications don't change.</small></div>
              <Toggle on={grouping.data.grouping_enabled === "yes"} label="Group similar emails" onChange={async (v) => {
                try { grouping.setData(await post<GroupingStatus>("/grouping", { answer: v ? "yes" : "no" })); } catch (e) { toast(errorText(e)); }
              }} /></div>
          )}
        </div>

        <div className="settings-sec"><h2>Data</h2>
          <div className="set-row"><div>Export folders, rules, tags, categories &amp; settings<small>One JSON file. No mail, tokens or keys.</small></div>
            <button className="btn btn-ghost btn-sm" onClick={exportBackup} data-tip="Download folders, rules, tags, categories and settings as JSON. No mail or keys">Export</button></div>
          <div className="set-row"><div>Import a backup<small>Adds to what you have; never deletes. Rules for accounts that aren't connected come in switched off.</small></div>
            <button className="btn btn-ghost btn-sm" onClick={() => fileInput.current?.click()} data-tip="Add folders, rules and settings from a Sift backup file">Import…</button>
            <input ref={fileInput} type="file" accept="application/json,.json" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) importBackup(f); e.target.value = ""; }} /></div>
        </div>
      </section>
    </>
  );
}

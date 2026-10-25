import { useEffect, useRef, useState } from "react";
import { clearSaved, savedSize } from "../offline";
import { del, get, patch, post, put, type Account, type AiStatus, type GroupingStatus, type Settings } from "../api";
import { Top, foldersChanged } from "../App";
import { Banner, confirmDialog, errorText, Select, Tag, TextField, toast, Toggle, useLoad } from "../components";
import { CATEGORY_LABELS } from "./FolderAi";

const PROVIDER_OPTIONS = [
  { value: "gemini", label: "Gemini", hint: "Google AI Studio key" },
  { value: "ollama", label: "Ollama", hint: "Local / self-hosted" },
  { value: "openai_compatible", label: "OpenAI-compatible", hint: "OpenAI, Groq, OpenRouter, DeepSeek" },
];

export function SettingsPage() {
  const ai = useLoad(() => get<AiStatus>("/ai"));
  const settings = useLoad(() => get<Settings>("/settings"));
  const grouping = useLoad(() => get<GroupingStatus>("/grouping"));
  const accounts = useLoad(() => get<Account[]>("/accounts"));
  const [provider, setProvider] = useState<string>("gemini");
  const [model, setModel] = useState<string | null>(null);
  const [baseUrl, setBaseUrl] = useState<string>("");
  const [key, setKey] = useState("");
  const [enableFallback, setEnableFallback] = useState(false);
  const [fallbackProvider, setFallbackProvider] = useState<string>("ollama");
  const [fallbackModel, setFallbackModel] = useState<string>("");
  const [fallbackBaseUrl, setFallbackBaseUrl] = useState<string>("");
  const [fallbackKey, setFallbackKey] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [cap, setCap] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const a = ai.data;
  const s = settings.data;

  useEffect(() => {
    if (a) {
      if (a.provider) setProvider(a.provider);
      if (a.base_url) setBaseUrl(a.base_url);
      if (a.fallback_provider) {
        setEnableFallback(true);
        setFallbackProvider(a.fallback_provider);
        if (a.fallback_model) setFallbackModel(a.fallback_model);
        if (a.fallback_base_url) setFallbackBaseUrl(a.fallback_base_url);
      }
    }
  }, [a?.provider, a?.base_url, a?.fallback_provider, a?.fallback_model, a?.fallback_base_url]);

  async function change(changes: Partial<Settings>) {
    try { settings.setData(await patch<Settings>("/settings", changes)); } catch (e) { toast(errorText(e)); }
  }
  async function saveKey() {
    setBusy(true);
    try {
      const effectiveModel = (model ?? a?.model ?? (provider === "ollama" ? "llama3.2" : provider === "openai_compatible" ? "gpt-4o-mini" : a?.suggested_model ?? "")).trim();
      const r = await put<AiStatus>("/ai/key", {
        provider,
        model: effectiveModel,
        api_key: key.trim() || (provider === "ollama" ? "ollama-local" : ""),
        base_url: baseUrl.trim() || null,
        fallback_provider: enableFallback ? fallbackProvider : null,
        fallback_model: enableFallback ? (fallbackModel.trim() || (fallbackProvider === "ollama" ? "llama3.2" : fallbackProvider === "openai_compatible" ? "gpt-4o-mini" : "gemini-2.5-flash")) : null,
        fallback_base_url: enableFallback && fallbackBaseUrl.trim() ? fallbackBaseUrl.trim() : null,
        fallback_api_key: enableFallback && fallbackKey.trim() ? fallbackKey.trim() : (enableFallback && fallbackProvider === "ollama" ? "ollama-local" : null),
      });
      ai.setData(r); setKey(""); setFallbackKey("");
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
      <section className="page">
        {ai.error && <Banner tone="err">{ai.error}</Banner>}
        <div className="settings-sec"><h2>AI provider · your own key</h2>
          <div className="card">
            <div className="inline" style={{ marginBottom: 12 }}>
              <b>{a?.ai_enabled ? "AI on" : "AI off"}</b>
              {a && <Tag tone={{ valid: "ok", missing: "", quota_exceeded: "warn" }[a.status] ?? "urgent"}>{{ missing: "No key", quota_exceeded: "Quota exceeded" }[a.status] ?? a.status}</Tag>}
              {a?.key_last4 && <span className="dim" style={{ fontSize: 13 }}>{a.provider ? a.provider.toUpperCase() : "GEMINI"} · <span className="code">{a.model}</span> · key ••••{a.key_last4}{a.base_url ? ` · ${a.base_url}` : ""}</span>}
              {a?.fallback_provider && <span className="dim" style={{ fontSize: 12, marginLeft: 8 }}>· Fallback: {a.fallback_provider} (<span className="code">{a.fallback_model}</span>)</span>}
            </div>
            {a && !a.ai_enabled && <p style={{ color: "var(--warn)", fontSize: 13.5, marginBottom: 12 }}>Add an API key to enable summaries, deadlines, company matching and plain-English rules. Everything else works without one, and unhandled mail arrives as normal priority.</p>}
            <div className="grid2">
              <div className="field"><label htmlFor="pv">Provider</label><Select id="pv" value={provider} ariaLabel="AI provider" options={PROVIDER_OPTIONS} onChange={setProvider} /></div>
              <div className="field"><label htmlFor="md">Model ID</label><TextField id="md" code value={model ?? a?.model ?? (provider === "ollama" ? "llama3.2" : provider === "openai_compatible" ? "gpt-4o-mini" : a?.suggested_model ?? "")} onChange={setModel} maxLength={120} /></div>
            </div>
            {(provider === "ollama" || provider === "openai_compatible") && (
              <div className="field" style={{ marginTop: 12 }}>
                <label htmlFor="burl">Base URL</label>
                <TextField id="burl" code value={baseUrl} onChange={setBaseUrl} placeholder={provider === "ollama" ? "http://localhost:11434/v1" : "https://api.openai.com/v1"} maxLength={200} />
              </div>
            )}
            <div className="field" style={{ marginTop: 16 }}><label htmlFor="ky">{a?.key_last4 ? "Replace API key" : "API key"}</label>
              <div className="inline">
                <input id="ky" className="input code" style={{ flex: 1 }} type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder={provider === "ollama" ? "Optional for local Ollama" : provider === "openai_compatible" ? "Paste OpenAI/Groq/OpenRouter key" : "Paste a key from aistudio.google.com"} />
                <button className="btn btn-primary btn-sm" style={{ height: 42 }} disabled={busy || (provider !== "ollama" && !a?.key_last4 && key.trim().length < 10)} onClick={saveKey}>{busy ? "Checking…" : "Save and test"}</button>
                {a?.key_last4 && <button className="btn btn-ghost btn-sm" style={{ height: 42 }} onClick={async () => { try { ai.setData(await post<AiStatus>("/ai/test")); } catch (e) { toast(errorText(e)); } }}>Test</button>}
                {a?.key_last4 && <button className="btn btn-danger btn-sm" style={{ height: 42 }} data-tip="Delete the stored key. Sift keeps working without AI" onClick={async () => { if (!(await confirmDialog({ title: "Remove your AI key?", body: "Sift deletes the stored key and keeps working without AI: unhandled mail arrives as normal priority.", confirm: "Remove key", danger: true }))) return; try { await del("/ai/key"); ai.reload(); } catch (e) { toast(errorText(e)); } }}>Remove</button>}
              </div>
            </div>
            <div style={{ marginTop: 20, paddingTop: 16, borderTop: "1px solid var(--border)" }}>
              <div className="inline" style={{ justifyContent: "space-between", marginBottom: 10 }}>
                <div>
                  <b style={{ fontSize: 14 }}>Fallback LLM Provider</b>
                  <p className="dim" style={{ fontSize: 12.5, margin: 0 }}>Automatic failover if primary provider hits quota limit (429) or fails</p>
                </div>
                <Toggle on={enableFallback} label="Enable Fallback" onChange={setEnableFallback} />
              </div>
              {enableFallback && (
                <div style={{ marginTop: 12, padding: "12px 14px", background: "var(--bg-card-subtle, rgba(255,255,255,0.03))", borderRadius: 8 }}>
                  <div className="grid2">
                    <div className="field">
                      <label htmlFor="fpv">Fallback Provider</label>
                      <Select id="fpv" value={fallbackProvider} ariaLabel="Fallback AI provider" options={PROVIDER_OPTIONS} onChange={setFallbackProvider} />
                    </div>
                    <div className="field">
                      <label htmlFor="fmd">Fallback Model ID</label>
                      <TextField id="fmd" code value={fallbackModel} onChange={setFallbackModel} placeholder={fallbackProvider === "ollama" ? "llama3.2" : fallbackProvider === "openai_compatible" ? "gpt-4o-mini" : "gemini-2.5-flash"} maxLength={120} />
                    </div>
                  </div>
                  {(fallbackProvider === "ollama" || fallbackProvider === "openai_compatible") && (
                    <div className="field" style={{ marginTop: 10 }}>
                      <label htmlFor="fburl">Fallback Base URL</label>
                      <TextField id="fburl" code value={fallbackBaseUrl} onChange={setFallbackBaseUrl} placeholder={fallbackProvider === "ollama" ? "http://localhost:11434/v1" : "https://api.openai.com/v1"} maxLength={200} />
                    </div>
                  )}
                  <div className="field" style={{ marginTop: 10 }}>
                    <label htmlFor="fky">{a?.fallback_key_last4 ? "Replace Fallback API key" : "Fallback API key"}</label>
                    <input id="fky" className="input code" type="password" autoComplete="off" value={fallbackKey} onChange={(e) => setFallbackKey(e.target.value)} placeholder={fallbackProvider === "ollama" ? "Optional for local Ollama" : "Paste fallback API key"} />
                  </div>
                </div>
              )}
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
            <div className="set-row"><div>Quiet hours<small>Silence non-urgent notifications during scheduled hours. Urgent mail still delivers.</small></div>
              <Toggle on={s.quiet_hours_enabled ?? false} label="Quiet hours" onChange={(v) => change({ quiet_hours_enabled: v })} /></div>
            {s.quiet_hours_enabled && (
              <div className="set-row"><div>Quiet window<small>Start and end times in your timezone ({s.timezone})</small></div>
                <div className="inline" style={{ gap: 8 }}>
                  <input type="time" className="input" style={{ width: 120 }} value={s.quiet_hours_start ?? "22:00"}
                    onChange={(e) => change({ quiet_hours_start: e.target.value })} />
                  <span className="dim">to</span>
                  <input type="time" className="input" style={{ width: 120 }} value={s.quiet_hours_end ?? "07:00"}
                    onChange={(e) => change({ quiet_hours_end: e.target.value })} />
                </div></div>
            )}
            <div className="set-row" style={{ alignItems: "flex-start" }}><div>Mute notification categories<small>Silence non-urgent notifications for selected categories</small></div>
              <div className="inline" style={{ flexWrap: "wrap", gap: 6, maxWidth: 420 }}>
                {Object.entries(CATEGORY_LABELS).map(([catKey, label]) => {
                  const muted = (s.muted_categories ?? []).includes(catKey);
                  return (
                    <button key={catKey} type="button" className={`chip ${muted ? "on" : ""}`} onClick={() => {
                      const next = muted
                        ? (s.muted_categories ?? []).filter((c) => c !== catKey)
                        : [...(s.muted_categories ?? []), catKey];
                      change({ muted_categories: next });
                    }}>
                      {label}
                    </button>
                  );
                })}
              </div></div>
            <div className="set-row"><div>Time zone<small>For rule time windows and deadlines</small></div><span className="muted">{s.timezone}</span></div>
          </div>
        )}

        <div className="settings-sec"><h2>Mail</h2>
          {s && (
            <div className="set-row"><div>Load images in mail automatically<small>They come through your Sift server, so senders never see your address. Off: images stay blocked until you press "Load images".</small></div>
              <Toggle on={s.load_remote_images} label="Load images automatically" onChange={(v) => change({ load_remote_images: v })} /></div>
          )}
          {grouping.data && (
            <div className="set-row"><div>Group similar emails<small>Display only. Urgent mail keeps its own row; notifications don't change.</small></div>
              <Toggle on={grouping.data.grouping_enabled === "yes"} label="Group similar emails" onChange={async (v) => {
                try { grouping.setData(await post<GroupingStatus>("/grouping", { answer: v ? "yes" : "no" })); } catch (e) { toast(errorText(e)); }
              }} /></div>
          )}
        </div>

        {s && <WritingSettings s={s} change={change} accounts={accounts.data ?? []} />}

        <div className="settings-sec"><h2>Data</h2>
          <div className="set-row"><div>Export folders, rules, tags, categories &amp; settings<small>One JSON file. No mail, tokens or keys.</small></div>
            <button className="btn btn-ghost btn-sm" onClick={exportBackup} data-tip="Download folders, rules, tags, categories and settings as JSON. No mail or keys">Export</button></div>
          <SavedOnDevice />
          <div className="set-row"><div>Import a backup<small>Adds to what you have; never deletes. Rules for accounts that aren't connected come in switched off.</small></div>
            <button className="btn btn-ghost btn-sm" onClick={() => fileInput.current?.click()} data-tip="Add folders, rules and settings from a Sift backup file">Import…</button>
            <input ref={fileInput} type="file" accept="application/json,.json" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) importBackup(f); e.target.value = ""; }} /></div>
        </div>
      </section>
    </>
  );
}

/** Name shown to recipients, signature added to new mail, and the undo window after Send. */
function WritingSettings({ s, change, accounts }: { s: Settings; change: (c: Partial<Settings>) => void; accounts: Account[] }) {
  const [selectedAccId, setSelectedAccId] = useState<string | null>(null);
  const [accSettings, setAccSettings] = useState<Settings | null>(null);
  const [name, setName] = useState<string | null>(null);
  const [sig, setSig] = useState<string | null>(null);

  useEffect(() => {
    setName(null);
    setSig(null);
    if (!selectedAccId) {
      setAccSettings(null);
      return;
    }
    get<Settings>("/settings", { account_id: selectedAccId })
      .then(setAccSettings)
      .catch((e) => toast(errorText(e)));
  }, [selectedAccId]);

  const activeSettings = selectedAccId ? (accSettings ?? s) : s;

  async function handleFieldChange(fieldChanges: Partial<Settings>) {
    if (!selectedAccId) {
      change(fieldChanges);
    } else {
      try {
        const updated = await patch<Settings>("/settings", fieldChanges, { account_id: selectedAccId });
        setAccSettings(updated);
      } catch (e) {
        toast(errorText(e));
      }
    }
  }

  return (
    <div className="settings-sec"><h2>Writing mail</h2>
      {accounts.length > 0 && (
        <div className="set-row"><div>Profile for<small>Customize name and signature per account, or set defaults for all</small></div>
          <div className="inline" style={{ flexWrap: "wrap", gap: 6 }}>
            <button type="button" className={`chip ${selectedAccId === null ? "on" : ""}`} onClick={() => setSelectedAccId(null)}>
              All accounts (default)
            </button>
            {accounts.map((a) => (
              <button type="button" key={a.id} className={`chip ${selectedAccId === a.id ? "on" : ""}`} onClick={() => setSelectedAccId(a.id)}>
                {a.email}
              </button>
            ))}
          </div></div>
      )}
      <div className="set-row"><div>Your name<small>Shown to people you write to, next to your address</small></div>
        <div style={{ width: 280 }}><TextField value={name ?? activeSettings.sender_name} onChange={setName} maxLength={100} ariaLabel="Your name" placeholder={selectedAccId ? (s.sender_name || "e.g. Asha Rao") : "e.g. Asha Rao"}
          onBlur={() => { if (name !== null && name.trim() !== activeSettings.sender_name) handleFieldChange({ sender_name: name.trim() }); setName(null); }} /></div></div>
      <div className="set-row" style={{ alignItems: "flex-start" }}><div>Signature<small>Added below new mail, replies and forwards. Plain text.</small></div>
        <textarea className="input" style={{ width: 280, minHeight: 90, resize: "vertical" }} value={sig ?? activeSettings.signature} maxLength={2000} aria-label="Signature"
          placeholder={selectedAccId ? (s.signature || "Default signature…") : ""}
          onChange={(e) => setSig(e.target.value)} onBlur={() => { if (sig !== null && sig !== activeSettings.signature) handleFieldChange({ signature: sig }); setSig(null); }} /></div>
      <div className="set-row"><div>Undo send<small>How long you can take a mail back after pressing Send</small></div>
        <div className="inline">{[0, 5, 10, 20, 30].map((n) => (
          <button key={n} className={`chip ${s.undo_send_seconds === n ? "on" : ""}`} onClick={() => change({ undo_send_seconds: n })}>{n ? `${n} s` : "Off"}</button>
        ))}</div></div>
    </div>
  );
}

/** What this browser keeps so Sift opens while the server is off (offline.ts, public/sw.js). */
function SavedOnDevice() {
  const [size, setSize] = useState<{ bytes: number; entries: number } | null>(null);
  const measure = () => savedSize().then(setSize).catch(() => setSize({ bytes: 0, entries: 0 }));
  useEffect(() => { measure(); }, []);
  const mb = size ? (size.bytes / 1048576 < 0.1 ? `${Math.max(1, Math.round(size.bytes / 1024))} KB` : `${(size.bytes / 1048576).toFixed(1)} MB`) : "…";
  return (
    <div className="set-row"><div>Saved on this device<small>Mail and pages you already opened, so Sift still opens when the server is off. {size ? `${mb} · ${size.entries} items` : "Measuring…"}</small></div>
      <button className="btn btn-ghost btn-sm" disabled={!size?.entries} data-tip="Delete the saved copies from this browser. Nothing changes on the server or in Gmail" onClick={async () => {
        if (!(await confirmDialog({ title: "Clear saved mail on this device?", body: "Sift will load everything from the server again. Nothing changes in Gmail or on the server.", confirm: "Clear" }))) return;
        await clearSaved();
        toast("Cleared what this device saved");
        measure();
      }}>Clear</button></div>
  );
}

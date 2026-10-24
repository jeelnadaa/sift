import { get, type AiStatus, type Usage } from "../api";
import { Top } from "../App";
import { Banner, useLoad } from "../components";

export function UsagePage() {
  const usage = useLoad(() => get<Usage>("/usage", { days: 30 }));
  const ai = useLoad(() => get<AiStatus>("/ai"));
  const u = usage.data;
  const totals = (u?.days ?? []).map((d) => d.input_tokens + d.output_tokens);
  const max = Math.max(1, ...totals);
  const calls = u?.days.reduce((s, d) => s + d.calls, 0) ?? 0;
  const today = u?.days.find((d) => d.day === new Date().toISOString().slice(0, 10));
  const pct = u && u.daily_token_cap ? Math.min(100, Math.round((u.tokens_today / u.daily_token_cap) * 100)) : 0;
  const fmt = (n: number) => n.toLocaleString();

  return (
    <>
      <Top title="Token usage" />
      <section className="page">
        {usage.error && <Banner tone="err">{usage.error}</Banner>}
        {ai.data && !ai.data.ai_enabled && <Banner tone="warn">AI is off: no valid key. Sift spends no tokens; rules, folders and notifications all keep working.</Banner>}
        <div className="grid4" style={{ marginBottom: 16 }}>
          <div className="card kpi"><b className="mono">{fmt(u?.tokens_today ?? 0)}</b><span>tokens today</span></div>
          <div className="card kpi"><b className="mono">{fmt(today?.calls ?? 0)}</b><span>AI calls today</span></div>
          <div className="card kpi"><b className="mono">{fmt(calls)}</b><span>AI calls, last 30 days</span></div>
          <div className="card kpi"><b className="mono">{fmt(totals.reduce((a, b) => a + b, 0))}</b><span>tokens, last 30 days</span></div>
        </div>
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="inline" style={{ justifyContent: "space-between", marginBottom: 10 }}><b>Daily cap</b><span className="mono muted">{fmt(u?.tokens_today ?? 0)} / {fmt(u?.daily_token_cap ?? 0)}</span></div>
          <div className="bar" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}><i style={{ width: `${pct}%`, background: pct > 85 ? "var(--warn)" : undefined }} /></div>
          <p className="dim" style={{ fontSize: 13, marginTop: 8 }}>At the cap Sift stops calling the AI until tomorrow and delivers mail as normal priority. Change the cap in Settings.</p>
        </div>
        <div className="card"><b>Last 30 days</b>
          {u && u.days.length === 0 ? <p className="dim" style={{ marginTop: 10 }}>No AI calls yet.</p> : (
            <div className="spark" style={{ height: 120, marginTop: 16 }}>
              {u?.days.map((d, i) => <span key={d.day} className={i === u.days.length - 1 ? "hi" : ""} style={{ height: `${Math.max(3, (totals[i] / max) * 100)}%` }} title={`${d.day}: ${fmt(totals[i])} tokens, ${d.calls} calls`} />)}
            </div>
          )}
        </div>
      </section>
    </>
  );
}

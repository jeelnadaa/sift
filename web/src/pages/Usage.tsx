import { get, type AiStatus, type Usage } from "../api";
import { Top } from "../App";
import { Banner, useLoad } from "../components";

export function UsagePage() {
  const usage = useLoad(() => get<Usage>("/usage", { days: 30 }));
  const ai = useLoad(() => get<AiStatus>("/ai"));
  const u = usage.data;
  // Always 30 slots ending today, so one busy day is one bar, not a full-width block.
  const byDay = new Map((u?.days ?? []).map((d) => [d.day, d]));
  const end = u?.days.length ? new Date(u.days[u.days.length - 1].day + "T00:00:00") : new Date();
  const slots = Array.from({ length: 30 }, (_, i) => {
    const d = new Date(end);
    d.setDate(end.getDate() - (29 - i));
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const row = byDay.get(key);
    return { key, date: d, tokens: row ? row.input_tokens + row.output_tokens : 0, input: row?.input_tokens ?? 0, output: row?.output_tokens ?? 0, calls: row?.calls ?? 0 };
  });
  const totals = slots.map((s) => s.tokens);
  const max = Math.max(1, ...totals);
  const calls = u?.days.reduce((s, d) => s + d.calls, 0) ?? 0;
  const today = slots[slots.length - 1];
  const label = (d: Date) => d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  const pct = u && u.daily_token_cap ? Math.min(100, Math.round((u.tokens_today / u.daily_token_cap) * 100)) : 0;
  const fmt = (n: number) => n.toLocaleString();

  return (
    <>
      <Top title="Token usage" />
      <section className="page">
        {usage.error && <Banner tone="err">{usage.error}</Banner>}
        {ai.data && !ai.data.ai_enabled && <Banner tone="warn">AI is off: no valid key. Sift spends no tokens; rules, folders and notifications all keep working.</Banner>}
        <div className="grid4" style={{ marginBottom: 16 }}>
          <div className="card kpi" data-tip="Input plus output tokens your key spent today"><b className="mono">{fmt(u?.tokens_today ?? 0)}</b><span>tokens today</span></div>
          <div className="card kpi" data-tip="Mails sent to your AI key today"><b className="mono">{fmt(today?.calls ?? 0)}</b><span>AI calls today</span></div>
          <div className="card kpi" data-tip="Mails sent to your AI key in the last 30 days"><b className="mono">{fmt(calls)}</b><span>AI calls, last 30 days</span></div>
          <div className="card kpi" data-tip="Tokens your key spent in the last 30 days"><b className="mono">{fmt(totals.reduce((a, b) => a + b, 0))}</b><span>tokens, last 30 days</span></div>
        </div>
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="inline" style={{ justifyContent: "space-between", marginBottom: 10 }}><b>Daily cap</b><span className="mono muted">{fmt(u?.tokens_today ?? 0)} / {fmt(u?.daily_token_cap ?? 0)}</span></div>
          <div className="bar" data-tip={`${pct}% of today's cap used`} role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}><i style={{ width: `${pct}%`, background: pct > 85 ? "var(--warn)" : undefined }} /></div>
          <p className="dim" style={{ fontSize: 13, marginTop: 8 }}>At the cap Sift stops calling the AI until tomorrow and delivers mail as normal priority. Change the cap in Settings.</p>
        </div>
        <div className="card"><b>Last 30 days</b>
          {u && u.days.length === 0 ? <p className="dim" style={{ marginTop: 10 }}>No AI calls yet.</p> : (
            <>
              <div className="usage-chart" role="img" aria-label={`Tokens per day for the last 30 days; most: ${fmt(max)}`}>
                {slots.map((s, i) => (
                  <span key={s.key} className={`${s.tokens ? "on" : ""} ${i === slots.length - 1 ? "hi" : ""}`}
                    style={{ height: s.tokens ? `${Math.max(4, (s.tokens / max) * 100)}%` : undefined }}
                    data-tip={s.tokens
                      ? `${label(s.date)}${i === slots.length - 1 ? " (today)" : ""}\n${fmt(s.tokens)} tokens · ${s.calls} AI call${s.calls === 1 ? "" : "s"}\n${fmt(s.input)} in, ${fmt(s.output)} out` + (u?.daily_token_cap ? `\n${Math.round((s.tokens / u.daily_token_cap) * 100)}% of the daily cap` : "")
                      : `${label(s.date)}: no AI use`} />
                ))}
              </div>
              <div className="usage-axis"><span>{label(slots[0].date)}</span><span>{label(slots[14].date)}</span><span>Today</span></div>
            </>
          )}
        </div>
      </section>
    </>
  );
}

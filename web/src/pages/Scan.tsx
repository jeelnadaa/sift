import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { get, post, type Account, type Scan } from "../api";
import { Top } from "../App";
import { Banner, Modal, errorText, toast, useLoad } from "../components";
import { humanize } from "../util";

const CHOICES: [string, string, string][] = [
  ["keep", "Keep", "No rule: Sift decides as usual"],
  ["notify_urgent", "Urgent", "Always notify right away, re-sent until your phone confirms"],
  ["notify_normal", "Normal", "Always notify once"],
  ["digest", "Digest", "Quiet notification (security mail still notifies)"],
  ["silent", "Silent", "Stored and searchable, never notified (security mail still notifies)"],
];
const CHOICE_LABEL = Object.fromEntries(CHOICES.map(([k, l]) => [k, l]));

/** First scan: last 30 days of headers only, no bodies, no AI. One action per sender, applied in bulk. */
export function ScanPage() {
  const [params, setParams] = useSearchParams();
  const accounts = useLoad(() => get<Account[]>("/accounts"));
  const accountId = params.get("account") ?? accounts.data?.[0]?.id ?? null;
  const scan = useLoad(async () => (accountId ? get<Scan | null>(`/accounts/${accountId}/scan`) : null), [accountId]);
  const [choice, setChoice] = useState<Record<string, string>>({});
  const [confirming, setConfirming] = useState(false);
  const s = scan.data;

  useEffect(() => {
    if (s?.status === "done") setChoice(Object.fromEntries(s.senders.map((x) => [x.key, x.suggested])));
    if (s && (s.status === "queued" || s.status === "running")) {
      const t = setTimeout(scan.reload, 2000);
      return () => clearTimeout(t);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s?.id, s?.status, s?.scanned]);

  async function start() {
    try { await post(`/accounts/${accountId}/scan`); scan.reload(); } catch (e) { toast(errorText(e)); }
  }
  async function apply() {
    const assignments = Object.fromEntries(Object.entries(choice).filter(([, v]) => v !== "keep"));
    try {
      const r = await post<{ rules: unknown[] }>(`/scans/${s!.id}/apply`, { assignments });
      toast(`${r.rules.length} rule(s) made. Security mail is always kept.`);
      scan.reload();
    } catch (e) { toast(errorText(e)); }
  }
  const changed = Object.values(choice).filter((v) => v !== "keep").length;
  const byAction = Object.entries(Object.values(choice).filter((v) => v !== "keep")
    .reduce<Record<string, number>>((acc, v) => ({ ...acc, [v]: (acc[v] ?? 0) + 1 }), {}));

  return (
    <>
      <Top title="Onboarding scan">{accountId && <button className="btn btn-ghost btn-sm" onClick={start} data-tip="Read the last 30 days of headers again (no bodies, no AI)">{s ? "Scan again" : "Start scan"}</button>}</Top>
      <section className="page">
        <p className="lede">Last 30 days, headers only. No bodies, no AI. Pick an action per sender; Sift makes the rules, always keeping security mail.</p>
        {(accounts.data?.length ?? 0) > 1 && (
          <div className="tabs">
            {accounts.data!.map((a) => <button key={a.id} className={`chip ${a.id === accountId ? "on" : ""}`} onClick={() => setParams({ account: a.id })}>{a.label || a.email}</button>)}
          </div>
        )}
        {accounts.data?.length === 0 && <Banner tone="warn">Connect a Gmail account first, under Accounts.</Banner>}
        {scan.error && <Banner tone="err">{scan.error}</Banner>}
        {s?.status === "failed" && <Banner tone="err">The scan failed: {s.error}</Banner>}
        {s && (s.status === "queued" || s.status === "running") && <Banner tone="ok">Scanning… {s.scanned} mails so far.</Banner>}
        {s?.applied_at && <Banner tone="ok">Applied. You can scan again any time.</Banner>}
        {!s && accountId && !scan.loading && <div className="card dim">No scan yet for this account. <a className="link" onClick={start} data-tip="Scan the last 30 days of headers (no bodies, no AI)">Start one</a>.</div>}
        {s?.status === "done" && (
          <>
            <div className="list"><table>
              <thead><tr><th>Sender</th><th>Mails</th><th>Hints</th><th>Action</th></tr></thead>
              <tbody>
                {s.senders.map((x) => (
                  <tr key={x.key}>
                    <td><b>{x.name || x.key}</b><div className="dim" style={{ fontSize: 12.5 }}>{x.key}{x.sample_subject ? ` · ${x.sample_subject}` : ""}</div></td>
                    <td className="mono">{x.count}</td>
                    <td className="dim" style={{ fontSize: 13 }}>{x.hints.map(humanize).join(", ") || "—"}</td>
                    <td><div className="inline">{CHOICES.map(([k, label, tip]) => (
                      <button key={k} className={`chip ${choice[x.key] === k ? "on" : ""}`} onClick={() => setChoice({ ...choice, [x.key]: k })}
                        data-tip={`${tip}${x.suggested === k ? "\nSift's suggestion" : ""}`}>{label}</button>
                    ))}</div></td>
                  </tr>
                ))}
              </tbody>
            </table></div>
            <div style={{ marginTop: 20 }}><button className="btn btn-primary" disabled={!changed} onClick={() => setConfirming(true)}
              data-tip={changed ? `Makes one rule per action you picked, listing those senders (${changed} senders). Senders left on Keep get no rule.` : "Pick an action other than Keep for at least one sender"}>
              Apply to {changed} sender{changed === 1 ? "" : "s"}</button>
              <span className="dim" style={{ fontSize: 13, marginLeft: 12 }}>Sift pre-picked an action from each sender's Gmail tab (Promotions: Silent, Social: Digest). Change any before applying.</span></div>
          </>
        )}
      </section>
      {confirming && (
        <Modal title={`Make ${byAction.length} rule${byAction.length === 1 ? "" : "s"} for ${changed} sender${changed === 1 ? "" : "s"}?`} onClose={() => setConfirming(false)} foot={<>
          <button className="btn btn-ghost btn-sm" onClick={() => setConfirming(false)}>Cancel</button>
          <button className="btn btn-primary btn-sm" onClick={() => { setConfirming(false); apply(); }}>Make the rules</button></>}>
          <p className="muted">Sift adds one rule per action, listing its senders (matched on the verified sender), for new mail from now on. Mail you already have isn't changed, and you can edit or delete each rule under Rules.</p>
          <div className="inline" style={{ margin: "12px 0" }}>{byAction.map(([a, n]) => <span key={a} className="tag">{CHOICE_LABEL[a]}: {n} sender{n === 1 ? "" : "s"}</span>)}</div>
          <p className="dim" style={{ fontSize: 13 }}>Silent and Digest rules always keep security mail (fraud, OTP, password, blocked card) notifying. Senders left on Keep get no rule.</p>
        </Modal>
      )}
    </>
  );
}

import { useNavigate } from "react-router-dom";
import { del, get, type Account } from "../api";
import { Top } from "../App";
import { Banner, Tag, errorText, toast, useLoad } from "../components";
import { accountColor, fullTime, safeUrl } from "../util";

const STATUS: Record<Account["status"], [string, string]> = { active: ["Active", "ok"], needs_reconnect: ["Needs reconnect", "urgent"], blocked: ["Blocked", "warn"] };

export function Accounts() {
  const navigate = useNavigate();
  const accounts = useLoad(() => get<Account[]>("/accounts"));

  async function connect(hint?: string) {
    try {
      const r = await get<{ auth_url: string }>("/accounts/connect-url", { login_hint: hint });
      const u = safeUrl(r.auth_url);
      if (u) location.assign(u);  // Google's consent page; it comes back to the server's callback
    } catch (e) { toast(errorText(e)); }
  }
  async function remove(a: Account) {
    if (!confirm(`Remove ${a.email}? This stops its watch, deletes its tokens and deletes its stored mail from Sift. Gmail itself is untouched.`)) return;
    try { await del(`/accounts/${a.id}`); accounts.reload(); toast("Account removed"); } catch (e) { toast(errorText(e)); }
  }

  return (
    <>
      <Top title="Accounts"><button className="btn btn-primary btn-sm" onClick={() => connect()}>+ Add Gmail account</button></Top>
      <section className="page">
        {accounts.error && <Banner tone="err">{accounts.error}</Banner>}
        <div className="grid2">
          {accounts.data?.map((a) => {
            const [label, tone] = STATUS[a.status];
            return (
              <div key={a.id} className="card" style={a.status !== "active" ? { borderColor: tone === "urgent" ? "rgba(255,90,60,.4)" : "rgba(255,185,56,.4)" } : undefined}>
                <div className="inline"><span className="acct"><i style={{ background: accountColor(a.color, a.id) }} /></span><b>{a.email}</b><span className="spacer" /><Tag tone={tone}>{label}</Tag></div>
                <div className="muted" style={{ marginTop: 10, fontSize: 13.5 }}>
                  {a.status === "blocked" ? "This account may be blocked by its administrator (common for college and work accounts). Other accounts keep working."
                    : a.status === "needs_reconnect" ? "Sift lost access to this account. Reconnect it; other accounts are fine."
                    : a.watch_expires_at ? `Instant push · watch renews by ${fullTime(a.watch_expires_at)}` : "Checked every few seconds"}
                </div>
                <div className="inline" style={{ marginTop: 16 }}>
                  {a.status !== "active" && <button className="btn btn-primary btn-sm" onClick={() => connect(a.email)}>Reconnect</button>}
                  {a.status === "active" && <button className="btn btn-ghost btn-sm" onClick={() => navigate(`/scan?account=${a.id}`)}>First scan</button>}
                  <button className="btn btn-danger btn-sm" onClick={() => remove(a)}>Remove</button>
                </div>
              </div>
            );
          })}
        </div>
        {accounts.data?.length === 0 && <div className="card dim">No Gmail account connected yet.</div>}
        <p className="dim" style={{ marginTop: 14, fontSize: 13 }}>Sift asks Google for read-only access. Removing an account stops its watch, deletes its tokens and deletes its stored mail.</p>
      </section>
    </>
  );
}

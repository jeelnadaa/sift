import { useNavigate } from "react-router-dom";
import { del, get, type Account } from "../api";
import { Top } from "../App";
import { Banner, confirmDialog, errorText, Tag, toast, useLoad } from "../components";
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
  async function allowChanges(a: Account) {
    try {
      const r = await get<{ auth_url: string }>(`/accounts/${a.id}/write-access-url`);
      const u = safeUrl(r.auth_url);
      if (u) location.assign(u);
    } catch (e) { toast(errorText(e)); }
  }
  async function remove(a: Account) {
    if (!(await confirmDialog({ title: `Remove ${a.email}?`, confirm: "Remove account", danger: true,
      body: "Sift stops watching it, deletes its tokens and deletes its stored mail, filing and timelines from Sift. Gmail itself is untouched, and you can connect it again later." }))) return;
    try { await del(`/accounts/${a.id}`); accounts.reload(); toast("Account removed"); } catch (e) { toast(errorText(e)); }
  }

  return (
    <>
      <Top title="Accounts"><button className="btn btn-primary btn-sm" onClick={() => connect()} data-tip="Connect another Gmail account (read-only access)">+ Add Gmail account</button></Top>
      <section className="page">
        {accounts.error && <Banner tone="err">{accounts.error}</Banner>}
        <div className="grid2">
          {accounts.data?.map((a) => {
            const [label, tone] = STATUS[a.status];
            return (
              <div key={a.id} className="card" style={a.status !== "active" ? { borderColor: tone === "urgent" ? "rgba(255,90,60,.4)" : "rgba(255,185,56,.4)" } : undefined}>
                <div className="inline"><span className="acct" data-tip="This account's color in lists"><i style={{ background: accountColor(a.color, a.id) }} /></span><b>{a.email}</b><span className="spacer" /><Tag tone={tone} tip={a.status === "active" ? "Sift is receiving this account's mail" : a.status === "blocked" ? "Google says the account's administrator may block Sift" : "Sift lost access; reconnect to resume"}>{label}</Tag></div>
                <div className="muted" style={{ marginTop: 10, fontSize: 13.5 }}>
                  {a.status === "blocked" ? "This account may be blocked by its administrator (common for college and work accounts). Other accounts keep working."
                    : a.status === "needs_reconnect" ? "Sift lost access to this account. Reconnect it; other accounts are fine."
                    : a.watch_expires_at ? `Instant push · watch renews by ${fullTime(a.watch_expires_at)}` : "Checked every few seconds"}
                </div>
                {a.status === "active" && (
                  <div style={{ marginTop: 8 }}>
                    {a.can_modify
                      ? <Tag tone="ok" tip="Sift can archive, label, mark read, star and snooze here. It never sends or deletes mail on its own.">Can change mail</Tag>
                      : <Tag tip="Sift only reads this account. Archive, labels and read state ask for permission the first time.">Read-only</Tag>}
                  </div>
                )}
                <div className="inline" style={{ marginTop: 16 }}>
                  {a.status !== "active" && <button className="btn btn-primary btn-sm" onClick={() => connect(a.email)} data-tip="Sign in to Google again to restore access">Reconnect</button>}
                  {a.status === "active" && !a.can_modify && <button className="btn btn-ghost btn-sm" onClick={() => allowChanges(a)} data-tip="Let Sift archive, label, mark read, star and snooze mail in this account. Google asks once.">Allow changes</button>}
                  {a.status === "active" && <button className="btn btn-ghost btn-sm" onClick={() => navigate(`/scan?account=${a.id}`)} data-tip="List this account's top senders from the last 30 days and set them in bulk">First scan</button>}
                  <button className="btn btn-danger btn-sm" onClick={() => remove(a)} data-tip="Remove from Sift: stops its watch, deletes its tokens and its stored mail. Gmail is untouched">Remove</button>
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

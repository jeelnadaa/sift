import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { get, post, type Account, type Group, type GroupingStatus, type Mail, type Page } from "../api";
import { Top } from "../App";
import { Banner, GroupRow, MailRow, Modal, Pager, useLoad, usePages } from "../components";
import { accountColor } from "../util";

const PAGE_SIZE = 30;
const PROMPTED_KEY = "sift.groupingPrompted";  // once per browser session; the server counts to 3

export function Feed() {
  const navigate = useNavigate();
  const [account, setAccount] = useState<string | null>(null);
  const [priority, setPriority] = useState<string | null>(null);
  const [ask, setAsk] = useState(false);
  const accounts = useLoad(() => get<Account[]>("/accounts"));
  const grouping = useLoad(() => get<GroupingStatus>("/grouping"));
  const grouped = grouping.data?.grouping_enabled === "yes";
  const feed = usePages((before) => get<Page<Mail | Group>>("/messages", { account_id: account, priority, grouped: grouped || undefined, before, limit: PAGE_SIZE }),
    [account, priority, grouped]);

  useEffect(() => {
    let prompted = false;
    try { prompted = sessionStorage.getItem(PROMPTED_KEY) === "1"; } catch { /* ignore */ }
    if (grouping.data?.should_ask && !prompted) {
      setAsk(true);
      try { sessionStorage.setItem(PROMPTED_KEY, "1"); } catch { /* ignore */ }
    }
  }, [grouping.data]);

  async function answer(a: "yes" | "no" | "dismissed") {
    setAsk(false);
    await post("/grouping", { answer: a }).catch(() => {});
    grouping.reload();
  }

  const trouble = (accounts.data ?? []).filter((a) => a.status !== "active");
  const items = feed.data?.items ?? [];
  return (
    <>
      <Top title="Feed" />
      <section className="page">
        {(accounts.data ?? []).filter((a) => a.status === "active" && a.stalled).map((a) => {
          const since = a.check_failing_since ?? a.last_check_ok_at;
          return (
            <Banner key={"s" + a.id} tone="err" action="Details" onAction={() => navigate("/accounts")}>
              Sift hasn't been able to check <b>{a.email}</b>{since ? ` since ${new Date(since).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}` : ""}{a.last_check_error ? ` (${a.last_check_error})` : ""}. It keeps retrying and catches up on its own; you'll be notified when it's back.
            </Banner>
          );
        })}
        {trouble.map((a) => (
          <Banner key={a.id} tone={a.status === "blocked" ? "warn" : "err"} action="Open" onAction={() => navigate("/accounts")}>
            {a.status === "blocked" ? <><b>{a.email}</b> may be blocked by its administrator.</> : <><b>{a.email}</b> needs to reconnect. Other accounts are fine.</>}
          </Banner>
        ))}
        <div className="tabs">
          <button className={`chip ${account === null ? "on" : ""}`} onClick={() => setAccount(null)} data-tip="Mail from every connected account">All accounts</button>
          {(accounts.data ?? []).map((a) => (
            <button key={a.id} className={`chip ${account === a.id ? "on" : ""}`} onClick={() => setAccount(account === a.id ? null : a.id)} data-tip={account === a.id ? "Click again to show every account" : `Only mail to ${a.email}`}>
              <span className="acct"><i style={{ background: accountColor(a.color, a.id) }} />{a.label || a.email}</span>
            </button>
          ))}
          <button className="chip" onClick={() => navigate("/search?q=is%3Asnoozed")} data-tip="Conversations you snoozed; they come back on their own">Snoozed</button>
          <span className="spacer" />
          {(["urgent", "normal", "digest"] as const).map((p) => (
            <button key={p} className={`chip ${priority === p ? "on" : ""}`} onClick={() => setPriority(priority === p ? null : p)} data-tip={priority === p ? "Click again to show every priority" : `Only ${p} mail`}>
              <span className={`dot ${p}`} />{p.charAt(0).toUpperCase() + p.slice(1)}
            </button>
          ))}
        </div>
        {feed.error && <Banner tone="err" action="Retry" onAction={feed.reload}>{feed.error}</Banner>}
        {feed.data && <Pager page={feed.page} pages={feed.pages} total={feed.total} onPrev={feed.onPrev} onNext={feed.onNext} />}
        <div className="list">
          {!feed.loading && items.length === 0 && <div className="empty">{account || priority ? "No mail matches these filters." : "No mail yet. New mail shows up here within seconds."}</div>}
          {items.map((i, n) => i.type === "group"
            ? <GroupRow key={"g" + i.id} g={i} n={n + 1} onOpen={() => navigate(`/groups/${i.id}`)} />
            : <MailRow key={i.id} m={i as Mail} n={n + 1} onOpen={() => navigate(`/mail/${i.id}`)} />)}
        </div>
        {feed.data && <Pager bottom page={feed.page} pages={feed.pages} total={feed.total} onPrev={feed.onPrev} onNext={feed.onNext} />}
        <div className="dim" style={{ marginTop: 14, fontSize: 13 }}>
          {grouped ? "Priority mail is never hidden inside a group. Urgent mail always gets its own row." : "Drag a mail onto a folder in the sidebar to file it."}
        </div>
      </section>
      {ask && (
        <Modal title="Group similar emails together?" onClose={() => answer("dismissed")}
          foot={<><button className="btn btn-ghost btn-sm" onClick={() => answer("no")} data-tip="Don't group; Sift won't ask again">No</button><button className="btn btn-primary btn-sm" onClick={() => answer("yes")} data-tip="Group similar mail, starting with the last 30 days">Yes, group them</button></>}>
          <p className="muted">Grouping only changes how mail is displayed. Urgent mail still shows on its own and every notification still arrives. You can change this in Settings.</p>
        </Modal>
      )}
    </>
  );
}

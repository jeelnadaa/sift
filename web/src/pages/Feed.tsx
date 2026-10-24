import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { get, post, type Account, type Group, type GroupingStatus, type Mail, type Page } from "../api";
import { Top } from "../App";
import { Banner, GroupRow, MailRow, Modal, useLoad } from "../components";
import { accountColor } from "../util";

const PROMPTED_KEY = "sift.groupingPrompted";  // once per browser session; the server counts to 3

export function Feed() {
  const navigate = useNavigate();
  const [account, setAccount] = useState<string | null>(null);
  const [priority, setPriority] = useState<string | null>(null);
  const [more, setMore] = useState<(Mail | Group)[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [ask, setAsk] = useState(false);
  const accounts = useLoad(() => get<Account[]>("/accounts"));
  const grouping = useLoad(() => get<GroupingStatus>("/grouping"));
  const grouped = grouping.data?.grouping_enabled === "yes";
  const feed = useLoad(async () => {
    const page = await get<Page<Mail | Group>>("/messages", { account_id: account, priority, grouped: grouped || undefined });
    setMore([]);
    setNext(page.next_before);
    return page.items;
  }, [account, priority, grouped]);

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
  async function loadMore() {
    if (!next) return;
    const page = await get<Page<Mail | Group>>("/messages", { account_id: account, priority, grouped: grouped || undefined, before: next });
    setMore((m) => [...m, ...page.items]);
    setNext(page.next_before);
  }

  const trouble = (accounts.data ?? []).filter((a) => a.status !== "active");
  const items = [...(feed.data ?? []), ...more];
  return (
    <>
      <Top title="Feed" />
      <section className="page">
        {trouble.map((a) => (
          <Banner key={a.id} tone={a.status === "blocked" ? "warn" : "err"} action="Open" onAction={() => navigate("/accounts")}>
            {a.status === "blocked" ? <><b>{a.email}</b> may be blocked by its administrator.</> : <><b>{a.email}</b> needs to reconnect. Other accounts are fine.</>}
          </Banner>
        ))}
        <div className="tabs">
          <button className={`chip ${account === null ? "on" : ""}`} onClick={() => setAccount(null)}>All accounts</button>
          {(accounts.data ?? []).map((a) => (
            <button key={a.id} className={`chip ${account === a.id ? "on" : ""}`} onClick={() => setAccount(account === a.id ? null : a.id)}>
              <span className="acct"><i style={{ background: accountColor(a.color, a.id) }} />{a.label || a.email}</span>
            </button>
          ))}
          <span className="spacer" />
          {(["urgent", "normal", "digest"] as const).map((p) => (
            <button key={p} className={`chip ${priority === p ? "on" : ""}`} onClick={() => setPriority(priority === p ? null : p)}>
              <span className={`dot ${p}`} />{p.charAt(0).toUpperCase() + p.slice(1)}
            </button>
          ))}
        </div>
        {feed.error && <Banner tone="err" action="Retry" onAction={feed.reload}>{feed.error}</Banner>}
        <div className="list">
          {!feed.loading && items.length === 0 && <div className="empty">No mail yet. New mail shows up here within seconds.</div>}
          {items.map((i) => i.type === "group"
            ? <GroupRow key={"g" + i.id} g={i} onOpen={() => navigate(`/groups/${i.id}`)} />
            : <MailRow key={i.id} m={i as Mail} onOpen={() => navigate(`/mail/${i.id}`)} />)}
        </div>
        {next && <div style={{ marginTop: 14 }}><button className="btn btn-ghost btn-sm" onClick={loadMore}>Load older</button></div>}
        <div className="dim" style={{ marginTop: 14, fontSize: 13 }}>
          {grouped ? "Priority mail is never hidden inside a group. Urgent mail always gets its own row." : "Drag a mail onto a folder in the sidebar to file it."}
        </div>
      </section>
      {ask && (
        <Modal title="Group similar emails together?" onClose={() => answer("dismissed")}
          foot={<><button className="btn btn-ghost btn-sm" onClick={() => answer("no")}>No</button><button className="btn btn-primary btn-sm" onClick={() => answer("yes")}>Yes, group them</button></>}>
          <p className="muted">Grouping only changes how mail is displayed. Urgent mail still shows on its own and every notification still arrives. You can change this in Settings.</p>
        </Modal>
      )}
    </>
  );
}

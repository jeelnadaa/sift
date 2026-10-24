import { Fragment, useEffect, useState, type ReactNode } from "react";
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
import { get, post, session, setSignedOutHandler, type Account, type Folder } from "./api";
import { DialogHost, Icon, Toaster, TooltipLayer, errorText, toast } from "./components";
import { Login } from "./pages/Login";
import { Feed } from "./pages/Feed";
import { MailDetail } from "./pages/Mail";
import { SearchPage } from "./pages/Search";
import { Thread } from "./pages/Thread";
import { Todos } from "./pages/Todo";
import { Opportunities } from "./pages/Opportunities";
import { Groups, GroupDetail } from "./pages/Groups";
import { Folders } from "./pages/Folders";
import { Rules } from "./pages/Rules";
import { RuleEditor } from "./pages/RuleEditor";
import { Silenced } from "./pages/Silenced";
import { ScanPage } from "./pages/Scan";
import { Accounts } from "./pages/Accounts";
import { UsagePage } from "./pages/Usage";
import { SettingsPage } from "./pages/Settings";

const SIDEBAR_KEY = "sift.sidebar";

/** Fires when folders change, so the sidebar's drop targets refresh. */
export const foldersChanged = () => dispatchEvent(new Event("sift:folders"));

export function App() {
  const [signedIn, setSignedIn] = useState(() => !!session.token());
  const navigate = useNavigate();
  useEffect(() => setSignedOutHandler(() => { setSignedIn(false); navigate("/login"); }), [navigate]);

  return (
    <>
      <Routes>
        <Route path="/login" element={signedIn ? <Navigate to="/" replace /> : <Login onSignedIn={() => setSignedIn(true)} />} />
        <Route path="/*" element={signedIn ? <Shell onSignOut={() => { session.clear(); setSignedIn(false); }} /> : <Navigate to="/login" replace />} />
      </Routes>
      <Toaster />
      <TooltipLayer />
      <DialogHost />
    </>
  );
}

const NAV: { h: string; items: [string, string, string, string][] }[] = [
  { h: "Inbox", items: [
    ["/", "Feed", "feed", "All new mail from every account, newest first"],
    ["/todo", "To-do", "todo", "Mail that needs action, with deadlines and reminders"],
    ["/opportunities", "Opportunities", "opps", "One timeline per company: announcements, tests, interviews, results"],
    ["/groups", "Groups", "groups", "Similar mail stacked together (display only)"]] },
  { h: "Organize", items: [
    ["/folders", "Folders", "folder", "Your own nested folders. Drop mail on one to file it"],
    ["/search", "Search", "search", "Gmail syntax plus Sift filters, across every account, or by meaning  ( / )"]] },
  { h: "Control", items: [
    ["/rules", "Rules", "rules", "What gets silenced, digested, notified or filed"],
    ["/silenced", "Silenced", "mute", "Mail kept quiet by a rule: check here if a rule is too greedy"],
    ["/scan", "Onboarding scan", "scan", "Top senders of the last 30 days, set in bulk"]] },
  { h: "Account", items: [
    ["/accounts", "Accounts", "mail", "Connected Gmail accounts and their status"],
    ["/usage", "Token usage", "chart", "What your own AI key has spent"],
    ["/settings", "Settings", "gear", "AI key, notifications, grouping, backup"]] },
];

function Shell({ onSignOut }: { onSignOut: () => void }) {
  const narrow = typeof matchMedia !== "undefined" && matchMedia("(max-width: 1000px)").matches;
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem(SIDEBAR_KEY) === "1" || narrow; } catch { return narrow; } });
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [folders, setFolders] = useState<Folder[]>([]);
  const location = useLocation();
  const navigate = useNavigate();

  const toggle = () => setCollapsed((c) => { try { localStorage.setItem(SIDEBAR_KEY, c ? "0" : "1"); } catch { /* ignore */ } return !c; });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (/INPUT|TEXTAREA|SELECT/.test((e.target as HTMLElement).tagName)) return;
      if (e.key === "[") toggle();
      if (e.key === "/") { e.preventDefault(); navigate("/search"); setTimeout(() => (document.querySelector(".search-box textarea") as HTMLElement | null)?.focus(), 50); }
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => { get<Account[]>("/accounts").then(setAccounts).catch(() => {}); }, [location.pathname]);
  useEffect(() => {
    const load = () => get<{ folders: Folder[] }>("/folders").then((t) => setFolders(t.folders)).catch(() => {});
    load();
    addEventListener("sift:folders", load);
    return () => removeEventListener("sift:folders", load);
  }, []);
  const trouble = accounts.some((a) => a.status !== "active");
  const email = session.email() ?? "";

  return (
    <div className={`shell ${collapsed ? "collapsed" : ""}`}>
      <Icons />
      <aside>
        <div className="brand">
          <div className="logo"><b /><span>Sift</span></div>
          <button className="collapse" onClick={toggle} data-tip={collapsed ? "Expand sidebar  ( [ )" : "Collapse sidebar  ( [ )"} aria-label="Toggle sidebar"><Icon name="chev" /></button>
        </div>
        <nav className="nav">
          {NAV.map((g) => (
            <div className="nav-group" key={g.h}>
              <div className="nav-h">{g.h}</div>
              {g.items.map(([to, label, icon, tip]) => (
                <Fragment key={to}>
                  <NavLink to={to} end={to === "/"} data-tip={collapsed ? `${label}\n${tip}` : tip} aria-label={label} className={({ isActive }) => (isActive ? "on" : "")}>
                    <Icon name={icon} /><span className="lbl">{label}</span>
                    {to === "/accounts" && trouble && <><span className="ct u">!</span><i className="ct-dot" /></>}
                  </NavLink>
                  {/* top-level folders sit right under Folders, as drop targets for mail */}
                  {to === "/folders" && !collapsed && folders.slice(0, 8).map((f) => <SideFolder key={f.id} f={f} />)}
                </Fragment>
              ))}
            </div>
          ))}
        </nav>
        <div className="side-foot">
          <div className="avatar">{email.charAt(0).toUpperCase() || "S"}</div>
          <div className="who-t"><b>{email.split("@")[0]}</b><div className="dim" style={{ fontSize: 12 }}>{accounts.length} account{accounts.length === 1 ? "" : "s"} · <a className="link dim" onClick={onSignOut} data-tip="Sign out of this browser">Sign out</a></div></div>
        </div>
      </aside>
      <main>
        <Routes>
          <Route path="/" element={<Feed />} />
          <Route path="/mail/:id" element={<MailDetail />} />
          <Route path="/read/:accountId/:threadId" element={<ReadThread />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/todo" element={<Todos />} />
          <Route path="/opportunities" element={<Opportunities />} />
          <Route path="/opportunities/:id" element={<Opportunities />} />
          <Route path="/groups" element={<Groups />} />
          <Route path="/groups/:id" element={<GroupDetail />} />
          <Route path="/folders" element={<Folders />} />
          <Route path="/folders/:id" element={<Folders />} />
          <Route path="/rules" element={<Rules />} />
          <Route path="/rules/new" element={<RuleEditor />} />
          <Route path="/rules/:id" element={<RuleEditor />} />
          <Route path="/silenced" element={<Silenced />} />
          <Route path="/scan" element={<ScanPage />} />
          <Route path="/accounts" element={<Accounts />} />
          <Route path="/usage" element={<UsagePage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

/** A top-level folder in the sidebar: click to open, drop mail on it to file. */
function SideFolder({ f }: { f: Folder }) {
  const [over, setOver] = useState(false);
  const navigate = useNavigate();
  return (
    <a data-tip={`${f.name}${f.unread_total ? ` · ${f.unread_total} unread` : ""}\nDrop mail here to file it`} className={over ? "drop" : ""} style={{ paddingLeft: 42, fontSize: 13.5 }}
      onClick={() => navigate(`/folders/${f.id}`)}
      onDragOver={(e) => { if (e.dataTransfer.types.includes("application/x-sift-mail")) { e.preventDefault(); setOver(true); } }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); fileDropped(e.dataTransfer.getData("application/x-sift-mail"), f); }}>
      <span style={{ width: 8, height: 8, borderRadius: 3, background: f.color ?? "var(--text-3)", flex: "none" }} />
      <span className="lbl" style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{f.name}</span>
      {f.unread_total > 0 && <span className="ct">{f.unread_total}</span>}
    </a>
  );
}

export async function fileDropped(messageId: string, f: Folder) {
  if (!messageId) return;
  try {
    const r = await post<{ filed: number }>(`/folders/${f.id}/threads`, { message_ids: [messageId] });
    toast(r.filed ? `Filed in ${f.name}` : `Already in ${f.name}`);
    foldersChanged();
  } catch (e) {
    toast(errorText(e));
  }
}

/** Page header. `back` puts "‹ Back" above the title on the left (where the eye starts);
 * the page's actions sit in a row right under the title, never tucked in the far corner. */
export function Top({ title, children, back }: { title: string; children?: ReactNode; back?: boolean | string }) {
  const navigate = useNavigate();
  useEffect(() => { document.title = `${title} · Sift`; }, [title]);
  return (
    <div className="top">
      {back && <button className="back" onClick={() => (typeof back === "string" ? navigate(back) : navigate(-1))} data-tip="Back to where you were  (Alt + ←)">‹ Back</button>}
      <h1>{title}</h1>
      {children && <div className="actions">{children}</div>}
    </div>
  );
}

function Icons() {
  return (
    <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true"><defs>
      <symbol id="i-feed" viewBox="0 0 24 24"><path d="M3 13l2.5-7.5A2 2 0 017.4 4h9.2a2 2 0 011.9 1.5L21 13v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5z" /><path d="M3 13h5l1.5 2.5h5L16 13h5" /></symbol>
      <symbol id="i-todo" viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="3" /><path d="M8.5 12.5l2.5 2.5 4.5-5" /></symbol>
      <symbol id="i-opps" viewBox="0 0 24 24"><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z" /><path d="M12 12l8-4.5M12 12v9M12 12L4 7.5" /></symbol>
      <symbol id="i-groups" viewBox="0 0 24 24"><rect x="5" y="9" width="14" height="10" rx="2" /><path d="M7.5 6h9M10 3h4" /></symbol>
      <symbol id="i-search" viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5" /><path d="M16 16l4.5 4.5" /></symbol>
      <symbol id="i-folder" viewBox="0 0 24 24"><path d="M3 7a2 2 0 012-2h4l2 2.5h8a2 2 0 012 2V17a2 2 0 01-2 2H5a2 2 0 01-2-2z" /></symbol>
      <symbol id="i-rules" viewBox="0 0 24 24"><path d="M4 7h10M18 7h2M4 17h2M10 17h10" /><circle cx="16" cy="7" r="2" /><circle cx="8" cy="17" r="2" /></symbol>
      <symbol id="i-mute" viewBox="0 0 24 24"><path d="M6 9a6 6 0 0112 0c0 5 2 6 2 6H4s2-1 2-6z" /><path d="M10 19a2 2 0 004 0M4 4l16 16" /></symbol>
      <symbol id="i-scan" viewBox="0 0 24 24"><path d="M4 8V6a2 2 0 012-2h2M16 4h2a2 2 0 012 2v2M20 16v2a2 2 0 01-2 2h-2M8 20H6a2 2 0 01-2-2v-2M4 12h16" /></symbol>
      <symbol id="i-mail" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2.5" /><path d="M3.5 7l8.5 6 8.5-6" /></symbol>
      <symbol id="i-chart" viewBox="0 0 24 24"><path d="M5 20V11M12 20V5M19 20v-7" /></symbol>
      <symbol id="i-gear" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3" /><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8" /></symbol>
      <symbol id="i-chev" viewBox="0 0 24 24"><path d="M14.5 6l-6 6 6 6" /></symbol>
    </defs></svg>
  );
}

/** A conversation Sift never stored (older mail found by search), read straight from Gmail. */
function ReadThread() {
  const { accountId = "", threadId = "" } = useParams();
  return (
    <>
      <Top title="Conversation" back />
      <section className="page" style={{ maxWidth: 1000 }}>
        <p className="dim" style={{ fontSize: 13, marginBottom: 12 }}>Older mail Sift never processed, read straight from Gmail. Sift doesn't keep a copy.</p>
        <Thread accountId={accountId} threadId={threadId} />
      </section>
    </>
  );
}

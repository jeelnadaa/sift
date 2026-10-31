import { useEffect, useState } from "react";
import { Top } from "../App";
import { Link } from "react-router-dom";
import {
  get,
  type Account,
  type AttachmentItem,
  type AttachmentListResult,
  type AttachmentStats,
} from "../api";
import { Icon, useBusyWhile } from "../components";

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function formatDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();
  const diffDays = Math.floor((now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24));
  if (diffDays === 0) {
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  if (diffDays < 7) {
    return d.toLocaleDateString([], { weekday: "short" });
  }
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function getFileCategoryIcon(mime: string, filename: string): { icon: string; color: string } {
  const m = mime.toLowerCase();
  const f = filename.toLowerCase();
  if (m.includes("pdf") || f.endsWith(".pdf")) return { icon: "📄", color: "#f87171" };
  if (m.startsWith("image/") || /\.(png|jpe?g|gif|webp|svg)$/.test(f)) return { icon: "🖼️", color: "#38bdf8" };
  if (m.includes("spreadsheet") || m.includes("excel") || /\.(xlsx?|csv)$/.test(f)) return { icon: "📊", color: "#34d399" };
  if (m.includes("word") || m.includes("document") || /\.(docx?|txt|rtf)$/.test(f)) return { icon: "📝", color: "#818cf8" };
  if (m.includes("zip") || m.includes("compressed") || m.includes("tar") || /\.(zip|tar|gz|rar|7z)$/.test(f)) return { icon: "📦", color: "#fbbf24" };
  return { icon: "📎", color: "var(--text-3)" };
}

export function AttachmentsPage() {
  const [items, setItems] = useState<AttachmentItem[]>([]);
  const [stats, setStats] = useState<AttachmentStats | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [sizeFilter, setSizeFilter] = useState<number | null>(null);
  const [accountFilter, setAccountFilter] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(true);
  const [nextBefore, setNextBefore] = useState<string | null>(null);
  const [total, setTotal] = useState<number>(0);
  const [reloadTick, setReloadTick] = useState(0);

  // Load stats & accounts once
  useEffect(() => {
    void get<AttachmentStats>("/attachments/stats").then(setStats).catch(() => null);
    void get<Account[]>("/accounts").then(setAccounts).catch(() => null);
  }, []);

  // Fetch items whenever filters change
  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    const query: Record<string, unknown> = { limit: 30 };
    if (typeFilter !== "all") query.type = typeFilter;
    if (searchQuery.trim()) query.q = searchQuery.trim();
    if (sizeFilter !== null) query.min_size = sizeFilter;
    if (accountFilter) query.account_id = accountFilter;

    get<AttachmentListResult>("/attachments", query)
      .then((res) => {
        if (!cancelled) {
          setItems(res.items);
          setNextBefore(res.next_before);
          setTotal(res.total);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setItems([]);
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [typeFilter, searchQuery, sizeFilter, accountFilter, reloadTick]);
  useBusyWhile(loading && reloadTick > 0);
  useEffect(() => {  // the Refresh button
    const on = () => setReloadTick((t) => t + 1);
    addEventListener("sift:refresh", on);
    return () => removeEventListener("sift:refresh", on);
  }, []);

  const loadMore = async () => {
    if (!nextBefore || loading) return;
    setLoading(true);

    const query: Record<string, unknown> = { limit: 30, before: nextBefore };
    if (typeFilter !== "all") query.type = typeFilter;
    if (searchQuery.trim()) query.q = searchQuery.trim();
    if (sizeFilter !== null) query.min_size = sizeFilter;
    if (accountFilter) query.account_id = accountFilter;

    try {
      const res = await get<AttachmentListResult>("/attachments", query);
      setItems((prev) => [...prev, ...res.items]);
      setNextBefore(res.next_before);
      setTotal(res.total);
    } finally {
      setLoading(false);
    }
  };

  const typeTabs: { key: string; label: string; icon: string }[] = [
    { key: "all", label: "All", icon: "📎" },
    { key: "pdf", label: "PDFs", icon: "📄" },
    { key: "image", label: "Images", icon: "🖼️" },
    { key: "sheet", label: "Sheets", icon: "📊" },
    { key: "doc", label: "Docs", icon: "📝" },
    { key: "archive", label: "Archives", icon: "📦" },
  ];

  return (
    <>
    <Top title="Attachments" refresh />
    <section className="page">
      <div className="inline" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: 12, marginBottom: 16 }}>
        <p className="lede" style={{ margin: 0 }}>Every file in your mail, across all your accounts.</p>
        {stats && <div className="dim" style={{ fontSize: 13 }}><b className="mono" style={{ color: "var(--text)" }}>{stats.total_count}</b> files · <b className="mono" style={{ color: "var(--text)" }}>{formatBytes(stats.total_size)}</b></div>}
      </div>

      {/* Filter Chips Bar */}
      <div style={{ display: "flex", gap: 8, overflowX: "auto", paddingBottom: 6, marginBottom: 16 }}>
        {typeTabs.map((tab) => {
          const count = tab.key === "all" ? stats?.total_count : stats?.by_type?.[tab.key]?.count;
          const active = typeFilter === tab.key;
          return (
            <button key={tab.key} onClick={() => setTypeFilter(tab.key)} className={`chip ${active ? "on" : ""}`}>
              {tab.label}
              {typeof count === "number" && <span className="mono" style={{ opacity: 0.7, marginLeft: 6 }}>{count}</span>}
            </button>
          );
        })}
      </div>

      {/* Search and Secondary Controls */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 20 }}>
        <div style={{ flex: "1 1 240px", position: "relative" }}>
          <input
            type="search"
            placeholder="Search by filename, sender, subject…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{ width: "100%", paddingLeft: 34 }}
          />
          <span style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", opacity: 0.5 }}>
            <Icon name="search" />
          </span>
        </div>

        {/* Size Filter */}
        <select
          value={sizeFilter ?? ""}
          onChange={(e) => setSizeFilter(e.target.value ? Number(e.target.value) : null)}
          style={{ width: "auto" }}
        >
          <option value="">Any size</option>
          <option value="524288">&gt; 500 KB</option>
          <option value="1048576">&gt; 1 MB</option>
          <option value="5242880">&gt; 5 MB</option>
          <option value="10485760">&gt; 10 MB</option>
        </select>

        {/* Account Filter */}
        {accounts.length > 1 && (
          <select
            value={accountFilter}
            onChange={(e) => setAccountFilter(e.target.value)}
            style={{ width: "auto" }}
          >
            <option value="">All Accounts</option>
            {accounts.map((acc) => (
              <option key={acc.id} value={acc.id}>
                {acc.label || acc.email}
              </option>
            ))}
          </select>
        )}
      </div>

      {/* Attachments List */}
      {items.length === 0 && !loading && (
        <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--text-3)" }}>
          <div style={{ fontSize: 36, marginBottom: 8 }}>📎</div>
          <div style={{ fontSize: 16, fontWeight: 500, color: "var(--text)" }}>No attachments found</div>
          <p style={{ margin: "6px 0 0 0", fontSize: 13 }}>
            {searchQuery || typeFilter !== "all" || sizeFilter
              ? "Try clearing your filters or search keywords."
              : "When you receive emails with files, they will appear here automatically."}
          </p>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {items.map((att) => {
          const { icon } = getFileCategoryIcon(att.mime, att.filename);
          return (
            <div
              key={att.id}
              className="card"
              style={{
                display: "flex",
                alignItems: "center",
                gap: 14,
                padding: "12px 16px",
                transition: "background 0.15s ease",
              }}
            >
              {/* File Icon */}
              <div
                style={{
                  fontSize: 24,
                  width: 42,
                  height: 42,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  background: "var(--surface-2)",
                  borderRadius: 8,
                  flexShrink: 0,
                }}
              >
                {icon}
              </div>

              {/* Main Info */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                  <a
                    href={att.download_url}
                    target="_blank"
                    rel="noreferrer"
                    style={{ fontWeight: 600, fontSize: 14, color: "var(--text)", textDecoration: "none" }}
                    className="hover-underline"
                    title={att.filename}
                  >
                    {att.filename}
                  </a>
                  <span className="dim" style={{ fontSize: 12 }}>
                    {formatBytes(att.size)}
                  </span>
                </div>

                <div className="dim" style={{ fontSize: 12, marginTop: 4, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                  <span>From: {att.sender_name || att.sender || "Unknown"}</span>
                  {att.subject && (
                    <>
                      <span>·</span>
                      <Link
                        to={`/mail/${att.message_id}`}
                        style={{ color: "var(--text-2)", textDecoration: "none" }}
                        className="hover-underline"
                        title={att.subject}
                      >
                        ✉️ {att.subject.length > 40 ? att.subject.slice(0, 40) + "…" : att.subject}
                      </Link>
                    </>
                  )}
                  {att.received_at && (
                    <>
                      <span>·</span>
                      <span>{formatDate(att.received_at)}</span>
                    </>
                  )}
                </div>
              </div>

              {/* Actions */}
              <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                <a
                  href={att.download_url}
                  download={att.filename}
                  className="btn btn-ghost btn-sm"
                  title="Download file"
                  style={{ textDecoration: "none" }}
                >
                  Download
                </a>
                <Link
                  to={`/mail/${att.message_id}`}
                  className="btn btn-ghost btn-sm"
                  title="View original mail"
                >
                  View Mail
                </Link>
              </div>
            </div>
          );
        })}
      </div>

      {/* Pagination / Load More */}
      {nextBefore && (
        <div style={{ textAlign: "center", marginTop: 24 }}>
          <button
            onClick={loadMore}
            disabled={loading}
            className="btn btn-ghost"
            style={{ minWidth: 140 }}
          >
            {loading ? "Loading…" : `Load more (${total - items.length} remaining)`}
          </button>
        </div>
      )}
    </section>
    </>
  );
}

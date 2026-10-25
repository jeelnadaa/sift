import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  get,
  type SenderDetailResult,
  type SenderItem,
  type SenderListResult,
} from "../api";
import { Avatar, Dot, Icon, Modal } from "../components";

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

export function SendersPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<SenderItem[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(true);
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [sortBy, setSortBy] = useState<string>("count");
  const [offset, setOffset] = useState<number>(0);
  const [selectedSender, setSelectedSender] = useState<string | null>(null);
  const [senderDetail, setSenderDetail] = useState<SenderDetailResult | null>(null);
  const [detailLoading, setDetailLoading] = useState<boolean>(false);

  const limit = 40;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    const query: Record<string, unknown> = {
      limit,
      offset,
      sort_by: sortBy,
    };
    if (searchQuery.trim()) query.q = searchQuery.trim();

    get<SenderListResult>("/senders", query)
      .then((res) => {
        if (!cancelled) {
          setItems(res.items);
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
  }, [searchQuery, sortBy, offset]);

  // Load sender detail when selected
  useEffect(() => {
    if (!selectedSender) {
      setSenderDetail(null);
      return;
    }
    setDetailLoading(true);
    get<SenderDetailResult>(`/senders/${encodeURIComponent(selectedSender)}`)
      .then(setSenderDetail)
      .catch(() => setSenderDetail(null))
      .finally(() => setDetailLoading(false));
  }, [selectedSender]);

  const sortTabs = [
    { key: "count", label: "📊 Volume" },
    { key: "recent", label: "🕒 Recent" },
    { key: "unread", label: "📬 Unread" },
    { key: "urgent", label: "🚨 Urgent" },
    { key: "name", label: "🔤 Name" },
  ];

  return (
    <div className="page" style={{ maxWidth: 960, margin: "0 auto", padding: "16px 20px" }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 12, marginBottom: 20 }}>
        <div>
          <h1 style={{ margin: "0 0 6px 0", fontSize: 24, fontWeight: 600 }}>Senders Directory</h1>
          <div className="dim" style={{ fontSize: 13 }}>
            Overview and statistics for all people and services contacting your inbox.
          </div>
        </div>

        <div className="card" style={{ padding: "6px 16px", textAlign: "center" }}>
          <div style={{ fontSize: 18, fontWeight: 600 }}>{total}</div>
          <div className="dim" style={{ fontSize: 11, textTransform: "uppercase" }}>Senders</div>
        </div>
      </div>

      {/* Search and Sort controls */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 16 }}>
        <div style={{ flex: "1 1 240px", position: "relative" }}>
          <input
            type="search"
            placeholder="Search by sender name, email address, or domain…"
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              setOffset(0);
            }}
            style={{ width: "100%", paddingLeft: 34 }}
          />
          <span style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", opacity: 0.5 }}>
            <Icon name="search" />
          </span>
        </div>

        {/* Sort Chips */}
        <div style={{ display: "flex", gap: 6, overflowX: "auto" }}>
          {sortTabs.map((t) => {
            const active = sortBy === t.key;
            return (
              <button
                key={t.key}
                onClick={() => {
                  setSortBy(t.key);
                  setOffset(0);
                }}
                className={`btn btn-sm ${active ? "btn-primary" : "btn-ghost"}`}
                style={{ borderRadius: 20, padding: "6px 12px", fontSize: 13 }}
              >
                {t.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Senders List */}
      {items.length === 0 && !loading && (
        <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--text-3)" }}>
          <div style={{ fontSize: 36, marginBottom: 8 }}>👥</div>
          <div style={{ fontSize: 16, fontWeight: 500, color: "var(--text)" }}>No senders found</div>
          <p style={{ margin: "6px 0 0 0", fontSize: 13 }}>
            {searchQuery ? "Try clearing your search term." : "Senders will appear as emails arrive in your accounts."}
          </p>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {items.map((s) => (
          <div
            key={s.email}
            className="card"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 14,
              padding: "12px 16px",
            }}
          >
            {/* Avatar */}
            <Avatar text={s.name || s.email} />

            {/* Sender Info */}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                <span
                  style={{ fontWeight: 600, fontSize: 14, color: "var(--text)", cursor: "pointer" }}
                  onClick={() => setSelectedSender(s.email)}
                  className="hover-underline"
                >
                  {s.name || s.email}
                </span>
                {s.name && (
                  <span className="dim" style={{ fontSize: 12 }}>
                    &lt;{s.email}&gt;
                  </span>
                )}
                {s.domain && (
                  <span
                    style={{
                      fontSize: 11,
                      background: "var(--bg-3)",
                      padding: "1px 6px",
                      borderRadius: 4,
                      color: "var(--text-3)",
                    }}
                  >
                    {s.domain}
                  </span>
                )}
              </div>

              {/* Sample Subject & Last activity */}
              <div className="dim" style={{ fontSize: 12, marginTop: 4, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                {s.sample_subject && (
                  <span title={s.sample_subject} style={{ maxWidth: 360, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    Latest: "{s.sample_subject}"
                  </span>
                )}
                {s.last_received_at && (
                  <>
                    <span>·</span>
                    <span>{formatDate(s.last_received_at)}</span>
                  </>
                )}
              </div>
            </div>

            {/* Metrics Badges */}
            <div style={{ display: "flex", gap: 6, alignItems: "center", flexShrink: 0 }}>
              <span
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  padding: "2px 8px",
                  borderRadius: 12,
                  background: "var(--bg-3)",
                  color: "var(--text)",
                }}
                title="Total emails"
              >
                {s.total_count} {s.total_count === 1 ? "mail" : "mails"}
              </span>

              {s.unread_count > 0 && (
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    padding: "2px 6px",
                    borderRadius: 10,
                    background: "rgba(56, 189, 248, 0.15)",
                    color: "#38bdf8",
                  }}
                  title="Unread emails"
                >
                  {s.unread_count} unread
                </span>
              )}

              {s.urgent_count > 0 && (
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    padding: "2px 6px",
                    borderRadius: 10,
                    background: "rgba(248, 113, 113, 0.15)",
                    color: "#f87171",
                  }}
                  title="Urgent emails"
                >
                  {s.urgent_count} urgent
                </span>
              )}
            </div>

            {/* Actions */}
            <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => setSelectedSender(s.email)}
                title="View sender activity"
              >
                Inspect
              </button>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => navigate(`/search?q=from:${encodeURIComponent(s.email)}`)}
                title="Search all messages from this sender"
              >
                Search
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Pagination Controls */}
      {total > limit && (
        <div style={{ display: "flex", justifyContent: "center", gap: 12, marginTop: 20, alignItems: "center" }}>
          <button
            className="btn btn-ghost btn-sm"
            disabled={offset === 0}
            onClick={() => setOffset((o) => Math.max(0, o - limit))}
          >
            ‹ Previous
          </button>
          <span className="dim" style={{ fontSize: 13 }}>
            {offset + 1}–{Math.min(offset + limit, total)} of {total}
          </span>
          <button
            className="btn btn-ghost btn-sm"
            disabled={offset + limit >= total}
            onClick={() => setOffset((o) => o + limit)}
          >
            Next ›
          </button>
        </div>
      )}

      {/* Sender Detail Modal */}
      {selectedSender && (
        <Modal
          title={senderDetail?.name || selectedSender}
          onClose={() => setSelectedSender(null)}
          foot={
            <div style={{ display: "flex", justifyContent: "space-between", width: "100%" }}>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  setSelectedSender(null);
                  navigate(`/rules/new`);
                }}
              >
                + Create Rule for Sender
              </button>
              <button
                className="btn btn-primary btn-sm"
                onClick={() => {
                  const s = selectedSender;
                  setSelectedSender(null);
                  navigate(`/search?q=from:${encodeURIComponent(s)}`);
                }}
              >
                Search All Mail
              </button>
            </div>
          }
        >
          {detailLoading || !senderDetail ? (
            <div style={{ padding: 24, textAlign: "center" }}>Loading sender details…</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              {/* Summary Stats */}
              <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                <div className="card" style={{ flex: 1, minWidth: 100, padding: "8px 12px", textAlign: "center" }}>
                  <div style={{ fontSize: 16, fontWeight: 600 }}>{senderDetail.total_count}</div>
                  <div className="dim" style={{ fontSize: 11, textTransform: "uppercase" }}>Total Mail</div>
                </div>
                <div className="card" style={{ flex: 1, minWidth: 100, padding: "8px 12px", textAlign: "center" }}>
                  <div style={{ fontSize: 16, fontWeight: 600 }}>{senderDetail.unread_count}</div>
                  <div className="dim" style={{ fontSize: 11, textTransform: "uppercase" }}>Unread</div>
                </div>
                <div className="card" style={{ flex: 1, minWidth: 100, padding: "8px 12px", textAlign: "center" }}>
                  <div style={{ fontSize: 16, fontWeight: 600 }}>{senderDetail.urgent_count}</div>
                  <div className="dim" style={{ fontSize: 11, textTransform: "uppercase" }}>Urgent</div>
                </div>
                <div className="card" style={{ flex: 1, minWidth: 100, padding: "8px 12px", textAlign: "center" }}>
                  <div style={{ fontSize: 16, fontWeight: 600 }}>{senderDetail.attachment_count}</div>
                  <div className="dim" style={{ fontSize: 11, textTransform: "uppercase" }}>With Files</div>
                </div>
              </div>

              {/* Rules affecting this sender */}
              {senderDetail.rules.length > 0 && (
                <div>
                  <div style={{ fontSize: 12, fontWeight: 600, textTransform: "uppercase", marginBottom: 6 }} className="dim">
                    Rules targeting this sender ({senderDetail.rules.length})
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {senderDetail.rules.map((r) => (
                      <div
                        key={r.id}
                        className="card"
                        style={{ padding: "6px 12px", display: "flex", justifyContent: "space-between", fontSize: 13 }}
                      >
                        <span style={{ fontWeight: 500 }}>{r.name}</span>
                        <span className="dim">Action: {r.action?.type || "custom"}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Recent Messages */}
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, textTransform: "uppercase", marginBottom: 6 }} className="dim">
                  Recent Messages ({senderDetail.recent_messages.length})
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 280, overflowY: "auto" }}>
                  {senderDetail.recent_messages.map((m) => (
                    <Link
                      key={m.id}
                      to={`/mail/${m.id}`}
                      onClick={() => setSelectedSender(null)}
                      className="card"
                      style={{
                        padding: "8px 12px",
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                        textDecoration: "none",
                        color: "var(--text)",
                      }}
                    >
                      <Dot tier={m.priority} />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: m.unread ? 600 : 400, fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {m.subject || "(no subject)"}
                        </div>
                        <div className="dim" style={{ fontSize: 11 }}>
                          {formatDate(m.received_at)} · {m.snippet || ""}
                        </div>
                      </div>
                      {m.has_attachment && <span title="Has attachment">📎</span>}
                    </Link>
                  ))}
                </div>
              </div>
            </div>
          )}
        </Modal>
      )}
    </div>
  );
}

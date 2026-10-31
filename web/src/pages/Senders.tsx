import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  del,
  get,
  post,
  type SenderDetailResult,
  type SenderItem,
  type SenderListResult,
} from "../api";
import { Avatar, Dot, Icon, Modal, Tag, errorText, toast, useBusyWhile } from "../components";
import { Top } from "../App";

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
  const [reloadTick, setReloadTick] = useState(0);

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
  }, [searchQuery, sortBy, offset, reloadTick]);
  useBusyWhile(loading && reloadTick > 0);
  useEffect(() => {  // the Refresh button
    const on = () => setReloadTick((t) => t + 1);
    addEventListener("sift:refresh", on);
    return () => removeEventListener("sift:refresh", on);
  }, []);

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
    { key: "count", label: "Volume" },
    { key: "recent", label: "Recent" },
    { key: "unread", label: "Unread" },
    { key: "urgent", label: "Urgent" },
    { key: "name", label: "Name" },
  ];

  return (
    <>
    <Top title="Senders" refresh />
    <section className="page">
      <div className="inline" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: 12, marginBottom: 16 }}>
        <p className="lede" style={{ margin: 0 }}>Everyone who writes to your accounts, with how much and how recently.</p>
        <div className="dim" style={{ fontSize: 13 }}><b className="mono" style={{ color: "var(--text)" }}>{total}</b> senders</div>
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
                className={`chip ${active ? "on" : ""}`}
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
                      background: "var(--surface-2)",
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
              <Tag tip="Mail from this sender">{`${s.total_count} ${s.total_count === 1 ? "mail" : "mails"}`}</Tag>

              {s.unread_count > 0 && (
                <Tag tone="normal" tip="Unread mail">{`${s.unread_count} unread`}</Tag>
              )}

              {s.urgent_count > 0 && (
                <Tag tone="urgent" tip="Urgent mail">{`${s.urgent_count} urgent`}</Tag>
              )}
            </div>

            {/* Actions */}
            <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
              <button
                type="button"
                className={`btn btn-sm ${s.is_vip ? "btn-primary" : "btn-ghost"}`}
                onClick={async (e) => {
                  e.stopPropagation();
                  try {
                    if (s.is_vip) {
                      await del(`/senders/${encodeURIComponent(s.email)}/vip`);
                      toast(`Removed ${s.name || s.email} from VIP`);
                    } else {
                      await post(`/senders/${encodeURIComponent(s.email)}/vip`);
                      toast(`Marked ${s.name || s.email} as VIP`);
                    }
                    setReloadTick((t) => t + 1);
                  } catch (err) {
                    toast(errorText(err));
                  }
                }}
                title={s.is_vip ? "VIP Sender (always urgent notifications). Click to remove." : "Mark as VIP sender (elevates new mail to urgent)"}
              >
                {s.is_vip ? "★ VIP" : "☆ VIP"}
              </button>
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
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  type="button"
                  className={`btn btn-sm ${senderDetail?.is_vip ? "btn-primary" : "btn-ghost"}`}
                  onClick={async () => {
                    if (!selectedSender) return;
                    try {
                      if (senderDetail?.is_vip) {
                        await del(`/senders/${encodeURIComponent(selectedSender)}/vip`);
                        setSenderDetail({ ...senderDetail, is_vip: false });
                        toast("Removed from VIP");
                      } else if (senderDetail) {
                        await post(`/senders/${encodeURIComponent(selectedSender)}/vip`);
                        setSenderDetail({ ...senderDetail, is_vip: true });
                        toast("Marked as VIP sender");
                      }
                      setReloadTick((t) => t + 1);
                    } catch (e) {
                      toast(errorText(e));
                    }
                  }}
                >
                  {senderDetail?.is_vip ? "★ VIP Sender" : "☆ Mark VIP"}
                </button>
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => {
                    setSelectedSender(null);
                    navigate(`/rules/new`);
                  }}
                >
                  + Rule
                </button>
              </div>
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
    </section>
    </>
  );
}

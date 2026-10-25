/** Typed client for the Sift API (same origin). The sign-in token lives in localStorage;
 * the page is served with a strict Content-Security-Policy (no inline or third-party
 * scripts), and mail text is only ever rendered as text, never as HTML. */

import * as offline from "./offline";

const TOKEN_KEY = "sift.token";
const EMAIL_KEY = "sift.email";

export class ApiError extends Error {
  /** `body` is the server's JSON error, e.g. {detail: {code: "needs_write_access", accounts: [...]}}. */
  constructor(public status: number, message: string, public body: unknown = null) { super(message); }
  get code(): string | null {
    const d = (this.body as { detail?: { code?: string } } | null)?.detail;
    return d && typeof d === "object" && typeof d.code === "string" ? d.code : null;
  }
}

export const session = {
  token: (): string | null => { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } },
  email: (): string | null => { try { return localStorage.getItem(EMAIL_KEY); } catch { return null; } },
  save(token: string, email: string) { try { localStorage.setItem(TOKEN_KEY, token); localStorage.setItem(EMAIL_KEY, email); } catch { /* private mode */ } },
  clear() { try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ } void offline.clearSaved(); },  // signing out leaves no mail behind
};

let onSignedOut: () => void = () => {};
export function setSignedOutHandler(fn: () => void) { onSignedOut = fn; }

function detail(body: unknown, status: number): string {
  const d = (body as { detail?: unknown })?.detail;
  if (typeof d === "string") return d.charAt(0).toUpperCase() + d.slice(1);
  if (d && typeof d === "object" && "message" in d && typeof (d as { message: unknown }).message === "string") return (d as { message: string }).message;
  if (Array.isArray(d) && d[0]?.msg) return `Please check what you entered (${d[0].loc?.slice(-1)[0] ?? "field"}: ${d[0].msg})`;
  if (status === 401) return "Signed out. Sign in again.";
  if (status === 404) return "Not found.";
  if (status === 503) return "The server isn't configured for this yet.";
  return `Server error (${status}).`;
}

export async function request<T>(method: string, path: string, body?: unknown, query?: Record<string, unknown>): Promise<T> {
  const url = new URL("/api/v1" + path, location.origin);
  for (const [k, v] of Object.entries(query ?? {})) if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
  const headers: Record<string, string> = {};
  const token = session.token();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const saveable = method === "GET" && offline.saveable(url.pathname);
  const fallback = async (): Promise<T> => {
    // the server is off (or the tunnel shows its error page): show what this device saved
    const saved = saveable ? await offline.recall<T>(session.email(), url.href) : null;
    if (saved) { offline.markOffline(saved.savedAt); return saved.data; }
    throw new ApiError(0, method === "GET" ? "Can't reach the Sift server, and this page isn't saved on this device yet." : "Can't reach the Sift server. Try again when it's back.");
  };
  let res: Response;
  try {
    res = await fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    return fallback();
  }
  // a 5xx that isn't Sift's own JSON error is a proxy saying the server is unreachable
  if (res.status >= 500 && !(res.headers.get("Content-Type") || "").includes("application/json")) return fallback();
  offline.markOnline();
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && path !== "/auth/login") { session.clear(); onSignedOut(); }
    throw new ApiError(res.status, detail(data, res.status), data);
  }
  if (saveable) void offline.remember(session.email(), url.href, data);
  return data as T;
}

export const get = <T,>(path: string, query?: Record<string, unknown>) => request<T>("GET", path, undefined, query);
export const post = <T,>(path: string, body?: unknown) => request<T>("POST", path, body ?? {});
export const put = <T,>(path: string, body: unknown) => request<T>("PUT", path, body);
export const patch = <T,>(path: string, body: unknown, query?: Record<string, unknown>) => request<T>("PATCH", path, body, query);
export const del = <T,>(path: string, query?: Record<string, unknown>) => request<T>("DELETE", path, undefined, query);

/** Sends a file as the raw request body (its type in Content-Type), e.g. a mail attachment. */
export async function upload<T>(path: string, file: File, query: Record<string, string>): Promise<T> {
  const url = new URL("/api/v1" + path, location.origin);
  for (const [k, v] of Object.entries(query)) url.searchParams.set(k, v);
  const headers: Record<string, string> = { "Content-Type": file.type || "application/octet-stream" };
  const token = session.token();
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try { res = await fetch(url, { method: "POST", headers, body: file }); } catch { throw new ApiError(0, "Can't reach the Sift server."); }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401) { session.clear(); onSignedOut(); }
    throw new ApiError(res.status, res.status === 413 ? "Attachments are limited to 25 MB in total." : detail(data, res.status), data);
  }
  return data as T;
}

// ---- types (mirror the API's JSON) ----

export type Priority = "urgent" | "normal" | "digest" | "silent";

export interface Link { url: string; label: string }

export interface MailNote {
  id: string;
  message_id: string;
  body: string;
  created_at: string;
  updated_at: string;
}

export interface AttachmentItem {
  id: string;
  message_id: string;
  account_id: string;
  filename: string;
  mime: string;
  size: number;
  sender: string | null;
  sender_name: string | null;
  subject: string | null;
  received_at: string | null;
  download_url: string;
}

export interface AttachmentTypeStat {
  count: number;
  size: number;
}

export interface AttachmentStats {
  total_count: number;
  total_size: number;
  by_type: Record<string, AttachmentTypeStat>;
}

export interface AttachmentListResult {
  items: AttachmentItem[];
  next_before: string | null;
  total: number;
}

export interface SenderItem {
  email: string;
  name: string | null;
  domain: string | null;
  total_count: number;
  unread_count: number;
  urgent_count: number;
  attachment_count: number;
  last_received_at: string | null;
  sample_subject: string | null;
}

export interface SenderListResult {
  items: SenderItem[];
  total: number;
  offset: number;
  limit: number;
}

export interface SenderMessageBrief {
  id: string;
  subject: string | null;
  snippet: string | null;
  received_at: string | null;
  priority: Priority | null;
  category: string | null;
  unread: boolean;
  has_attachment: boolean;
}

export interface SenderDetailResult extends SenderItem {
  recent_messages: SenderMessageBrief[];
  rules: { id: string; name: string; enabled: boolean; action: Action }[];
}

export interface Mail {
  type?: "mail";
  id: string; account_id: string; account: string | null; account_color: string | null;
  thread_id: string; sender: string | null; sender_name: string | null; subject: string | null; snippet: string | null;
  received_at: string | null; priority: Priority | null; category: string | null; status: string;
  has_attachment: boolean; pinned?: boolean; has_note?: boolean; notes_count?: number; unread: boolean; matched_rule_id: string | null; summary: string | null;
  company: string | null; platform: string | null; deadline: string | null; links: Link[]; action_needed: boolean;
  opportunity_id: string | null; todo_id: string | null; decided_by: string | null;
  notified_at?: string | null; delivered_at?: string | null;
  thread_count?: number; thread_unread?: number; starred?: boolean; in_inbox?: boolean;
  groups?: { id: string; title: string; custom: boolean }[];  // the groups it's in (mail detail only)
  notes?: MailNote[];
  can_unsubscribe?: boolean;
  unsubscribe_url?: string | null;
  unsubscribe_post?: boolean;
}

export interface UnsubscribeResult {
  status: "one_click_posted" | "url_available" | "mailto_available" | "http_error" | "request_failed";
  sender: string | null;
  sender_name: string | null;
  unsubscribe_url: string | null;
  unsubscribe_mailto: string | null;
  is_one_click: boolean;
  rule_created: boolean;
  error: string | null;
}

export interface Group {
  type: "group"; id: string; title: string; kind: string; muted: boolean; collapsed: boolean;
  count: number; unread: number; urgent: number; shown: boolean;
  latest_sender: string | null; latest_subject: string | null; received_at: string | null; account_ids: string[];
  items?: Mail[];
  custom?: boolean; query?: string | null; instruction?: string | null;  // your own groups and what new mail joins them
}

export interface Page<T> { items: T[]; next_before: string | null; grouped?: boolean; total: number; pages: number }

export interface Account { id: string; email: string; status: "active" | "needs_reconnect" | "blocked"; status_detail: string | null; label: string | null; color: string | null; watch_expires_at: string | null; can_modify: boolean;
  last_check_ok_at: string | null; check_failing_since: string | null; last_check_error: string | null; stalled: boolean }

export interface Folder {
  id: string; parent_id: string | null; name: string; color: string | null; icon: string | null; position: number;
  pinned: boolean; notify_mode: "default" | "always" | "mute"; smart: boolean; threads: number; unread: number; unread_total: number;
  ai_rule: { categories: string[]; timeline: boolean; query?: string; describe?: string } | null; auto_sort: "company" | "sender" | "ai" | null; auto_sort_instruction: string | null;
  children: Folder[];
}
export interface FolderTree { folders: Folder[]; max_depth: number; last_used_id: string | null }
export interface FolderView { folder: Folder; path: { id: string; name: string }[]; items: Mail[]; next_before: string | null; total: number; pages: number }

export interface Rule {
  id: string; name: string; position: number; enabled: boolean; conditions: Cond; action: Action; exceptions: Cond | null;
  account_scope: string[] | null; origin: string; hit_count: number; last_hit_at: string | null;
}
export type Cond = { all: Cond[] } | { any: Cond[] } | { not: Cond } | Leaf;
export interface Leaf { field: string; op?: string; value?: unknown }
export interface Action { type: string; folder_id?: string; category?: string; tag?: string; [k: string]: unknown }
export interface Draft { name: string; conditions: Cond; action: Action; exceptions: Cond | null; account_scope: string[] | null; notes?: string[] }
export interface Sample { id: string; sender: string | null; subject: string | null; received_at: string | null; priority: string | null; important: boolean }
export interface Preview { checked: number; matches: number; important_matches: number; samples: Sample[]; kept_by_exceptions: number; kept_samples: Sample[]; body_not_previewed: boolean }
export interface Suggestion { id: string; domain: string; template: string; count: number; sample_subject: string; sender: string; message_id: string }
export interface Category { id: string | null; name: string; definition: string | null; builtin: boolean }

export interface Opportunity { id: string; company: string; aliases: string[]; domains: string[]; status: string; deadline: string | null; events: number; last_kind: string | null; updated_at: string }
export interface TimelineEvent {
  id: string; kind: string; matched_by: string; occurred_at: string; deadline: string | null; links: Link[]; platform: string | null; summary: string | null;
  message_id: string | null; subject: string | null; sender_name: string | null; account: string | null;
  title: string | null; note: string | null; remind: boolean; manual: boolean;  // manual: a section added by hand
}
export interface OpportunityDetail extends Opportunity { timeline: TimelineEvent[] }

export interface Todo { id: string; title: string; notes: string | null; due_at: string | null; done: boolean; source: string; message_id: string | null; subject: string | null; sender_name: string | null; opportunity_id: string | null; company: string | null }

export interface ScanSender { key: string; kind: string; name: string | null; count: number; sample_subject: string | null; hints: string[]; suggested: string }
export interface Scan { id: string; account_id: string; status: string; scanned: number; senders: ScanSender[]; error: string | null; applied_at: string | null }

export interface Settings { timezone: string; daily_token_cap: number; resend_urgent: boolean; resend_after_minutes: number; resend_limit: number; grouping_enabled: string; load_remote_images: boolean;
  sender_name: string; signature: string; undo_send_seconds: number;
  quiet_hours_enabled: boolean; quiet_hours_start: string; quiet_hours_end: string; muted_categories: string[] }

// ---- writing mail (Phase 4) ----
export interface DraftAttachment { index: number; filename: string; mime: string; size: number }
export interface OutboxItem {
  id: string; account_id: string; account_email?: string | null; draft_id: string; thread_id: string | null; subject: string | null; recipients: string | null;
  send_at: string; later: boolean; follow_up_days: number | null; status: "scheduled" | "sending" | "sent" | "cancelled" | "failed"; error: string | null; sent_at: string | null;
}
export interface DraftData {
  account_id: string; account_email: string; draft_id: string; thread_id: string | null; version: string | null; to: string[]; cc: string[]; bcc: string[];
  subject: string; body: string; in_reply_to: string | null; references: string | null; attachments: DraftAttachment[];
  attachments_size: number; attachments_limit: number; outbox?: OutboxItem | null;
}
export interface DraftSummary { account_id: string; account_email: string; draft_id: string; thread_id: string | null; subject: string; to: string; snippet: string; updated_ms: number; outbox: OutboxItem | null }
export interface ReplyContext {
  account_id: string; account_email: string; mode: string; to: string[]; cc: string[]; subject: string; body: string;
  in_reply_to: string | null; references: string | null; thread_id: string | null; forward_gmail_id: string | null; attachments: { filename: string; mime: string; size: number }[];
}
export interface FollowUpItem { id: string; account_id: string; thread_id: string; subject: string | null; recipients: string | null; sent_at: string; due_at: string; status: "waiting" | "replied" | "reminded" | "cancelled" }
export interface AiStatus { ai_enabled: boolean; status: string; provider: string | null; model: string | null; key_last4: string | null; tokens_today: number; daily_token_cap: number; suggested_model: string | null }
export interface AiTask {
  id: string; folder_id: string | null; folder_name: string; kind: "timelines" | "todos" | "sort" | "fill"; include_subfolders: boolean; instruction: string | null;
  group_id?: string | null; query?: string | null; by_sift_ai?: boolean;
  status: "queued" | "running" | "done" | "stopped" | "failed"; total: number; done: number; changed: number; note: string | null; tokens: number;
  created_at: string; finished_at: string | null;
}
export interface Usage {
  days: { day: string; calls: number; input_tokens: number; output_tokens: number }[]; tokens_today: number; daily_token_cap: number;
  automatic: { purpose: string; label: string; calls: number; tokens: number }[]; tasks: AiTask[];
  sift_ai?: { tokens: number; calls: number; runs: { id: string; text: string; status: string; tokens: number; created_at: string }[] };
}
export interface GroupingStatus { grouping_enabled: "not_asked" | "yes" | "no"; prompts: number; should_ask: boolean }

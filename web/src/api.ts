/** Typed client for the Sift API (same origin). The sign-in token lives in localStorage;
 * the page is served with a strict Content-Security-Policy (no inline or third-party
 * scripts), and mail text is only ever rendered as text, never as HTML. */

const TOKEN_KEY = "sift.token";
const EMAIL_KEY = "sift.email";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export const session = {
  token: (): string | null => { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } },
  email: (): string | null => { try { return localStorage.getItem(EMAIL_KEY); } catch { return null; } },
  save(token: string, email: string) { try { localStorage.setItem(TOKEN_KEY, token); localStorage.setItem(EMAIL_KEY, email); } catch { /* private mode */ } },
  clear() { try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ } },
};

let onSignedOut: () => void = () => {};
export function setSignedOutHandler(fn: () => void) { onSignedOut = fn; }

function detail(body: unknown, status: number): string {
  const d = (body as { detail?: unknown })?.detail;
  if (typeof d === "string") return d.charAt(0).toUpperCase() + d.slice(1);
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
  let res: Response;
  try {
    res = await fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "Can't reach the Sift server.");
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && path !== "/auth/login") { session.clear(); onSignedOut(); }
    throw new ApiError(res.status, detail(data, res.status));
  }
  return data as T;
}

export const get = <T,>(path: string, query?: Record<string, unknown>) => request<T>("GET", path, undefined, query);
export const post = <T,>(path: string, body?: unknown) => request<T>("POST", path, body ?? {});
export const put = <T,>(path: string, body: unknown) => request<T>("PUT", path, body);
export const patch = <T,>(path: string, body: unknown) => request<T>("PATCH", path, body);
export const del = <T,>(path: string, query?: Record<string, unknown>) => request<T>("DELETE", path, undefined, query);

// ---- types (mirror the API's JSON) ----

export type Priority = "urgent" | "normal" | "digest" | "silent";

export interface Link { url: string; label: string }

export interface Mail {
  type?: "mail";
  id: string; account_id: string; account: string | null; account_color: string | null;
  thread_id: string; sender: string | null; sender_name: string | null; subject: string | null; snippet: string | null;
  received_at: string | null; priority: Priority | null; category: string | null; status: string;
  has_attachment: boolean; unread: boolean; matched_rule_id: string | null; summary: string | null;
  company: string | null; platform: string | null; deadline: string | null; links: Link[]; action_needed: boolean;
  opportunity_id: string | null; todo_id: string | null; decided_by: string | null;
  notified_at?: string | null; delivered_at?: string | null;
  thread_count?: number; thread_unread?: number;
}

export interface Group {
  type: "group"; id: string; title: string; kind: string; muted: boolean; collapsed: boolean;
  count: number; unread: number; urgent: number; shown: boolean;
  latest_sender: string | null; latest_subject: string | null; received_at: string | null; account_ids: string[];
  items?: Mail[];
}

export interface Page<T> { items: T[]; next_before: string | null; grouped?: boolean }

export interface Account { id: string; email: string; status: "active" | "needs_reconnect" | "blocked"; status_detail: string | null; label: string | null; color: string | null; watch_expires_at: string | null }

export interface Folder {
  id: string; parent_id: string | null; name: string; color: string | null; icon: string | null; position: number;
  pinned: boolean; notify_mode: "default" | "always" | "mute"; smart: boolean; threads: number; unread: number; unread_total: number;
  children: Folder[];
}
export interface FolderTree { folders: Folder[]; max_depth: number; last_used_id: string | null }
export interface FolderView { folder: Folder; path: { id: string; name: string }[]; items: Mail[]; next_before: string | null }

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
export interface TimelineEvent { id: string; kind: string; matched_by: string; occurred_at: string; deadline: string | null; links: Link[]; platform: string | null; summary: string | null; message_id: string | null; subject: string | null; sender_name: string | null; account: string | null }
export interface OpportunityDetail extends Opportunity { timeline: TimelineEvent[] }

export interface Todo { id: string; title: string; notes: string | null; due_at: string | null; done: boolean; source: string; message_id: string | null; subject: string | null; sender_name: string | null; opportunity_id: string | null; company: string | null }

export interface ScanSender { key: string; kind: string; name: string | null; count: number; sample_subject: string | null; hints: string[]; suggested: string }
export interface Scan { id: string; account_id: string; status: string; scanned: number; senders: ScanSender[]; error: string | null; applied_at: string | null }

export interface Settings { timezone: string; daily_token_cap: number; resend_urgent: boolean; resend_after_minutes: number; resend_limit: number; grouping_enabled: string }
export interface AiStatus { ai_enabled: boolean; status: string; provider: string | null; model: string | null; key_last4: string | null; tokens_today: number; daily_token_cap: number; suggested_model: string | null }
export interface Usage { days: { day: string; calls: number; input_tokens: number; output_tokens: number }[]; tokens_today: number; daily_token_cap: number }
export interface GroupingStatus { grouping_enabled: "not_asked" | "yes" | "no"; prompts: number; should_ask: boolean }

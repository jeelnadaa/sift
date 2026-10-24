import type { Folder } from "./api";

/** "assessment_link" -> "Assessment link". Pills never show snake_case (DESIGN.md). */
export function humanize(v: string | null | undefined): string {
  if (!v) return "";
  const s = v.replace(/_/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function relativeTime(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "";
  const t = new Date(iso);
  if (isNaN(t.getTime())) return "";
  const mins = Math.floor((now.getTime() - t.getTime()) / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  if (mins < 24 * 60) return `${Math.floor(mins / 60)}h`;
  if (mins < 7 * 24 * 60) return `${Math.floor(mins / 1440)}d`;
  return t.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export function fullTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const t = new Date(iso);
  return isNaN(t.getTime()) ? "" : t.toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

/** Only http(s) links from mail are ever opened. */
export function safeUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.toString() : null;
  } catch {
    return null;
  }
}

export const ACCOUNT_COLORS = ["var(--acc-1)", "var(--acc-2)", "var(--acc-3)", "var(--acc-4)"];

export function accountColor(hex: string | null | undefined, key: string): string {
  if (hex && /^#[0-9a-f]{6}$/i.test(hex)) return hex;
  let h = 0;
  for (const c of key) h = (h * 31 + c.charCodeAt(0)) | 0;
  return ACCOUNT_COLORS[Math.abs(h) % ACCOUNT_COLORS.length];
}

export const FOLDER_COLORS = ["#c8ff3d", "#6ea8ff", "#b79cff", "#ff8a5b", "#4ad6c4", "#f6d365", "#ff6fae"];

/** Depth-first (folder, depth) list; children follow their parent. `open` limits to expanded folders. */
export function flatten(folders: Folder[], open?: Set<string>, depth = 0): [Folder, number][] {
  return folders.flatMap((f): [Folder, number][] => [
    [f, depth],
    ...(open === undefined || open.has(f.id) ? flatten(f.children, open, depth + 1) : []),
  ]);
}

export function subtreeIds(f: Folder): Set<string> {
  const out = new Set<string>([f.id]);
  for (const c of f.children) for (const id of subtreeIds(c)) out.add(id);
  return out;
}

export function findFolder(folders: Folder[], id: string | null | undefined): Folder | undefined {
  if (!id) return undefined;
  return flatten(folders).find(([f]) => f.id === id)?.[0];
}

export const PRIORITY_LABEL: Record<string, string> = { urgent: "Urgent", normal: "Normal", digest: "Digest", silent: "Silent" };

export const ACTION_LABELS: [string, string][] = [
  ["notify_urgent", "Notify urgent"], ["notify_normal", "Notify normal"], ["digest", "Digest"],
  ["silent", "Store silently"], ["ignore", "Ignore"], ["llm", "Classify as usual"],
];
export const actionLabel = (t: string) => ACTION_LABELS.find(([k]) => k === t)?.[1] ?? humanize(t);
export const actionTier = (t: string) => ({ notify_urgent: "urgent", notify_normal: "normal", llm: "normal", digest: "digest" } as Record<string, string>)[t] ?? "";

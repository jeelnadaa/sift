/** Saved copies of what this browser already loaded, so Sift still opens when the server is off.
 *
 * Every successful GET from the API is kept in the browser's Cache Storage, in a cache of its own
 * per signed-in account ("sift-data:<email>"); when the server can't be reached the last copy is
 * shown instead and the app says it is offline (event "sift:offline", banner in the shell).
 * Changes (send, archive, edit...) still need the server. The service worker (public/sw.js) keeps
 * the app itself and the mail you opened. Settings > "Saved on this device" shows the size and
 * clears it all; signing out clears it too. Nothing here holds tokens or keys. */

const PREFIX = "sift-data:";
const SKIP = [/^\/api\/v1\/auth\//, /^\/api\/v1\/events/];

let offlineSince: number | null = null;
const memCache = new Map<string, { data: unknown; savedAt: number }>();

function cacheName(email: string | null) { return PREFIX + (email || "anon").toLowerCase(); }
const supported = () => typeof caches !== "undefined";

export function saveable(path: string) { return supported() && !SKIP.some((r) => r.test(path)); }

/** Synchronous in-memory peek for instant cache-first rendering */
export function peek<T>(url: string): T | null {
  const hit = memCache.get(url);
  return hit ? (hit.data as T) : null;
}

// the reader documents' own policy (backend reader.RENDER_CSP), for copies served from the cache
const RENDER_CSP = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; font-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'self'";
const READ_CACHE = "sift-read-v1";  // shared with public/sw.js

interface DocMessage { html_url?: string | null; doc?: string }
export function hasDocs(data: unknown): boolean {
  const ms = (data as { messages?: DocMessage[] } | null)?.messages;
  return Array.isArray(ms) && ms.some((m) => typeof m?.doc === "string");
}

/** A conversation fetched with bundle=true carries each message's reader document. Each one is put
 * in the service worker's reader cache under its link (so the mail frame opens without asking the
 * server), and the saved conversation keeps only the links. */
async function storeDocs(data: unknown): Promise<unknown> {
  if (!hasDocs(data)) return data;
  const d = data as { messages: DocMessage[] };
  if (supported()) {
    try {
      const c = await caches.open(READ_CACHE);
      await Promise.all(d.messages.filter((m) => m.doc && m.html_url).map((m) => c.put(new URL(m.html_url!, location.origin).href,
        new Response(m.doc, { headers: { "Content-Type": "text/html; charset=utf-8", "Content-Security-Policy": RENDER_CSP, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer" } }))));
    } catch { /* best-effort */ }
  }
  return { ...d, messages: d.messages.map(({ doc: _doc, ...m }) => m) };
}

export async function remember(email: string | null, url: string, data: unknown): Promise<void> {
  data = await storeDocs(data);
  memCache.set(url, { data, savedAt: Date.now() });
  if (!supported()) return;
  try {
    const c = await caches.open(cacheName(email));
    await c.put(url, new Response(JSON.stringify(data), { headers: { "Content-Type": "application/json", "X-Saved-At": String(Date.now()) } }));
  } catch { /* storage full or blocked: saving is best-effort */ }
}

/** When this device last saved `url` (0 when it hasn't). */
export async function savedAt(email: string | null, url: string): Promise<number> {
  const hitMem = memCache.get(url);
  if (hitMem) return hitMem.savedAt;
  if (!supported()) return 0;
  try {
    const hit = await (await caches.open(cacheName(email))).match(url);
    return hit ? Number(hit.headers.get("X-Saved-At") || 0) : 0;
  } catch { return 0; }
}

export async function recall<T>(email: string | null, url: string): Promise<{ data: T; savedAt: number } | null> {
  const hitMem = memCache.get(url);
  if (hitMem) return { data: hitMem.data as T, savedAt: hitMem.savedAt };
  if (!supported()) return null;
  try {
    const hit = await (await caches.open(cacheName(email))).match(url);
    if (!hit) return null;
    const data = (await hit.json()) as T;
    const savedAt = Number(hit.headers.get("X-Saved-At") || 0);
    memCache.set(url, { data, savedAt });
    return { data, savedAt };
  } catch { return null; }
}

/** The server answered: leave offline mode. */
export function markOnline() {
  if (offlineSince === null) return;
  offlineSince = null;
  dispatchEvent(new CustomEvent("sift:offline", { detail: null }));
}

/** A page was served from the saved copy taken at `savedAt`. */
export function markOffline(savedAt: number) {
  if (offlineSince === null) offlineSince = savedAt;
  else offlineSince = Math.min(offlineSince, savedAt);
  dispatchEvent(new CustomEvent("sift:offline", { detail: { savedAt: offlineSince } }));
}

export const isOffline = () => offlineSince !== null;

/** Total size of everything saved on this device for Sift (data, the app, mail you opened). */
export async function savedSize(): Promise<{ bytes: number; entries: number }> {
  let bytes = 0, entries = 0;
  if (!supported()) return { bytes, entries };
  for (const name of await caches.keys()) {
    if (!name.startsWith("sift-")) continue;
    const c = await caches.open(name);
    for (const req of await c.keys()) {
      const res = await c.match(req);
      if (!res) continue;
      entries++;
      const len = Number(res.headers.get("Content-Length") || 0);
      bytes += len || (await res.clone().blob()).size;
    }
  }
  return { bytes, entries };
}

/** Clears saved mail and data for every account on this device. The app itself stays cached
 * (it holds no mail) unless `everything` is set. */
export async function clearSaved(everything = false): Promise<void> {
  memCache.clear();
  if (!supported()) return;
  for (const name of await caches.keys()) {
    if (name.startsWith(PREFIX) || name.startsWith("sift-read") || (everything && name.startsWith("sift-"))) await caches.delete(name);
  }
  navigator.serviceWorker?.controller?.postMessage("clear-read");
}

export function registerServiceWorker() {
  if (!("serviceWorker" in navigator) || location.protocol === "http:" && location.hostname !== "localhost" && location.hostname !== "127.0.0.1") return;
  navigator.serviceWorker.register("/app/sw.js", { scope: "/app/" }).catch(() => { /* offline mode is a bonus, never a blocker */ });
}

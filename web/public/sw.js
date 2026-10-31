/* Sift's service worker: the app keeps opening when the server is off (the laptop is shut, the
 * tunnel shows an error page). It only stores the app itself and the mail pages you opened:
 *  - the app's page and its hashed build files (fonts, script, styles);
 *  - mail you read or that was downloaded ahead (the sanitized reader pages and their images, under
 *    /api/v1/render, /img, /reader-fonts), so it opens at once and offline. The app itself puts the
 *    reader documents that come with a conversation (bundle) in the same cache (src/offline.ts).
 * JSON data (feed, timelines, to-dos...) is saved per account by the app itself (src/offline.ts).
 * The app's page is network-first; build files and mail pages are cache-first: a reader link names
 * one mail with one images choice, and a mail's content never changes. A 5xx (the tunnel's
 * "origin unreachable") counts as offline. Settings > "Saved on this device" clears it all. */
const SHELL = "sift-shell-v1";
const READ = "sift-read-v1";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    const keep = new Set([SHELL, READ]);
    for (const k of await caches.keys()) if (k.startsWith("sift-") && !k.startsWith("sift-data") && !keep.has(k)) await caches.delete(k);
    await self.clients.claim();
  })());
});

async function networkFirst(req, cacheName, key) {
  const cache = await caches.open(cacheName);
  try {
    const res = await fetch(req);
    if (res.status >= 500) throw new Error("server unreachable");
    if (res.ok) await cache.put(key || req, res.clone());
    return res;
  } catch (err) {
    const hit = await cache.match(key || req);
    if (hit) return hit;
    throw err;
  }
}

const READ_MAX = 1500;  // reader pages and pictures kept; the oldest go first

async function cacheFirst(req, cacheName = SHELL) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) {
    await cache.put(req, res.clone());
    if (cacheName === READ) trim(cache);
  }
  return res;
}

async function trim(cache) {
  const keys = await cache.keys();  // in the order they were added
  for (const k of keys.slice(0, Math.max(0, keys.length - READ_MAX))) await cache.delete(k);
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  const p = url.pathname;
  if (p.startsWith("/app/assets/")) {
    e.respondWith(cacheFirst(req));
  } else if (req.mode === "navigate" && p.startsWith("/app")) {
    // every client route is the same page: keep one copy of it
    e.respondWith(networkFirst(req, SHELL, "/app/"));
  } else if (p === "/app/favicon.svg") {
    e.respondWith(networkFirst(req, SHELL));
  } else if (p.startsWith("/api/v1/render/") || p.startsWith("/api/v1/img") || p.startsWith("/api/v1/reader-fonts/")) {
    e.respondWith(cacheFirst(req, READ));
  }
});

self.addEventListener("message", (e) => {
  if (e.data === "clear-read") e.waitUntil(caches.delete(READ));
});

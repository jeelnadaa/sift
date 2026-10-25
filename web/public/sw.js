/* Sift's service worker: the app keeps opening when the server is off (the laptop is shut, the
 * tunnel shows an error page). It only stores the app itself and the mail pages you opened:
 *  - the app's page and its hashed build files (fonts, script, styles);
 *  - mail you read (the sanitized reader pages and their images, under /api/v1/render, /img,
 *    /reader-fonts), so it can be read again offline.
 * JSON data (feed, timelines, to-dos...) is saved per account by the app itself (src/offline.ts).
 * Everything here is network-first except the immutable build files; a 5xx (the tunnel's
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

async function cacheFirst(req) {
  const cache = await caches.open(SHELL);
  const hit = await cache.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) await cache.put(req, res.clone());
  return res;
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
    e.respondWith(networkFirst(req, READ));
  }
});

self.addEventListener("message", (e) => {
  if (e.data === "clear-read") e.waitUntil(caches.delete(READ));
});

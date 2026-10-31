/** Downloads the newest feed mails ahead of time (owner, 2026-10-31: the newest 100), so opening
 * one shows it at once, even on a slow connection or with the server off.
 *
 * For each mail: its details (`/messages/{id}`) and its conversation with the reader documents
 * inline (`thread?bundle=true`, the exact request the mail page makes). `api.request` saves both;
 * offline.ts puts each document in the service worker's reader cache. Two at a time, in idle
 * time, only while the tab is visible and online; mail saved in the last few hours is skipped;
 * the "save data" browser setting turns it off. */
import { get, session } from "./api";
import * as offline from "./offline";

export const NEWEST = 100;
const FRESH_MS = 6 * 3600 * 1000;
const PARALLEL = 2;

const queue: string[] = [];
const queued = new Set<string>();
let running = 0;

function allowed(): boolean {
  const conn = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
  return document.visibilityState === "visible" && navigator.onLine && !offline.isOffline() && !conn?.saveData;
}

type IdleWindow = { requestIdleCallback?: (f: () => void, o?: { timeout: number }) => number };
const idle = (fn: () => void) => {
  const ric = (window as unknown as IdleWindow).requestIdleCallback;
  if (ric) ric.call(window, fn, { timeout: 3000 }); else setTimeout(fn, 200);
};

async function one(id: string): Promise<void> {
  const threadUrl = new URL(`/api/v1/messages/${id}/thread?bundle=true`, location.origin).href;
  if (Date.now() - (await offline.savedAt(session.email(), threadUrl)) < FRESH_MS) return;
  await get(`/messages/${id}`).catch(() => {});
  await get(`/messages/${id}/thread`, { bundle: true }).catch(() => {});
}

function pump() {
  while (running < PARALLEL && queue.length && allowed()) {
    const id = queue.shift()!;
    running++;
    idle(() => { void one(id).finally(() => { running--; queued.delete(id); pump(); }); });
  }
}

/** Queue mail ids (newest first); ones already queued or saved recently are skipped. */
export function prefetchMails(ids: string[]) {
  for (const id of ids.slice(0, NEWEST)) {
    if (queued.has(id)) continue;
    queued.add(id);
    queue.push(id);
  }
  pump();
}

if (typeof document !== "undefined") document.addEventListener("visibilitychange", pump);

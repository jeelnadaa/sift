/** Live updates from the server (GET /api/v1/events, server-sent events read with fetch so the
 * sign-in header can be sent). Each change is re-dispatched as a window "sift:live" event; pages
 * that show mail reload quietly when they hear one (useLoad's `live` option). Reconnects on its
 * own with backoff; after a reconnect, or when the tab comes back after a while, a "resync"
 * makes every live page reload, so nothing is missed. */
import { session } from "./api";

export interface LiveEvent { type: "hello" | "mail" | "new_mail" | "folders" | "drafts" | "resync"; ids?: string[] }

let started = false;
let controller: AbortController | null = null;

export function emit(e: LiveEvent) {
  dispatchEvent(new CustomEvent<LiveEvent>("sift:live", { detail: e }));
}

export function startLive() {
  if (started) return;
  started = true;
  let hiddenAt = 0;
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) hiddenAt = Date.now();
    else if (hiddenAt && Date.now() - hiddenAt > 30_000) emit({ type: "resync" });
  });
  void connect(0);
}

export function stopLive() {
  started = false;
  controller?.abort();
}

async function connect(attempt: number): Promise<void> {
  if (!started) return;
  const token = session.token();
  if (!token) { started = false; return; }
  controller = new AbortController();
  let gotData = false;
  try {
    const res = await fetch("/api/v1/events", { headers: { Authorization: `Bearer ${token}`, Accept: "text/event-stream" }, signal: controller.signal });
    if (res.status === 401) { started = false; return; }
    if (!res.ok || !res.body) throw new Error(`events ${res.status}`);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let cut: number;
      while ((cut = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, cut);
        buf = buf.slice(cut + 2);
        const data = block.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trim()).join("\n");
        if (!data) continue;
        try {
          const e = JSON.parse(data) as LiveEvent;
          if (e.type === "hello") { if (attempt > 0) emit({ type: "resync" }); gotData = true; continue; }
          emit(e);
        } catch { /* ignore a malformed block */ }
      }
    }
  } catch {
    if (!started) return;
  }
  // dropped (server restart, network): try again, backing off up to 30 s
  const wait = gotData ? 1000 : Math.min(30_000, 1000 * 2 ** Math.min(attempt, 5));
  setTimeout(() => void connect(gotData ? 1 : attempt + 1), wait);
}

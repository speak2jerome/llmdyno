// One WebSocket for the whole app. Components subscribe to topics; the hub reconnects and re-subscribes.
//
// Stale connections: the server sends a ping every 20 s, so 50 s of silence means a half-open socket (sleep, VPN
// change, proxy restart) and the hub reconnects on its own. Events missed while disconnected, or dropped because the
// tab could not keep up, are recovered by a "resync": every listener refetches what it shows.
import { useEffect, useRef, useState } from "react";

export type WsMsg = { topic: string; kind: string; data: any; ts: number };
type Handler = (m: WsMsg) => void;

const STALE_MS = 50_000;

class Hub {
  ws: WebSocket | null = null;
  handlers = new Map<string, Set<Handler>>();
  connected = false;
  everConnected = false;
  listeners = new Set<(c: boolean) => void>();
  resyncers = new Set<() => void>();
  backoff = 500;
  lastMsg = 0;
  retry: number | null = null;

  constructor() {
    setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN && Date.now() - this.lastMsg > STALE_MS) this.ws.close();
    }, 10_000);
    const wake = () => {
      if (this.ws?.readyState === WebSocket.OPEN || this.ws?.readyState === WebSocket.CONNECTING) return;
      this.backoff = 500;
      this.schedule(0);
    };
    window.addEventListener("online", wake);
    document.addEventListener("visibilitychange", () => document.visibilityState === "visible" && wake());
  }

  connect() {
    this.retry = null;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    this.ws = ws;
    ws.onopen = () => {
      this.backoff = 500;
      this.lastMsg = Date.now();
      const topics = [...this.handlers.keys()].filter((t) => t !== "*");
      if (topics.length) ws.send(JSON.stringify({ sub: topics }));
      this.setConnected(true);
      if (this.everConnected) this.resync();
      this.everConnected = true;
    };
    ws.onmessage = (e) => {
      this.lastMsg = Date.now();
      let batch: WsMsg[];
      try {
        batch = JSON.parse(e.data);
      } catch {
        return;
      }
      for (const m of batch) {
        if (m.kind === "resync") {
          this.resync();
          continue;
        }
        this.handlers.get(m.topic)?.forEach((h) => h(m));
        this.handlers.get("*")?.forEach((h) => h(m));
      }
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.setConnected(false);
      this.schedule(this.backoff);
      this.backoff = Math.min(this.backoff * 2, 8000);
    };
  }

  schedule(ms: number) {
    if (this.retry !== null) clearTimeout(this.retry);
    this.retry = window.setTimeout(() => this.connect(), ms);
  }

  resync() {
    this.resyncers.forEach((r) => r());
  }

  setConnected(c: boolean) {
    this.connected = c;
    this.listeners.forEach((l) => l(c));
  }

  on(topic: string, h: Handler) {
    let set = this.handlers.get(topic);
    if (!set) {
      set = new Set();
      this.handlers.set(topic, set);
      if (this.ws?.readyState === WebSocket.OPEN && topic !== "*") this.ws.send(JSON.stringify({ sub: [topic] }));
    }
    set.add(h);
    return () => {
      set!.delete(h);
      if (!set!.size) {
        this.handlers.delete(topic);
        if (this.ws?.readyState === WebSocket.OPEN && topic !== "*" && topic !== "jobs")
          this.ws.send(JSON.stringify({ unsub: [topic] }));
      }
    };
  }

  onResync(fn: () => void) {
    this.resyncers.add(fn);
    return () => {
      this.resyncers.delete(fn);
    };
  }
}

export const hub = new Hub();
hub.connect();

/** Subscribe to a topic for the component's lifetime. The handler may change between renders. */
export function useTopic(topic: string | null | undefined, handler: Handler) {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    if (!topic) return;
    return hub.on(topic, (m) => ref.current(m));
  }, [topic]);
}

/** Run fn after a reconnect or when the server says events were dropped: refetch whatever the component shows. */
export function useResync(fn: () => void) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => hub.onResync(() => ref.current()), []);
}

/** True while connected, and also during the very first connection attempt (so nothing flashes on page load). */
export function useConnected() {
  const [c, setC] = useState(hub.connected || !hub.everConnected);
  useEffect(() => {
    const l = (v: boolean) => setC(v || !hub.everConnected);
    hub.listeners.add(l);
    // if the first connection never succeeds, say so after a few seconds
    const t = setTimeout(() => !hub.connected && setC(false), 4000);
    return () => {
      hub.listeners.delete(l);
      clearTimeout(t);
    };
  }, []);
  return c;
}

import type { Client } from "./client.ts";
import { InvalidError } from "./errors.ts";
import { Job, Plan, Run, RUN_FINISHED, TERMINAL, type Json } from "./handles.ts";

/**
 * Something that happened while LLMDyno worked. kind is one of:
 * - "run": a run changed state; data is the run summary (id, status, stage, correctness, wall_s, cost_usd, …)
 * - "plan": the plan changed state; data has its status
 * - "gpu": a GPU telemetry sample while a local model runs
 * - "transcript": one agent event of a run: { i, ev } (with transcript: true)
 * - "proxy": one model request through LLMDyno's proxy: tokens, cost, latency (with transcript: true)
 * - "job": a background job's progress: status, progress (0-1), detail
 * - "log": one line of a job's log
 */
export interface LiveEvent {
  kind: "run" | "plan" | "gpu" | "transcript" | "proxy" | "job" | "log";
  /** Where it came from: plan:<id>, run:<id> or job:<id>. */
  topic: string;
  data: any;
  /** When it happened, in seconds since 1970 (as the server reports it). */
  ts: number;
  status: string | undefined;
  runId: string | undefined;
  /** A run that reached done / failed / cancelled / skipped, or a plan or job that stopped. */
  finished: boolean;
}

export interface WatchOptions {
  /** Also every agent event and model request of the plan's runs. */
  transcript?: boolean;
  /** GPU samples (default true). */
  gpu?: boolean;
  /** Stop after this many milliseconds. */
  timeoutMs?: number;
  /** How often to poll as well, in milliseconds (default 2000); polling covers anything the socket misses. */
  pollMs?: number;
  /** Stop when this signal aborts. */
  signal?: AbortSignal;
}

export type WatchTarget = Plan | Run | Job | string;

const KINDS: Record<string, LiveEvent["kind"]> = {
  "plan/run": "run", "plan/plan": "plan", "plan/gpu": "gpu", "run/status": "run", "run/transcript": "transcript",
  "run/proxy": "proxy", "job/update": "job", "job/log": "log",
};

function makeEvent(kind: LiveEvent["kind"], topic: string, data: any, ts: number): LiveEvent {
  const status = data && typeof data === "object" ? data.status : undefined;
  const runId = topic.startsWith("run:") ? topic.slice(4) : kind === "run" && data && typeof data === "object" ? data.id : undefined;
  const finished = kind === "run" ? (RUN_FINISHED as readonly string[]).includes(status)
    : (kind === "plan" || kind === "job") && (TERMINAL as readonly string[]).includes(status);
  return { kind, topic, data, ts, status, runId, finished };
}

function targetOf(x: WatchTarget): ["plan" | "run" | "job", string] {
  if (x instanceof Plan) return ["plan", x.id];
  if (x instanceof Run) return ["run", x.id];
  if (x instanceof Job) return ["job", x.id];
  for (const kind of ["plan", "run", "job"] as const) if (x.startsWith(`${kind}_`)) return [kind, x];
  throw new InvalidError(`watch() takes a plan, run or job (or its id), not ${JSON.stringify(x)}`);
}

function stopped(kind: string, d: Json): boolean {
  if (kind === "plan") {
    const job = d.job ?? {};
    return (TERMINAL as readonly string[]).includes(d.status) && (job.status == null || (TERMINAL as readonly string[]).includes(job.status));
  }
  if (kind === "run") return (RUN_FINISHED as readonly string[]).includes(d.status);
  return (TERMINAL as readonly string[]).includes(d.status);
}

interface Socket {
  add(topics: string[]): void;
  close(): void;
}

/** The server's WebSocket, or undefined when there is none (polling still works). */
function openSocket(client: Client, onMessage: (msg: Json) => void, topics: string[]): Socket | undefined {
  const WS = client.WebSocket;
  if (!WS) return undefined;
  const url = client.url.replace(/^http/, "ws") + "/ws" + (client.token ? `?token=${encodeURIComponent(client.token)}` : "");
  let ws: WebSocket;
  try {
    ws = new WS(url);
  } catch {
    return undefined;
  }
  const pending = [...topics];
  let open = false;
  ws.addEventListener("open", () => {
    open = true;
    if (pending.length) ws.send(JSON.stringify({ sub: pending.splice(0) }));
  });
  ws.addEventListener("message", (e: MessageEvent) => {
    let batch: unknown;
    try {
      batch = JSON.parse(typeof e.data === "string" ? e.data : new TextDecoder().decode(e.data as ArrayBuffer));
    } catch {
      return;
    }
    for (const msg of Array.isArray(batch) ? batch : [batch]) {
      if (msg && typeof msg === "object" && msg.topic !== "ping" && msg.topic !== "*") onMessage(msg as Json);
    }
  });
  ws.addEventListener("error", () => { /* the polling carries on */ });
  return {
    add(more) {
      if (open) ws.send(JSON.stringify({ sub: more }));
      else pending.push(...more);
    },
    close() {
      try {
        ws.close();
      } catch { /* already closed */ }
    },
  };
}

/**
 * Follow a plan, run or job until it stops:
 *
 *     for await (const ev of dyno.watch(plan)) {
 *       if (ev.kind === "run" && ev.finished) console.log(ev.data.benchmark_id, ev.status, ev.data.correctness);
 *     }
 *
 * Events come live over the server's WebSocket; the state is also polled every pollMs so nothing is missed when the
 * socket is unavailable (a proxy that blocks WebSockets, say).
 */
export async function* watch(client: Client, target: WatchTarget, options: WatchOptions = {}): AsyncGenerator<LiveEvent> {
  const [kind, tid] = targetOf(target);
  const transcript = Boolean(options.transcript);
  const gpu = options.gpu ?? true;
  const pollMs = options.pollMs ?? 2000;
  const deadline = options.timeoutMs ? Date.now() + options.timeoutMs : undefined;
  const runs = new Set<string>();
  const last = new Map<string, string>();
  const polled = new Set<string>();
  const queue: LiveEvent[] = [];
  let wake: (() => void) | undefined;

  const snapshot = async (): Promise<Json> => {
    if (kind === "plan") {
      const d = await client.call("plans.get_plan", { pid: tid });
      for (const r of d.runs ?? []) runs.add(r.id);
      return d;
    }
    if (kind === "run") return client.call("runs.get_run", { rid: tid });
    return client.call("system.get_job", { jid: tid });
  };

  const wanted = (topic: string) => (kind === "plan"
    ? topic === `plan:${tid}` || (transcript && topic.startsWith("run:") && runs.has(topic.slice(4)))
    : topic === `${kind}:${tid}`);

  let socket: Socket | undefined;
  const onMessage = (msg: Json) => {
    const topic = String(msg.topic ?? "");
    if (!wanted(topic)) return;
    const area = topic.split(":", 1)[0];
    const evKind = KINDS[`${area}/${msg.kind}`];
    if (!evKind || (evKind === "gpu" && !gpu)) return;
    if (kind === "plan" && evKind === "run" && area === "run") return;   // the plan topic carries every run change
    if ((evKind === "transcript" || evKind === "proxy") && !transcript) return;
    if (evKind === "run" && msg.data && typeof msg.data === "object") {
      const rid = msg.data.id;
      if (transcript && rid && !runs.has(rid)) socket?.add([`run:${rid}`]);
      if (rid) runs.add(rid);
    }
    queue.push(makeEvent(evKind, topic, msg.data, Number(msg.ts) || Date.now() / 1000));
    wake?.();
  };
  socket = openSocket(client, onMessage, [`${kind}:${tid}`]);
  const abort = () => wake?.();
  options.signal?.addEventListener("abort", abort);

  try {
    const first = await snapshot();
    if (kind === "plan") {
      for (const r of first.runs ?? []) {
        last.set(r.id, r.status);
        if (transcript) socket?.add([`run:${r.id}`]);
      }
    }
    last.set(tid, first.status);
    if (stopped(kind, first)) {
      yield makeEvent(kind, `${kind}:${tid}`, first, Date.now() / 1000);
      return;
    }
    let nextPoll = Date.now() + pollMs;
    for (;;) {
      if (options.signal?.aborted) return;
      if (!queue.length) {
        const waitMs = Math.max(50, Math.min(nextPoll, deadline ?? nextPoll) - Date.now());
        await new Promise<void>((resolve) => {
          const timer = setTimeout(resolve, waitMs);
          wake = () => {
            clearTimeout(timer);
            resolve();
          };
        });
        wake = undefined;
      }
      const ev = queue.shift();
      if (ev) {
        const key = ev.kind === "run" ? ev.runId : ev.kind === "plan" || ev.kind === "job" ? tid : undefined;
        if (key !== undefined && ev.status !== undefined) {
          if (polled.has(key) && last.get(key) === ev.status) {
            polled.delete(key);
            continue;                       // a poll got there first and already reported this status
          }
          polled.delete(key);
          last.set(key, ev.status);
        }
        yield ev;
        if ((ev.kind === "plan" || ev.kind === "job" || ev.kind === "run") && key === tid
            && [...TERMINAL, ...RUN_FINISHED].includes(ev.status as never)) {
          if (stopped(kind, await snapshot())) return;   // a plan is over once its job has stopped too
        }
      }
      if (deadline !== undefined && Date.now() >= deadline) return;
      if (Date.now() >= nextPoll) {
        nextPoll = Date.now() + pollMs;
        const d = await snapshot();
        if (kind === "plan") {
          for (const r of d.runs ?? []) {
            if (last.get(r.id) !== r.status) {
              last.set(r.id, r.status);
              polled.add(r.id);
              yield makeEvent("run", `plan:${tid}`, r, Date.now() / 1000);
            }
          }
        }
        if (last.get(tid) !== d.status) {
          last.set(tid, d.status);
          polled.add(tid);
          yield makeEvent(kind, `${kind}:${tid}`, d, Date.now() / 1000);
        }
        if (stopped(kind, d)) return;
      }
    }
  } finally {
    options.signal?.removeEventListener("abort", abort);
    socket?.close();
  }
}

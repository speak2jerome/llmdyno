// Unit tests with a fake server: run with `npm test` (Node 22.18+ runs TypeScript directly).
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import {
  API_METHODS, Client, ConflictError, ForbiddenError, InvalidError, LLMDynoError, NotFoundError, PreflightError, Plan,
  ROUTES, Results, VERSION, connect,
} from "../src/index.ts";

type Handler = (req: { method: string; url: URL; body: unknown; headers: Record<string, string> }) => Response | Promise<Response>;

const json = (data: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json", ...headers } });

function fakeFetch(handler: Handler) {
  const seen: Array<{ method: string; url: URL; body: unknown; headers: Record<string, string> }> = [];
  const fn = (async (input: string | URL | Request, init: RequestInit = {}) => {
    const url = new URL(String(input));
    const headers = Object.fromEntries(Object.entries((init.headers ?? {}) as Record<string, string>));
    let body: unknown = init.body;
    if (typeof body === "string") body = JSON.parse(body);
    const req = { method: init.method ?? "GET", url, body, headers };
    seen.push(req);
    return handler(req);
  }) as typeof fetch;
  return { fn, seen };
}

test("call() puts path, query and body parameters where the route says", async () => {
  const { fn, seen } = fakeFetch(() => json({ ok: true }));
  const c = new Client("http://box:8777/", { fetch: fn, token: "t0k" });
  await c.call("runs.run_transcript", { rid: "run_a/b", start: 5, limit: 10 });
  await c.call("plans.rename_plan", { pid: "plan_1", body: { name: "x" } });
  await c.call("system.get_specs", { refresh: true });
  assert.equal(seen[0].method, "GET");
  assert.equal(seen[0].url.pathname, "/api/runs/run_a%2Fb/transcript");
  assert.equal(seen[0].url.search, "?start=5&limit=10");
  assert.equal(seen[0].headers.Authorization, "Bearer t0k");
  assert.equal(seen[1].method, "PATCH");
  assert.deepEqual(seen[1].body, { name: "x" });
  assert.equal(seen[1].headers["Content-Type"], "application/json");
  assert.equal(seen[2].url.search, "?refresh=true");
});

test("call() refuses unknown operations, unknown parameters and missing path parameters", async () => {
  const c = new Client("http://box", { fetch: fakeFetch(() => json({})).fn });
  await assert.rejects(c.call("runs.nope"), InvalidError);
  await assert.rejects(c.call("runs.get_run", { rid: "r", colour: "red" }), /takes no colour/);
  await assert.rejects(c.call("runs.get_run", {}), /needs rid/);
});

test("the api object has one method per operation, calling that operation", async () => {
  const { fn, seen } = fakeFetch(() => json([]));
  const c = new Client("http://box", { fetch: fn });
  const methods = Object.values(API_METHODS).flatMap((m) => Object.values(m));
  assert.equal(methods.length, Object.keys(ROUTES).length);
  assert.equal(new Set(methods).size, methods.length);
  await c.api.runs.runFiles({ rid: "run_1", root: "home" });
  await c.api.harnesses.listHarnesses();
  assert.equal(seen[0].url.pathname + seen[0].url.search, "/api/runs/run_1/files?root=home");
  assert.equal(seen[1].url.pathname, "/api/harnesses");
});

test("HTTP errors become the same error classes as in Python", async () => {
  const statuses: Record<string, number> = { "/api/runs/a": 404, "/api/runs/b": 409, "/api/runs/c": 401, "/api/runs/d": 500 };
  const c = new Client("http://box", {
    fetch: fakeFetch(({ url }) => json({ detail: `no ${url.pathname}` }, statuses[url.pathname])).fn,
  });
  await assert.rejects(c.call("runs.get_run", { rid: "a" }), (e: unknown) => e instanceof NotFoundError && e.status === 404 && e.message === "no /api/runs/a");
  await assert.rejects(c.call("runs.get_run", { rid: "b" }), ConflictError);
  await assert.rejects(c.call("runs.get_run", { rid: "c" }), ForbiddenError);
  await assert.rejects(c.call("runs.get_run", { rid: "d" }), (e: unknown) => e instanceof LLMDynoError && e.status === 500);
  assert.equal(new NotFoundError("x").status, 404);
});

test("downloads come back as text or bytes with their file name", async () => {
  const c = new Client("http://box", {
    fetch: fakeFetch(({ url }) => (url.pathname.endsWith("/download")
      ? new Response(new Uint8Array([80, 75, 3, 4]), { headers: { "content-type": "application/zip", "content-disposition": 'attachment; filename="run_1.zip"' } })
      : new Response("a,b\n1,2\n", { headers: { "content-type": "text/csv; charset=utf-8", "content-disposition": "attachment; filename=results.csv" } }))).fn,
  });
  const zip = await c.run("run_1").download();
  assert.equal(zip.filename, "run_1.zip");
  assert.ok(zip.content instanceof Uint8Array && zip.content[0] === 80);
  const csv = await c.call("results.export", { level: "runs", fmt: "csv" });
  assert.equal(csv.filename, "results.csv");
  assert.equal(csv.content, "a,b\n1,2\n");
});

test("connect() checks the server and explains a refused token", async () => {
  const ok = fakeFetch(() => json({ ok: true, version: VERSION }));
  const c = await connect("http://box:1", { fetch: ok.fn });
  assert.equal(c.server.version, VERSION);
  const refused = fakeFetch(() => json({ detail: "missing or wrong access token" }, 401));
  await assert.rejects(connect("http://box:1", { fetch: refused.fn }), /refused the connection.*LLMDYNO_TOKEN/);
  const nothing = fakeFetch(() => { throw new TypeError("fetch failed"); });
  await assert.rejects(connect("http://box:1", { fetch: nothing.fn }), /cannot reach LLMDyno at http:\/\/box:1/);
});

test("bench() stops on blocking problems and on unacknowledged risks", async () => {
  let preflight: unknown = { ok: false, blocking: [{ text: "no Docker" }], warnings: [] };
  const { fn, seen } = fakeFetch(({ url }) => {
    if (url.pathname === "/api/profiles") return json([{ id: "prof_1", name: "Qwen", kind: "local" }]);
    if (url.pathname === "/api/plans/preflight") return json(preflight);
    if (url.pathname === "/api/plans") return json({ plan_id: "plan_9", job_id: "job_9" });
    return json({});
  });
  const c = new Client("http://box", { fetch: fn });
  await assert.rejects(c.bench("qwen"), (e: unknown) => e instanceof PreflightError && e.problems[0] === "no Docker");
  preflight = { ok: true, blocking: [], warnings: [{ text: "may spill", ack: true }] };
  await assert.rejects(c.bench("qwen"), /acknowledgeRisks/);
  const plan = await c.bench("prof_1", { acknowledgeRisks: true, wait: false, benchmarks: ["t1"], budgetUsd: 2 });
  assert.ok(plan instanceof Plan && plan.id === "plan_9");
  const created = seen.find((r) => r.url.pathname === "/api/plans" && r.method === "POST")!;
  assert.deepEqual(created.body, {
    name: "", profile_ids: ["prof_1"], harness_ids: ["pi"], benchmark_ids: ["t1"], iterations: 1,
    options: { budget_usd: 2, quality: true }, start: true, acknowledge_risks: true,
  });
});

test("cloudModel() rejects unknown settings before calling anything that changes the server", async () => {
  const { fn, seen } = fakeFetch(() => json([{ id: "openai", name: "OpenAI" }]));
  const c = new Client("http://box", { fetch: fn });
  await assert.rejects(c.cloudModel("openai", "gpt-x", { temprature: 0.2 }), /unknown cloud setting "temprature"/);
  await assert.rejects(c.cloudModel("nope", "m"), /unknown vendor/);
  assert.ok(seen.every((r) => r.method === "GET"));
});

class FakeSocket {
  static last: FakeSocket | undefined;
  sent: unknown[] = [];
  closed = false;
  url: string;
  private listeners: Record<string, Array<(e: any) => void>> = {};

  constructor(url: string) {
    this.url = url;
    FakeSocket.last = this;
    setTimeout(() => this.emit("open", {}), 0);
  }

  addEventListener(name: string, fn: (e: any) => void) {
    (this.listeners[name] ??= []).push(fn);
  }

  send(data: string) {
    this.sent.push(JSON.parse(data));
  }

  close() {
    this.closed = true;
  }

  emit(name: string, e: unknown) {
    for (const fn of this.listeners[name] ?? []) fn(e);
  }

  push(...msgs: unknown[]) {
    this.emit("message", { data: JSON.stringify(msgs) });
  }
}

test("watch() streams live events, skips duplicates from polling and stops with the plan", async () => {
  let state = { status: "running", runs: [{ id: "run_1", status: "running" }], job: { status: "running" } };
  const { fn } = fakeFetch(({ url }) => (url.pathname === "/api/plans/plan_1" ? json(state) : json({})));
  const c = new Client("http://box:8777", { fetch: fn, token: "abc", WebSocket: FakeSocket as unknown as typeof WebSocket });
  const seen: string[] = [];
  const it = c.watch("plan_1", { pollMs: 40 });
  const consume = (async () => {
    for await (const ev of it) seen.push(`${ev.kind}:${ev.runId ?? ""}:${ev.status ?? ""}:${ev.finished}`);
  })();
  await new Promise((r) => setTimeout(r, 20));
  const ws = FakeSocket.last!;
  assert.equal(ws.url, "ws://box:8777/ws?token=abc");
  assert.deepEqual(ws.sent[0], { sub: ["plan:plan_1"] });
  ws.push({ topic: "plan:plan_1", kind: "run", data: { id: "run_1", status: "done" }, ts: 1 },
    { topic: "ping", kind: "ping", ts: 2 }, { topic: "plan:other", kind: "run", data: { id: "x", status: "done" }, ts: 3 });
  await new Promise((r) => setTimeout(r, 10));
  state = { status: "done", runs: [{ id: "run_1", status: "done" }], job: { status: "done" } };
  await consume;
  assert.deepEqual(seen, ["run:run_1:done:true", "plan::done:true"]);
  assert.ok(ws.closed);
});

test("Results turns the server's tables into rows like the Python library", () => {
  const data = {
    labels: { profiles: { p1: { name: "Qwen" } }, harnesses: { pi: "Pi" }, benchmarks: { t1: { title: "Flask site" } } },
    configs: [{ profile_id: "p1", harness_id: "pi", final: 0.9087, correctness: 1, quality: 0.78, runs: 5 }],
    runs: [{ id: "run_1", plan_id: "plan_1", profile_id: "p1", harness_id: "pi", benchmark_id: "swe_x", iteration: 1, correctness: 1 }],
  };
  const r = new (Results as any)(null, data, ["plan_1"], {}) as Results;
  assert.deepEqual(r.best()!.final, 90.9);
  assert.equal(r.best()!.profile, "Qwen");
  assert.equal(r.runs()[0].benchmark, "swe_x");
  assert.deepEqual(r.public(), [{ profile: "Qwen", harness: "Pi", swebench_resolved_pct: 100, swebench_runs: 1, polyglot_solved_pct: null, polyglot_runs: 0 }]);
  assert.match(r.toString(), /1\s+Qwen\s+Pi\s+90\.9/);
  assert.throws(() => r.rows("nope" as never), /level is one of/);
});

test("npx llmdyno explains what to install when no Python, uv or pipx is found", () => {
  const cli = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "cli.ts");
  const r = spawnSync(process.execPath, ["--disable-warning=ExperimentalWarning", cli], {
    env: { PATH: "", SystemRoot: process.env.SystemRoot ?? "", LLMDYNO_LAUNCHER_DRY_RUN: "1" }, encoding: "utf8",
  });
  assert.equal(r.status, 1, r.stderr);
  assert.match(r.stderr, /uv \(recommended\)/);
});

test("npx llmdyno runs the installed Python package, passing arguments through", { skip: !process.env.LLMDYNO_TEST_PYTHON }, () => {
  const cli = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "cli.ts");
  const run = (...args: string[]) => {
    const r = spawnSync(process.execPath, ["--disable-warning=ExperimentalWarning", cli, ...args], {
      env: { ...process.env, LLMDYNO_PYTHON: process.env.LLMDYNO_TEST_PYTHON, LLMDYNO_LAUNCHER_DRY_RUN: "1" }, encoding: "utf8",
    });
    assert.equal(r.status, 0, r.stderr);
    return JSON.parse(r.stdout) as { runner: string; command: string[] };
  };
  const plain = run();
  assert.match(plain.runner, /-m llmdyno \(LLMDyno \d/);
  assert.deepEqual(plain.command.slice(-4), ["-m", "llmdyno", "serve", "--open"]);
  assert.deepEqual(run("doctor", "--json").command.slice(-2), ["doctor", "--json"]);
});

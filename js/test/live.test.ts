// Tests against a real LLMDyno server: LLMDYNO_TEST_URL=http://127.0.0.1:8777 npm run test:live
// They load the bundled sample results (no Docker or model needed) and only read, apart from the sample itself.
import assert from "node:assert/strict";
import { before, test } from "node:test";

import { Client, InvalidError, NotFoundError, ROUTES, VERSION, connect } from "../src/index.ts";

const URL_ = process.env.LLMDYNO_TEST_URL;
const skip = !URL_ && "set LLMDYNO_TEST_URL to a running LLMDyno server";
let dyno: Client;
let planId: string;

before(async () => {
  if (skip) return;
  dyno = await connect(URL_);
  planId = (await dyno.loadSample()).id;
});

test("connects and reports the server's version", { skip }, () => {
  assert.equal(dyno.server.ok, true);
  assert.equal(String(dyno.server.version).split(".").slice(0, 2).join("."), VERSION.split(".").slice(0, 2).join("."));
});

test("every operation the client knows is a route of this server", { skip }, async () => {
  const spec = await (await fetch(`${URL_}/openapi.json`)).json() as { paths: Record<string, Record<string, unknown>> };
  const served = new Set(Object.entries(spec.paths).flatMap(([p, ops]) => Object.keys(ops).map((m) => `${m.toUpperCase()} ${p}`)));
  const missing = Object.entries(ROUTES).filter(([, r]) => !served.has(`${r.method} ${r.path}`)).map(([op]) => op);
  assert.deepEqual(missing, []);
});

test("the sample's results match the README's Round 1 table", { skip }, async () => {
  const results = await dyno.results(planId);
  const board = results.leaderboard();
  assert.equal(board.length, 15);
  assert.equal(board[0].profile.startsWith("GPT-6 Luna"), true);
  assert.equal(board[0].final, 94.3);
  assert.equal(results.runs().length, 75);
  assert.match(results.toString(), /GPT-6 Luna/);
  const csv = await results.export({ level: "configs", fmt: "csv" });
  assert.match(csv.split("\n")[0], /profile/i);
});

test("plans, runs, transcripts and files", { skip }, async () => {
  const plan = dyno.plan(planId);
  const info = await plan.refresh();
  assert.equal(info.status, "done");
  const runs = await plan.runs();
  assert.equal(runs.length, 75);
  const run = runs[0];
  const summary = await run.refresh();
  assert.equal(summary.plan_id, planId);
  const events = await run.transcript({ limit: 50 });
  assert.ok(Array.isArray(events));
  const events2 = [];
  for await (const ev of dyno.watch(plan, { timeoutMs: 10_000 })) events2.push(ev);
  assert.equal(events2.length, 1);
  assert.equal(events2[0].kind, "plan");
  assert.equal(events2[0].finished, true);
});

test("profiles, harnesses, benchmarks and the typed api", { skip }, async () => {
  const profiles = await dyno.profiles();
  assert.ok(profiles.length >= 15);
  const byName = await dyno.profile(profiles[0].name);
  assert.equal(byName.id, profiles[0].id);
  const harnesses = await dyno.api.harnesses.listHarnesses();
  assert.ok(harnesses.some((h: { id: string }) => h.id === "pi"));
  const suites = await dyno.listSuites();
  assert.ok(suites.some((s) => s.id === "suite_quick"));
  const vendors = await dyno.api.providers.listVendors();
  assert.ok(vendors.some((v: { id: string }) => v.id === "openai"));
});

test("errors come back typed", { skip }, async () => {
  await assert.rejects(dyno.run("run_does_not_exist").refresh(), NotFoundError);
  await assert.rejects(dyno.profile("no such profile anywhere"), NotFoundError);
  await assert.rejects(dyno.call("plans.get_plan", { pid: planId, colour: "red" }), InvalidError);
});

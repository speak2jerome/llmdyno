# JavaScript and TypeScript

LLMDyno is a Python app that runs agents in Docker. From JavaScript or TypeScript there are three ways to use it:

- **`npx llmdyno`** starts it.
- **The `llmdyno` npm package** drives it from Node, Bun, Deno or a browser, with the same calls as the Python library.
- **`node_harness()`** benchmarks your own TypeScript agent, built with the Vercel AI SDK, Mastra, LangChain.js, the
  OpenAI Agents SDK or plain code.

## Start LLMDyno

```bash
npx llmdyno            # starts LLMDyno and opens the dashboard at http://127.0.0.1:8777
npx llmdyno doctor     # any other arguments go to the LLMDyno command line
```

`npx llmdyno` needs Python 3.11+ on the machine. It tries these in order:

1. A Python that already has LLMDyno installed (`pip install llmdyno`). `LLMDYNO_PYTHON` names a Python to try first.
2. [uv](https://docs.astral.sh/uv/) (`uvx`), running the LLMDyno version that matches the npm package.
3. [pipx](https://pipx.pypa.io/), the same way.

If it finds none of them, it says what to install. Docker is needed to run benchmarks, as with every way of using
LLMDyno.

## The client

```bash
npm install llmdyno
```

It needs Node 22 or later, or any runtime with `fetch` and `WebSocket`. It has no dependencies.

```ts
import { connect } from "llmdyno";

const dyno = await connect();     // http://127.0.0.1:8777, or LLMDYNO_URL and LLMDYNO_TOKEN
```

`connect()` checks that a LLMDyno server answers. It warns if the server's version differs from the client's in the
first two numbers. On another machine, start the server with `llmdyno serve --host 0.0.0.0` and pass its access
token: `connect("http://gpu-box:8777", { token })`. See [Remote mode](REMOTE.md).

### Benchmark

```ts
const gpt = await dyno.cloudModel("openai", "gpt-6-luna", { reasoning_effort: "low", budgetUsd: 2 });
const qwen = await dyno.profile("Qwen3.8 27B Q3_K_XL 32k");          // a profile you made in the dashboard or Python

const results = await dyno.bench([gpt, qwen], {
  benchmarks: "suite_quick",
  harnesses: ["pi", "opencode"],
  onEvent: (ev) => { if (ev.kind === "run" && ev.finished) console.log(ev.data.benchmark_id, ev.status); },
});
console.log(results.toString());
console.table(results.leaderboard());
```

`bench()` checks the plan first, as in Python. A `PreflightError` lists anything that blocks it, and danger warnings
such as a VRAM spill need `acknowledgeRisks: true`. With `wait: false` it returns the running `Plan` instead of the
results.

`cloudModel()` works like Python's `cloud_model()`: calling it again with the same arguments returns the same profile.
Settings it doesn't know are refused before anything changes on the server. An `apiKey` you pass is stored encrypted
on the server. Without one, the server uses the key it already has for that provider.

### Live events

```ts
const plan = await dyno.bench(qwen, { benchmarks: "t0_smoke_cli", wait: false });
for await (const ev of plan.watch({ transcript: true })) {
  if (ev.kind === "transcript") console.log(ev.data.ev);
  if (ev.kind === "run" && ev.finished) console.log("run", ev.runId, ev.status);
}
```

Events arrive over the server's WebSocket, the same ones the dashboard shows:

| Kind | What it is |
|---|---|
| `run` | A run changed state. |
| `plan` | The plan changed state. |
| `gpu` | A GPU sample. |
| `transcript` | One agent event (with `transcript: true`). |
| `proxy` | One model request (with `transcript: true`). |
| `job` | A job's progress. |
| `log` | A line of a job's log. |

The state is polled every two seconds as well, so nothing is missed if a proxy blocks WebSockets. `timeoutMs` and an
`AbortSignal` stop the loop early.

### Plans, runs and results

```ts
const [run] = await plan.runs();
await run.refresh();                         // status, stage, scores, time, tokens, cost
await run.transcript();                      // messages, thinking, tool calls and results
await run.files();                           // what the agent left in the workspace
await run.readFile("wordfreq.py");
await run.log({ stage: 1, stream: "stderr" });
await run.requests();                        // every model request: tokens, cost, latency
await run.download();                        // the workspace as a zip: { filename, content }

const r = await dyno.results(plan, { quality: 40, passThreshold: 1 });
r.leaderboard(); r.runs(); r.cells(); r.reviews(); r.rubric(); r.public();
await r.export({ level: "runs", fmt: "csv" });
```

`dyno.loadSample()` loads the bundled Round 1 study, so there is data to explore before you run anything.

### Every operation

Each of the 116 operations of the web API is a typed method under `dyno.api`, grouped like the Python library's areas:

```ts
await dyno.api.models.hubSearch({ q: "qwen coder gguf", limit: 5 });
await dyno.api.harnesses.harnessDockerfile({ hid: "pi" });
await dyno.api.system.getSpecs({ refresh: true });
```

The list is generated from the server's own routes by `scripts/gen_js_client.py`. A test fails when the server gains
an operation the client doesn't have, so the JavaScript and Python clients can't drift apart. `dyno.call("runs.get_run",
{ rid })` reaches the same operations by their service name.

### Errors

The client raises the same errors as the Python library, each with the HTTP `status`:

- `NotFoundError` (404);
- `ConflictError` (409);
- `InvalidError` (400);
- `ForbiddenError` (401 or 403);
- `RiskNotAcknowledgedError` (428);
- `RateLimitError` (429);
- `UpstreamError` (502);
- `InsufficientStorageError` (507);
- `PreflightError`, with `problems` and the full `report`.

All of them are `LLMDynoError`s.

## Benchmark your own TypeScript agent

`node_harness()` turns a JavaScript or TypeScript function into a harness. Your agent then runs in the same offline
sandbox as the built-in harnesses, reaching the model only through LLMDyno's proxy, so transcripts, token counts,
budgets and grading work the same way. You register it from Python (or the `llmdyno node-harness` command):

```python
h = llmdyno.node_harness("vercel_ai_agent.ts:run", source="examples/agents/ts/vercel_ai_agent.ts")
llmdyno.bench(qwen, "suite_quick", harnesses=[h.id, "pi"])
```

Then benchmark it from Python, the dashboard or the JavaScript client, like any other harness.

The function is called once per stage, in the task's workspace, with one object:

```ts
interface Task {
  prompt: string; model: string; baseUrl: string; apiKey: string; workspace: string;
  stage: number; ctx?: number; maxTokens?: number; reasoning?: string;
}
export async function run(task: Task): Promise<string> { /* … */ }
```

- **`baseUrl`** is LLMDyno's OpenAI-compatible proxy. `apiKey` is a placeholder, because the proxy adds the real key.
- **The return value** is printed, so return a short summary.
- **The entry point** is `"file.ts:name"`. Without a name, LLMDyno calls the `run` export or the default export.
- **TypeScript runs as it is.** The sandbox runs Node 24, which runs TypeScript directly. Stick to type annotations:
  no enums, namespaces or constructor parameter properties.
- **Dependencies:**
  - `packages=` lists the npm packages to install; pin them.
  - When you leave it out, the entry file's `export const PACKAGES = [...]` is used.
  - A `package.json` in the source folder is installed too.
- **A whole project:** pass `source=` a folder and give the entry point relative to it. `node_modules`, `.git` and build
  output are left out.

Ready-made agents are in
[examples/agents/ts](https://github.com/speak2jerome/llmdyno/tree/main/examples/agents/ts). Each one passed a strict
type check and an end-to-end run against a scripted model. The Vercel AI SDK agent also ran a real benchmark on a local
Qwen3.8 27B: 98.9, with every hidden test passing.

| Framework | Template | Packages |
|---|---|---|
| Vercel AI SDK | `vercel_ai_agent.ts` | `ai`, `@ai-sdk/openai-compatible`, `zod` |
| Mastra | `mastra_agent.ts` | `@mastra/core`, `@ai-sdk/openai-compatible`, `zod` |
| LangGraph.js | `langgraph_agent.ts` | `@langchain/langgraph`, `@langchain/openai`, `@langchain/core`, `zod` |
| OpenAI Agents SDK | `openai_agents_agent.ts` | `@openai/agents`, `openai`, `zod` |

Python agents work the same way with `python_harness()`: see [Integrations](INTEGRATIONS.md#your-own-agent).

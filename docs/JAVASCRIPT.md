# JavaScript and TypeScript

LLMDyno is a Python app that runs agents in Docker. From JavaScript or TypeScript there are three ways to use it:

- **`npx llmdyno`** starts it.
- **The `llmdyno` npm package** drives it from Node: the main calls of the Python library as methods, and every
  operation of the web API, typed, under `dyno.api`.
- **`node_harness()`** benchmarks your own TypeScript agent, built with the Vercel AI SDK, Mastra, LangGraph.js, the
  OpenAI Agents SDK or plain code.

## Start LLMDyno

```bash
npx llmdyno            # starts LLMDyno and opens the dashboard at http://127.0.0.1:8777
npx llmdyno doctor     # any other arguments go to the LLMDyno command line
```

`npx llmdyno` with no arguments runs `llmdyno serve --open`; with arguments it passes them to the
[command line](reference/cli.md) unchanged (`npx llmdyno serve --port 9000`). To run LLMDyno it tries, in this order:

1. **A Python that already has LLMDyno installed** (`pip install llmdyno`). It tries `LLMDYNO_PYTHON` first, then
   `py -3`, `python` and `python3` on Windows, or `python3` and `python` elsewhere. An installed LLMDyno of another
   minor version is still used; the launcher prints a note suggesting `pip install -U llmdyno`.
2. **[uv](https://docs.astral.sh/uv/)**: `uvx --from llmdyno==<this package's version> llmdyno …`. uv can fetch a
   Python by itself.
3. **[pipx](https://pipx.pypa.io/)**: `pipx run --spec llmdyno==<version> llmdyno …`, which needs Python 3.11 or later.

If it finds none of them, it exits with what to install. `LLMDYNO_LAUNCHER_DRY_RUN=1` prints the command it would
run instead of running it. Docker is needed to run benchmarks, whichever way LLMDyno is started.

## The client

```bash
npm install llmdyno
```

It needs Node 22 or later and has no dependencies. It uses only `fetch` and `WebSocket`, so other runtimes that have
both, such as Bun and Deno, should work, but they aren't tested. In a browser it works only on pages the LLMDyno
server serves itself, because the server sends no CORS headers. The package is ESM only and ships its own type
definitions.

```ts
import { connect } from "llmdyno";

const dyno = await connect();     // LLMDYNO_URL, else http://127.0.0.1:8777; token from LLMDYNO_TOKEN
```

`connect(url?, options?)` calls the server's health check and fails if nothing answers or the answer isn't from
LLMDyno. It prints a warning when the server's version differs from the client's in the first two numbers, because
calls that changed between them may fail. `new Client(url, options)` makes a client without reading the environment
or checking the server.

On another machine, start the server with `llmdyno serve --host 0.0.0.0` and pass its access token:
`connect("http://gpu-box:8777", { token })`. See [Remote mode](REMOTE.md).

| Option | Default | What it does |
|---|---|---|
| `token` | `LLMDYNO_TOKEN` | The server's access token. Not needed on the server's own machine. |
| `timeoutMs` | `120000` | How long one request may take. Long work runs as jobs, so requests are short. |
| `fetch` | the global `fetch` | A `fetch` to use instead, for tests or proxies. |
| `WebSocket` | the global `WebSocket` | A WebSocket class for live events. Without one, `watch()` polls. |

### Benchmark

```ts
const gpt = await dyno.cloudModel("openai", "gpt-6-luna", { reasoning_effort: "low" });
const qwen = await dyno.profile("Qwen3.8 27B Q3_K_XL 32k");          // a profile you made in the dashboard or Python

const results = await dyno.bench([gpt, qwen], {
  benchmarks: "suite_quick",
  harnesses: ["pi", "opencode"],
  onEvent: (ev) => { if (ev.kind === "run" && ev.finished) console.log(ev.data.benchmark_id, ev.status); },
});
console.log(results.toString());
console.table(results.leaderboard());
```

`bench(models, options)` runs every profile × harness × benchmark × iteration and waits for the plan to stop. Models
are `Profile` objects, profile names or profile ids. Before it starts, it runs the same preflight as the dashboard: a
`PreflightError` lists anything that blocks the plan (a harness image not built, no API key, Docker not running, …),
and danger warnings such as a VRAM spill need `acknowledgeRisks: true`. `dyno.preflight(models, options)` returns
that report without starting anything.

`bench()` resolves when the plan stops, which includes `paused`. A plan with failed runs still returns `Results` for
what finished; it does not throw. With `wait: false` it returns the running `Plan` at once.

| Option | Default | What it does |
|---|---|---|
| `benchmarks` | `"suite_quick"` | Benchmark or suite ids, one or a list. `dyno.listBenchmarks()` and `listSuites()` list them. |
| `harnesses` | `"pi"` | Harness ids: `pi`, `opencode`, `codex`, `qwen-code`, `crush`, `aider`, `mini-swe-agent`, or your own. |
| `iterations` | `1` | Runs of each combination. Three or more give confidence intervals. |
| `name` | a dated name | The plan's name. |
| `budgetUsd` | none | A cap on this plan's cloud spend, on top of each provider's own cap. |
| `quality` | `true` | Run static analysis and behaviour probes after grading. |
| `timeoutMultiplier` | `1` | Multiplies every benchmark's time limit, for slow machines or CPU-only models. |
| `cloudConcurrency` | the server's setting (3) | Cloud runs in parallel. Local runs always take the GPU one model at a time. |
| `allowSpill` | `false` | Let local profiles run although their memory check says they spill out of VRAM. The results are flagged. |
| `acknowledgeRisks` | `false` | Start despite danger warnings. The results are flagged. |
| `onEvent` | none | Called with every live event while `bench()` waits. |
| `wait` | `true` | `false` returns the running `Plan` instead of waiting. |

### Cloud models and profiles

`cloudModel(vendor, model, options)` works like Python's `cloud_model()`. It makes (or finds) the provider and the
profile, and calling it again with the same arguments returns the same profile. Settings it doesn't know are refused
before anything changes on the server.

| Option | What it does |
|---|---|
| `apiKey` | The provider's key. It is saved on the server (encrypted with DPAPI on Windows, in a file only the server's user can read on Linux and macOS), never sent back, and only used by the run proxy. It replaces a saved key. Without it the server uses the key it has. |
| `budgetUsd` | The provider's hard spend cap, shared by every model of that provider. A new provider gets $5. On an existing provider this changes its cap. |
| `pricing` | `"auto"` (default) looks the price up in OpenRouter's catalog; or `{ input, output, cached }` in dollars per million tokens. |
| `name` | The profile's name. Default: model, vendor and reasoning effort. |
| `baseUrl` | The endpoint of an OpenAI-compatible server. Required for vendor `"custom"`. |
| `apiStyle` | `"openai-chat"`, `"openai-responses"` or `"anthropic"`, when the vendor offers several. |
| anything else | A profile setting: `ctx`, `max_output_tokens`, `reasoning_effort`, `temperature`, `top_p`, `api_style`, `extra_body`. `CLOUD_PARAMS` lists them. |

Local profiles are made in the dashboard or from Python (`llmdyno.local_model()`), because they involve choosing and
downloading a model file. `dyno.profile(nameOrId)` finds one by id or by exact name, ignoring case; it throws
`NotFoundError` when nothing matches and `ConflictError` when two profiles share the name. `dyno.profiles(kind?)`
lists them, optionally only `"local"` or `"cloud"` ones.

A `Profile` has `id`, `name`, `kind` (`"local"` or `"cloud"`), `params` (its settings) and `data` (everything the
server returned), and these methods:

| Method | What it does |
|---|---|
| `refresh()` | Read it again from the server. |
| `update(patch)` | Change the name, notes, tags, pricing or settings. `{ params: {...} }` replaces the settings. |
| `check(exact = false)` | Memory fit of a local profile: the verdict (`fits`, `tight`, `spill`, `oom`, …), projected VRAM and warnings. `exact: true` also runs llama.cpp's own fit check (about 2 seconds). |
| `test()` | The quick test: loads the model, measures speed and VRAM and checks tool calling (about 20 seconds locally; two short requests for a cloud model). |
| `duplicate(name?)` | A copy, optionally renamed. |
| `export()` | The profile as a portable JSON `Download`, without API keys. |
| `delete()` | Delete it. Results of past runs are kept. |

### Live events

```ts
const plan = await dyno.bench(qwen, { benchmarks: "t0_smoke_cli", wait: false });
for await (const ev of plan.watch({ transcript: true })) {
  if (ev.kind === "transcript") console.log(ev.data.ev);
  if (ev.kind === "run" && ev.finished) console.log("run", ev.runId, ev.status);
}
```

`dyno.watch(target, options)` (or `plan.watch(options)`) follows a plan, run or job until it stops. The target is a
`Plan`, `Run` or `Job`, or an id. Events arrive over the server's WebSocket, the same ones the dashboard shows. Each
`LiveEvent` has `kind`, `topic` (`plan:<id>`, `run:<id>` or `job:<id>`), `data`, `ts` (seconds since 1970),
`status`, `runId` and `finished`.

| Kind | What it is | When you get it |
|---|---|---|
| `plan` | The plan changed state. | Watching a plan. |
| `run` | A run changed state. | Watching a plan or a run. |
| `gpu` | A GPU sample. | Watching a plan, unless `gpu: false`. |
| `transcript` | One agent event. | With `transcript: true`, watching a plan or a run. |
| `proxy` | One model request. | With `transcript: true`, watching a plan or a run. |
| `job` | A job's progress. | Watching a job. |
| `log` | A line of a job's log. | Watching a job. |

| Option | Default | What it does |
|---|---|---|
| `transcript` | `false` | Also every agent event and model request. |
| `gpu` | `true` | GPU samples while a plan runs. |
| `pollMs` | `2000` | How often the state is polled as well. |
| `timeoutMs` | none | Stop after this long. |
| `signal` | none | An `AbortSignal` that stops the loop. |

The state is polled as well as watched, so status changes of the plan, its runs or a job still arrive if a proxy
blocks WebSockets. Transcript, proxy, GPU and log events come only over the WebSocket. `timeoutMs` and `signal` end
the loop quietly, without an error.

### Plans and runs

```ts
const [run] = await plan.runs();
await run.refresh();                         // status, stage, scores, time, tokens, cost
await run.transcript();                      // messages, thinking, tool calls and results
await run.files();                           // what the agent left in the workspace
await run.readFile("wordfreq.py");
await run.log({ stage: 1, stream: "stderr" });
await run.requests();                        // every model request: tokens, cost, latency
const zip = await run.download();            // { download: true, filename, mediaType, content: Uint8Array }
```

`dyno.plans()` lists every plan, newest first. `dyno.plan(id)`, `dyno.run(id)` and `dyno.job(id)` make handles
without a request.

| `Plan` method | What it does |
|---|---|
| `refresh()` | `{ id, name, status, counts, runs, job, … }` as it is now. |
| `status()` | `draft`, `queued`, `running`, `paused`, `done`, `failed` or `cancelled`. |
| `runs()` | Its runs as `Run` handles. |
| `watch(options)` | Live events until it stops (see above). |
| `wait({ onEvent?, transcript? })` | Wait until it stops, then return its `Results`. |
| `results(options)` | Scored results of this plan (see below). |
| `pause()`, `resume()`, `cancel()` | Pause after the runs in progress finish, continue, or stop. Finished results are kept. |
| `retry(statuses?)` | Queue the failed and cancelled runs again (or those with the given statuses). Returns how many. |
| `rename(name)` | Rename it. |
| `delete({ files? })` | Delete the plan and its runs, and by default their files. |
| `swebenchPredictions()` | Its SWE-bench patches in the standard predictions format (JSONL text). |
| `job` | The `Job` that runs it, while it runs. |

| `Run` method | What it does |
|---|---|
| `refresh()` | The run's summary: status, stage, scores, time, tokens, cost. |
| `status()` | `queued`, `running`, `grading`, `done`, `failed`, `cancelled` or `skipped`. |
| `transcript({ start?, limit? })` | The agent's events in order (default: the first 20 000). |
| `requests()` | Every model request through the proxy: tokens, cost, latency. |
| `files({ home? })` | Files in the workspace, or with `home: true` in the agent's home folder (configs, sessions). |
| `readFile(path, { home? })` | One file's text. |
| `log({ stage?, stream? })` | A harness log (default: stdout of stage 1). |
| `serverLog()` | The llama-server log of a local run. |
| `gpu(maxPoints = 600)` | GPU telemetry samples taken during the run. |
| `download()` | The workspace as a zip `Download`. |
| `cancel()` | Stop it. What it did so far is kept. |
| `retry()` | Run it again. Returns the `Job` that does it, if one started. |
| `regrade()` | Grade the finished workspace again (after fixing a grader, say) and return the new summary. |

A `Job` is any background task: a download, an image build, a plan, a review, an import. `job.refresh()` returns
`{ status, progress, detail, log, result, … }`, `job.cancel()` stops it, and
`job.wait({ pollMs?, timeoutMs?, onProgress? })` waits and returns its result. A job that ends failed, cancelled,
paused or interrupted (the server restarted while it ran) makes `wait()` throw.

### Results

```ts
const r = await dyno.results(plan, { quality: 40, passThreshold: 1 });   // quality here is a weight
r.leaderboard(); r.best(); r.runs(); r.cells(); r.reviews(); r.rubric(); r.agreement(); r.public();
await r.export({ level: "runs", fmt: "csv" });
await r.reference();                         // Artificial Analysis numbers next to yours (needs a key on the server)
```

`dyno.results(plans?, options)` takes a plan, a plan id or a list of them. With none it uses every plan except the
bundled sample. The options are the Results page's:

| Option | Default | What it does |
|---|---|---|
| `correctness`, `instructionFollowing`, `quality`, `efficiency` | 50, 15, 25, 10 | Weights of the final score. They are relative, so they need not add up to 100. |
| `qualityWeights` | `{ static: 35, probes: 30, review: 35 }` | How code quality splits between static analysis, behaviour probes and judge reviews. |
| `passThreshold` | `0.8` | The share of hidden tests a run must pass to count as a pass (for pass@k). |
| `efficiencyRef` | `"local"` | What speed and cost are compared with: the fastest local run, or `"all"` runs. |
| `benchmarks` | all | Only these benchmarks. |
| `includeSample` | `false` | Include the bundled sample results. |

`leaderboard()`, `runs()`, `cells()`, `reviews()`, `rubric()` and `public()` return rows; `rows(level)` returns any
of those tables by name. `agreement()` says how much the judges agree and whether any favours its own vendor.
`export({ level, fmt })` returns the dashboard's export as text, for `level` `"configs"`, `"cells"` or `"runs"` and
`fmt` `"csv"` or `"json"`. `toString()` prints the leaderboard.

`dyno.loadSample()` loads the bundled Round 1 study and returns its plan, so there is data to explore before you run
anything; `dyno.unloadSample()` removes it.

### Other calls

| Method | What it returns |
|---|---|
| `health()` | The server's health check: `{ ok, version, schema_version, time, data_dir }`. |
| `listBenchmarks()`, `listSuites()` | Built-in, custom and imported benchmarks; suites such as `suite_quick`. |
| `listHarnesses()` | Built-in and custom harnesses with their image status. |
| `listModels()` | Model files in the server's data folder. |
| `searchModels(q, { sort?, limit? })` | GGUF repositories on Hugging Face. |
| `specs(refresh = false)` | The server machine's hardware: CPU, RAM, GPUs, Docker. |
| `gpu()` | Live GPU usage on the server. |
| `server` | What the server said about itself on connect. |

### Every operation

Each of the 116 operations of the web API is a typed method under `dyno.api`, grouped by the server's 13 areas
(benchmarks, harnesses, imports, judging, models, plans, profiles, providers, references, results, runs, settings and
system):

```ts
await dyno.api.models.hubSearch({ q: "qwen coder gguf", limit: 5 });
await dyno.api.harnesses.harnessDockerfile({ hid: "pi" });
await dyno.api.system.getSpecs({ refresh: true });
await dyno.api.providers.setProviderKey({ pid, body: { api_key: key } });
```

The [web API map](reference/web-api.md) lists every method with its route and its Python equivalent. Each method
takes one object:

- **path parameters** (`rid`, `pid`, `hid`, …) by name; a missing one throws `InvalidError`;
- **query parameters** by name; booleans are sent as `"true"` or `"false"`;
- **a JSON body** as `body`;
- **an upload** (only `benchmarks.importBenchmarkZip`) as `data`: a `Blob`, `Uint8Array` or `ArrayBuffer`.

Unknown keys throw `InvalidError` listing the ones that operation accepts. Responses are parsed JSON, text, or a
`Download` for files the server sends as attachments. `dyno.call("runs.get_run", { rid })` reaches the same
operations by their service name, and `ROUTES` holds the whole table.

The list is generated from the server's own routes by `scripts/gen_js_client.py`. A test fails when the server gains
an operation the client doesn't have, so the JavaScript and Python clients can't drift apart.

### Errors

The client throws the same errors as the Python library. All of them are `LLMDynoError`s with the HTTP `status`:

| Error | Status | When |
|---|---|---|
| `InvalidError` | 400, 422 | A bad argument or setting. |
| `ForbiddenError` | 401, 403 | A missing or wrong access token, or an action that isn't allowed. |
| `NotFoundError` | 404 | No such profile, plan, run, … |
| `ConflictError` | 409 | The state doesn't allow it: a name used twice, a plan that is still running. |
| `RiskNotAcknowledgedError` | 428 | The server wants `acknowledge_risks` for a call made through `dyno.api`. |
| `RateLimitError` | 429 | A provider or Hugging Face is rate-limiting. |
| `UpstreamError` | 502 | A provider, Hugging Face or Docker failed. |
| `InsufficientStorageError` | 507 | Not enough disk space for a download or image. |
| `PreflightError` | 409 | `bench()` was blocked. It has `problems`, `warnings` and the full `report`. |
| `LLMDynoError` | 503 | No server answers at that address. |

`bench()` reports danger warnings that need `acknowledgeRisks` as a `PreflightError` too, with a note saying so.

## Benchmark your own TypeScript agent

`node_harness()` turns a JavaScript or TypeScript function into a harness. Your agent then runs in the same offline
sandbox as the built-in harnesses, reaching the model only through LLMDyno's proxy, so transcripts, token counts,
budgets and grading work the same way. You register it from Python or the command line:

```python
h = llmdyno.node_harness("vercel_ai_agent.ts:run", source="examples/agents/ts/vercel_ai_agent.ts")
llmdyno.bench(qwen, "suite_quick", harnesses=[h.id, "pi"])
```

```bash
llmdyno node-harness vercel_ai_agent.ts:run --source examples/agents/ts/vercel_ai_agent.ts --build
```

Then benchmark it from Python, the dashboard or the JavaScript client like any other harness. Its id is `js-` plus
the entry file's name in lower case, with anything other than letters, digits and dashes turned into dashes
(`js-vercel-ai-agent`), unless you pass `id=`.

The function is called once per stage, in the task's workspace, with one object:

```ts
interface Task {
  prompt: string; model: string; baseUrl: string; apiKey: string; workspace: string;
  stage: number; ctx?: number; maxTokens?: number; reasoning?: string;
}
export async function run(task: Task): Promise<string> { /* … */ }
```

- **`baseUrl`** is LLMDyno's OpenAI-compatible proxy. `apiKey` is a placeholder, because the proxy adds the real key.
- **The return value** is printed: a string as it is, anything else as JSON, nothing for `null` or `undefined`. The
  function may be synchronous. The process exits right after printing, so finish any background work first.
- **The entry point** is `"file.ts:name"`; `.mts`, `.js` and `.mjs` work too. Without a name, LLMDyno calls the `run`
  export or the default export.
- **TypeScript runs as it is.** The sandbox runs Node 24, which runs TypeScript directly by removing the types. Stick
  to type annotations: no enums, namespaces or constructor parameter properties. In a project with several files, use
  `.ts` extensions in relative imports and `import type` for imports that are only types.
- **Dependencies:**
  - `packages=` lists the npm packages to install; pin them (`"ai@7.0.179"`).
  - When you leave it out, the entry file's `export const PACKAGES = [...]` is used. `packages=[]` installs nothing.
  - A `package.json` in the source folder is installed too, without its devDependencies. Without one, LLMDyno writes
    a minimal `package.json` with `"type": "module"`.
- **A whole project:** pass `source=` a folder and give the entry point relative to it. `node_modules`, `.git`,
  `dist`, `build`, `.next`, `.turbo` and `coverage` are left out, and the rest must stay under 4 MB. With a single
  file as `source=`, only that file is copied.
- **Stages:** each stage starts a fresh process (`multi_stage="fresh"`). The workspace carries over between stages.

The harness image is built the first time it is needed, or straight away with `build=True`.

Ready-made agents are in
[examples/agents/ts](https://github.com/speak2jerome/llmdyno/tree/main/examples/agents/ts). Each one passed a strict
type check and an end-to-end run against a scripted model. The Vercel AI SDK agent also ran a real benchmark on a local
Qwen3.8 27B: it scored 98.9, with every hidden test passing.

| Framework | Template | Packages |
|---|---|---|
| Vercel AI SDK | `vercel_ai_agent.ts` | `ai`, `@ai-sdk/openai-compatible`, `zod` |
| Mastra | `mastra_agent.ts` | `@mastra/core`, `@ai-sdk/openai-compatible`, `zod` |
| LangGraph.js | `langgraph_agent.ts` | `@langchain/langgraph`, `@langchain/openai`, `@langchain/core`, `zod` |
| OpenAI Agents SDK | `openai_agents_agent.ts` | `@openai/agents`, `openai`, `zod` |

Python agents work the same way with `python_harness()`: see [Integrations](INTEGRATIONS.md#your-own-agent).

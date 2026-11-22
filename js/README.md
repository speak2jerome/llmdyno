# llmdyno for JavaScript and TypeScript

[LLMDyno](https://github.com/speak2jerome/llmdyno) is an open-source benchmark for running local and cloud LLMs as
coding agents. It runs real agent harnesses on multi-file coding tasks in offline Docker sandboxes. Hidden tests grade
the result and blind LLM judges review the code, alongside speed, VRAM and cost.

This package gives you two things:

- **A typed client.** It drives a LLMDyno server from Node 22 or later, with the same calls as the Python library.
- **`npx llmdyno`.** It starts that server for you.

LLMDyno itself is a Python app that runs agents in Docker, so you need Python 3.11+ and Docker on the machine that
runs the benchmarks.

## Start the server

```bash
npx llmdyno            # starts LLMDyno and opens the dashboard at http://127.0.0.1:8777
npx llmdyno doctor     # any other argument goes to the LLMDyno command line
```

`npx llmdyno` uses an installed LLMDyno if your Python has one. Otherwise it runs the matching version through
[uv](https://docs.astral.sh/uv/) or [pipx](https://pipx.pypa.io/). If none of those is installed, it tells you what to
install.

## Use it from code

```bash
npm install llmdyno
```

```ts
import { connect } from "llmdyno";

const dyno = await connect();               // http://127.0.0.1:8777, or LLMDYNO_URL and LLMDYNO_TOKEN

const gpt = await dyno.cloudModel("openai", "gpt-6-luna", { reasoning_effort: "low", budgetUsd: 2 });
const results = await dyno.bench([gpt, "Qwen3.8 27B Q3_K_XL 32k"], {
  benchmarks: "suite_quick",
  harnesses: "pi",
  onEvent: (ev) => { if (ev.kind === "run" && ev.finished) console.log(ev.data.benchmark_id, ev.status); },
});

console.log(results.toString());            // the leaderboard
console.table(results.leaderboard());
```

Follow a plan live, then look inside its runs:

```ts
const plan = await dyno.bench("Qwen3.8 27B Q3_K_XL 32k", { benchmarks: "t0_smoke_cli", wait: false });
for await (const ev of plan.watch({ transcript: true })) {
  if (ev.kind === "transcript") console.log(ev.data.ev);
}
const [run] = await plan.runs();
console.log(await run.transcript());
console.log(await run.readFile("wordfreq.py"));
```

Every operation of the web API is also available, typed, under `dyno.api`:

```ts
await dyno.api.models.hubSearch({ q: "qwen coder gguf", limit: 5 });
await dyno.api.runs.runGpu({ rid: run.id, max_points: 200 });
```

The library raises the same errors as the Python one: `NotFoundError`, `ConflictError`, `InvalidError`,
`PreflightError` and the rest, each with the HTTP `status`.

It uses only `fetch` and `WebSocket`. Other runtimes that have both, such as Bun and Deno, should work but aren't
tested. In a browser it works only on pages that the LLMDyno server serves itself, because the server sends no CORS
headers.

On another machine, start the server with `llmdyno serve --host 0.0.0.0`. Then connect with its access token:
`connect("http://gpu-box:8777", { token })`.

## Benchmark your own TypeScript agent

An agent built with the Vercel AI SDK, Mastra, LangChain.js or the OpenAI Agents SDK can run in LLMDyno's sandbox and
be graded like the built-in harnesses. Register it from Python with `llmdyno.node_harness("agent.ts:run")`. Templates
for each framework are in
[examples/agents/ts](https://github.com/speak2jerome/llmdyno/tree/main/examples/agents/ts).

## Links

- [Documentation](https://speak2jerome.github.io/llmdyno/JAVASCRIPT/)
- [Source and issues](https://github.com/speak2jerome/llmdyno)
- [Python package](https://pypi.org/project/llmdyno/)
- [Project page at Zynxtech](https://zynxtech.in/projects/llmdyno/)

MIT licensed. LLMDyno is part of [Zynxtech open source](https://zynxtech.in/), built by [Jerome Eliezer](https://zynxtech.in/about/).

/**
 * LLMDyno from JavaScript and TypeScript: a client for a LLMDyno server, with the same calls as the Python library.
 *
 *     import { connect } from "llmdyno";
 *
 *     const dyno = await connect();                      // http://127.0.0.1:8777, or LLMDYNO_URL / LLMDYNO_TOKEN
 *     const gpt = await dyno.cloudModel("openai", "gpt-6-luna", { reasoning_effort: "low" });
 *     const results = await dyno.bench([gpt, "Qwen3.8 27B Q3_K_XL 32k"], { benchmarks: "suite_quick" });
 *     console.log(results.toString());
 *
 * Start a server with `npx llmdyno` (it runs the Python package through uv or pipx) or `llmdyno serve`.
 */
export { Client, connect } from "./client.ts";
export type { BenchOptions, ClientOptions, CloudModelOptions, Download } from "./client.ts";
export {
  ConflictError, ForbiddenError, InsufficientStorageError, InvalidError, LLMDynoError, NotFoundError, PreflightError,
  RateLimitError, RiskNotAcknowledgedError, UpstreamError,
} from "./errors.ts";
export { Job, Plan, Profile, Run, RUN_FINISHED, TERMINAL } from "./handles.ts";
export type { Json } from "./handles.ts";
export { watch } from "./live.ts";
export type { LiveEvent, WatchOptions, WatchTarget } from "./live.ts";
export { Results } from "./results.ts";
export type { Level, ResultsOptions } from "./results.ts";
export { API_METHODS, CLOUD_PARAMS, LOCAL_PARAMS, ROUTES, SAMPLING_PARAMS } from "./generated.ts";
export type { Api, Operation, Route } from "./generated.ts";
export { VERSION } from "./version.ts";

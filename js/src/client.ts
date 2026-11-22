import { API_METHODS, CLOUD_PARAMS, ROUTES, type Api, type Operation, type Route } from "./generated.ts";
import { ConflictError, InvalidError, LLMDynoError, NotFoundError, PreflightError, httpError } from "./errors.ts";
import { Job, Plan, Profile, Run, type Json } from "./handles.ts";
import { watch, type LiveEvent, type WatchOptions, type WatchTarget } from "./live.ts";
import { Results, type ResultsOptions } from "./results.ts";
import { VERSION } from "./version.ts";

/** A file the server sent as a download (a run's workspace zip, an export, a log …). */
export interface Download {
  download: true;
  filename: string;
  mediaType: string;
  /** Text for text, JSON and CSV files; bytes for everything else (zip archives). */
  content: string | Uint8Array;
}

/** Options for connect() and new Client(). */
export interface ClientOptions {
  /** The server's access token. Only needed from another machine (see `llmdyno token` on the server). */
  token?: string;
  /** Milliseconds before a single request gives up (default 120 000). Long work runs as jobs, so calls are short. */
  timeoutMs?: number;
  /** A fetch to use instead of the global one (tests, proxies). */
  fetch?: typeof fetch;
  /** A WebSocket class to use instead of the global one, for live events. */
  WebSocket?: typeof WebSocket;
}

/** Options for bench() and preflight(): what to run and the plan's limits. */
export interface BenchOptions {
  /** Benchmark or suite ids (default "suite_quick"); see listBenchmarks() and listSuites(). */
  benchmarks?: string | string[];
  /** Harness ids (default "pi"): pi, opencode, codex, qwen-code, crush, aider, mini-swe-agent, or your own. */
  harnesses?: string | string[];
  /** Runs of each profile × harness × benchmark (default 1; 3 or more gives confidence intervals). */
  iterations?: number;
  /** The plan's name (default: one with the date). */
  name?: string;
  /** Caps this plan's cloud spend, on top of each provider's own cap. */
  budgetUsd?: number;
  /** Run the code-quality checks after grading (default true). */
  quality?: boolean;
  /** Multiplies every benchmark's time limit (default 1), for slow machines or CPU-only models. */
  timeoutMultiplier?: number;
  /** Cloud runs in parallel (default: the server's cloud_concurrency setting, 3). */
  cloudConcurrency?: number;
  /** Let local profiles run although their memory check says they spill out of VRAM; the results are flagged. */
  allowSpill?: boolean;
  /** Start even with danger warnings (VRAM spill, out of memory …); the results are flagged. */
  acknowledgeRisks?: boolean;
  /** Called with every live event while the plan runs (see watch()). */
  onEvent?: (event: LiveEvent) => void;
}

/** Options for cloudModel(). */
export interface CloudModelOptions {
  /**
   * Saved on the server (encrypted with DPAPI on Windows, in a file only its user can read elsewhere), never sent
   * back, and only ever used by its proxy. It replaces a saved key. Omit it to use the key the server has.
   */
  apiKey?: string;
  /** The profile's name (default: model · vendor · reasoning effort). */
  name?: string;
  /** The endpoint of an OpenAI-compatible server; required for vendor "custom". */
  baseUrl?: string;
  /** Which API to speak when the vendor offers several: "openai-chat", "openai-responses" or "anthropic". */
  apiStyle?: string;
  /**
   * Hard spend cap of the provider, shared by every model of that provider (a new provider gets $5). On an existing
   * provider this changes its cap.
   */
  budgetUsd?: number;
  /** "auto" looks the price up (OpenRouter's catalog), or give {input, output, cached} in $ per 1M tokens. */
  pricing?: "auto" | { input?: number; output?: number; cached?: number };
  /** Other profile settings, as in Python: ctx, max_output_tokens, reasoning_effort, temperature, top_p, extra_body. */
  [setting: string]: unknown;
}

type ModelRef = Profile | string;

const env = (name: string): string | undefined =>
  (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env?.[name];

const asList = <T>(x: T | T[] | undefined): T[] => (x === undefined ? [] : Array.isArray(x) ? x : [x]);

function warn(message: string): void {
  const proc = (globalThis as { process?: { emitWarning?: (m: string) => void } }).process;
  if (proc?.emitWarning) proc.emitWarning(message);
  else console.warn(message);
}

/**
 * A connection to a LLMDyno server: the same calls as the Python library, from JavaScript or TypeScript.
 * Every operation of the web API is also available, typed, under `api` (dyno.api.runs.runTranscript({ rid })).
 */
export class Client {
  /** The server's address, without a trailing slash. */
  readonly url: string;
  /** The access token sent with every request, if any. */
  readonly token: string | undefined;
  /** What the server said about itself on connect: version, data folder, … */
  server: Record<string, unknown> = {};
  /** Every web API operation, grouped by area. */
  readonly api: Api;
  /** Milliseconds before a single request gives up. */
  readonly timeoutMs: number;
  /** The WebSocket class used for live events (undefined: events are polled only). */
  readonly WebSocket: typeof WebSocket | undefined;
  private readonly fetchImpl: typeof fetch;

  /**
   * A client for the server at `url`. Prefer connect(), which also reads LLMDYNO_URL and LLMDYNO_TOKEN and checks
   * that the server answers; this constructor does neither.
   */
  constructor(url: string, options: ClientOptions = {}) {
    this.url = url.replace(/\/+$/, "");
    this.token = options.token;
    this.timeoutMs = options.timeoutMs ?? 120_000;
    this.fetchImpl = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.WebSocket = options.WebSocket ?? (globalThis as { WebSocket?: typeof WebSocket }).WebSocket;
    const api: Record<string, Record<string, (params?: Record<string, unknown>) => Promise<unknown>>> = {};
    for (const [area, methods] of Object.entries(API_METHODS)) {
      api[area] = {};
      for (const [name, op] of Object.entries(methods)) {
        api[area][name] = (params?: Record<string, unknown>) => this.call(op, params ?? {});
      }
    }
    this.api = api as unknown as Api;
  }

  toString(): string {
    return `LLMDyno at ${this.url}`;
  }

  // ---------------------------------------------------------------- transport
  /** Call one operation by its service name ("runs.run_transcript"), with its path, query and body parameters. */
  async call(op: Operation | string, params: Record<string, unknown> = {}): Promise<any> {
    const route = (ROUTES as Record<string, Route>)[op];
    if (!route) throw new InvalidError(`${op} is not an operation of the LLMDyno web API`);
    let path = route.path;
    const query = new URLSearchParams();
    let body: unknown;
    let file: unknown;
    for (const [key, value] of Object.entries(params)) {
      const where = route.params[key];
      if (!where) throw new InvalidError(`${op} takes no ${key}; it takes ${Object.keys(route.params).join(", ") || "no parameters"}`);
      if (value === undefined || value === null) continue;
      if (where === "path") path = path.replace(`{${key}}`, encodeURIComponent(String(value)));
      else if (where === "query") query.set(key, String(value));
      else if (where === "body") body = value;
      else file = value;
    }
    const missing = path.match(/\{(\w+)\}/);
    if (missing) throw new InvalidError(`${op} needs ${missing[1]}`);
    const headers: Record<string, string> = {};
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    let payload: BodyInit | undefined;
    if (file !== undefined) {
      const form = new FormData();
      form.append("file", file instanceof Blob ? file : new Blob([file as BlobPart], { type: "application/zip" }), "benchmark.zip");
      payload = form;
    } else if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
    const qs = query.toString();
    return this.request(route.method, path + (qs ? `?${qs}` : ""), headers, payload);
  }

  private async request(method: string, path: string, headers: Record<string, string>, body?: BodyInit): Promise<any> {
    let response: Response;
    try {
      response = await this.fetchImpl(this.url + path, {
        method, headers, body, signal: AbortSignal.timeout(this.timeoutMs),
      });
    } catch (e) {
      const why = e instanceof Error ? `${e.name}: ${e.message}` : String(e);
      throw new LLMDynoError(`cannot reach LLMDyno at ${this.url}: ${why}`, 503);
    }
    return Client.result(response);
  }

  private static async result(r: Response): Promise<any> {
    const ctype = r.headers.get("content-type") ?? "";
    if (r.status >= 400) {
      let detail: unknown;
      const text = await r.text();
      if (ctype.includes("json")) {
        try {
          detail = (JSON.parse(text) as { detail?: unknown }).detail;
        } catch {
          detail = undefined;
        }
      }
      throw httpError(r.status, detail ?? (text || `HTTP ${r.status}`));
    }
    const disposition = r.headers.get("content-disposition") ?? "";
    if (disposition.includes("attachment")) {
      const name = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? "download";
      const media = ctype.split(";")[0].trim();
      const textual = media.startsWith("text/") || media === "application/json" || media === "application/x-ndjson";
      const content = textual ? await r.text() : new Uint8Array(await r.arrayBuffer());
      return { download: true, filename: name, mediaType: media, content } satisfies Download;
    }
    if (ctype.includes("json")) return r.json();
    return r.text();
  }

  /** The server's health check: {ok, version, …}. */
  async health(): Promise<Record<string, unknown>> {
    return this.request("GET", "/api/health", this.token ? { Authorization: `Bearer ${this.token}` } : {});
  }

  /** Follow a plan, run or job live until it stops (the dashboard's events). See LiveEvent for the event kinds. */
  watch(target: WatchTarget, options: WatchOptions = {}): AsyncGenerator<LiveEvent> {
    return watch(this, target, options);
  }

  // ---------------------------------------------------------------- profiles
  /** Every profile (optionally only "local" or "cloud" ones). */
  async profiles(kind?: "local" | "cloud"): Promise<Profile[]> {
    const rows: Json[] = await this.call("profiles.list_profiles");
    return rows.filter((p) => !kind || p.kind === kind).map((p) => new Profile(this, p));
  }

  /** A profile by id or exact name (case-insensitive). */
  async profile(nameOrId: ModelRef): Promise<Profile> {
    if (nameOrId instanceof Profile) return nameOrId;
    const rows: Json[] = await this.call("profiles.list_profiles");
    let hit = rows.filter((p) => p.id === nameOrId);
    if (!hit.length) hit = rows.filter((p) => String(p.name).toLowerCase() === nameOrId.toLowerCase());
    if (!hit.length) {
      const names = rows.slice(0, 12).map((p) => JSON.stringify(p.name)).join(", ");
      throw new NotFoundError(`no profile ${JSON.stringify(nameOrId)}${names ? `; there are: ${names}` : ""}`, 404);
    }
    if (hit.length > 1) throw new ConflictError(`${hit.length} profiles are called ${JSON.stringify(nameOrId)}; use the id`, 409);
    return new Profile(this, hit[0]);
  }

  /**
   * A cloud model to benchmark, e.g. cloudModel("anthropic", "claude-sonnet-5-5", { reasoning_effort: "low" }).
   * Calling it again with the same arguments returns the same profile. The API key, if you pass one, is saved on
   * the server for that provider; without one the server uses the key it already has.
   */
  async cloudModel(vendor: string, model: string, options: CloudModelOptions = {}): Promise<Profile> {
    const { apiKey, name, baseUrl, apiStyle, budgetUsd, pricing = "auto", ...settings } = options;
    const vendors: Json[] = await this.call("providers.list_vendors");
    const v = vendors.find((x) => x.id === vendor);
    if (!v) throw new InvalidError(`unknown vendor ${JSON.stringify(vendor)}; one of: ${vendors.map((x) => x.id).join(", ")}`);
    if (vendor === "custom" && !baseUrl) {
      throw new InvalidError("a custom provider needs baseUrl, e.g. http://host.docker.internal:11434/v1 for Ollama");
    }
    for (const key of Object.keys(settings)) {
      if (!CLOUD_PARAMS.includes(key)) {
        throw new InvalidError(`unknown cloud setting ${JSON.stringify(key)}; known: ${CLOUD_PARAMS.join(", ")}`);
      }
    }
    const providers: Json[] = await this.call("providers.list_providers");
    let prov: Json;
    const found = providers.find((p) => p.vendor === vendor && (!baseUrl || p.base_url === baseUrl));
    if (found) {
      prov = found;
      const patch: Json = {};
      if (budgetUsd !== undefined && Number(budgetUsd) !== prov.budget_usd) patch.budget_usd = Number(budgetUsd);
      if (apiStyle && apiStyle !== prov.api_style) patch.api_style = apiStyle;
      if (Object.keys(patch).length) prov = await this.call("providers.patch_provider", { pid: prov.id, body: patch });
      if (apiKey) prov = await this.call("providers.set_provider_key", { pid: prov.id, body: { api_key: apiKey } });
    } else {
      const body: Json = { vendor, budget_usd: budgetUsd ?? 5 };
      if (baseUrl) body.base_url = baseUrl;
      if (apiStyle) body.api_style = apiStyle;
      if (apiKey) body.api_key = apiKey;
      prov = await this.call("providers.create_provider", { body });
    }
    if (!v.key_optional && !prov.has_key) {
      throw new InvalidError(`no API key for ${v.name}: pass apiKey, or add one on the server (Settings > Providers)`);
    }
    let price: Json = {};
    if (pricing === "auto") {
      if (vendor !== "custom") {
        const hit = (await this.call("providers.pricing_lookup", { vendor, model })).match;
        if (hit) for (const k of ["input", "output", "cached"]) if (hit[k] != null) price[k] = hit[k];
      }
    } else {
      price = { ...pricing };
    }
    const params: Json = Object.fromEntries(Object.entries(settings).filter(([, x]) => x !== undefined && x !== null));
    const effort = params.reasoning_effort;
    const defaultName = `${model} · ${String(v.name).split(" (")[0]}${effort ? ` · ${effort}` : ""}`;
    return this.upsertProfile({
      kind: "cloud", name: name ?? defaultName, provider_id: prov.id, remote_model: model, params, pricing: price,
    });
  }

  private async upsertProfile(body: Json): Promise<Profile> {
    const rows: Json[] = await this.call("profiles.list_profiles");
    const same = rows.find((p) => String(p.name).toLowerCase() === String(body.name).toLowerCase());
    if (!same) return new Profile(this, await this.call("profiles.create_profile", { body }));
    if (same.kind !== body.kind) {
      throw new ConflictError(`a ${same.kind} profile is already called ${JSON.stringify(body.name)}; pass another name`, 409);
    }
    if (body.kind === "cloud" && body.provider_id !== same.provider_id) {
      throw new ConflictError(`profile ${JSON.stringify(body.name)} uses another provider; pass another name`, 409);
    }
    const patch: Json = { params: body.params ?? {} };
    for (const k of ["pricing", "remote_model"]) if (body[k] != null) patch[k] = body[k];
    return new Profile(this, await this.call("profiles.patch_profile", { pid: same.id, body: patch }));
  }

  // ---------------------------------------------------------------- plans
  private async planBody(models: ModelRef | ModelRef[], options: BenchOptions): Promise<Json> {
    const ids: string[] = [];
    for (const m of asList(models)) ids.push((await this.profile(m)).id);
    if (!ids.length) throw new InvalidError("pass at least one model (a Profile, or a profile name or id)");
    const opts: Json = {
      budget_usd: options.budgetUsd, quality: options.quality ?? true, timeout_multiplier: options.timeoutMultiplier,
      cloud_concurrency: options.cloudConcurrency, allow_spill: options.allowSpill || undefined,
    };
    return {
      name: options.name ?? "", profile_ids: ids, harness_ids: asList(options.harnesses ?? "pi"),
      benchmark_ids: asList(options.benchmarks ?? "suite_quick"), iterations: options.iterations ?? 1,
      options: Object.fromEntries(Object.entries(opts).filter(([, x]) => x !== undefined && x !== null)),
    };
  }

  /** What bench() would check before starting: blocking problems, warnings, and time and cost estimates. */
  async preflight(models: ModelRef | ModelRef[], options: BenchOptions = {}): Promise<Json> {
    return this.call("plans.plan_preflight", { body: await this.planBody(models, options) });
  }

  /**
   * Run models × harnesses × benchmarks × iterations and return the scored Results (or, with wait: false, the
   * running Plan). The plan is checked first: PreflightError lists anything that blocks it.
   */
  async bench(models: ModelRef | ModelRef[], options?: BenchOptions & { wait?: true }): Promise<Results>;
  async bench(models: ModelRef | ModelRef[], options: BenchOptions & { wait: false }): Promise<Plan>;
  async bench(models: ModelRef | ModelRef[], options: BenchOptions & { wait?: boolean } = {}): Promise<Results | Plan> {
    const body = await this.planBody(models, options);
    const pf = await this.call("plans.plan_preflight", { body });
    const texts = (xs: Json[] | undefined) => (xs ?? []).map((x) => String(x.text));
    if (!pf.ok) throw new PreflightError(texts(pf.blocking), texts(pf.warnings), pf);
    const risky = (pf.warnings ?? []).filter((w: Json) => w.ack).map((w: Json) => String(w.text));
    if (risky.length && !options.acknowledgeRisks) {
      throw new PreflightError([...risky, "pass acknowledgeRisks: true to run anyway (results will be flagged)"],
        texts(pf.warnings), pf);
    }
    const created = await this.call("plans.create_plan", {
      body: { ...body, start: true, acknowledge_risks: Boolean(options.acknowledgeRisks) },
    });
    const plan = new Plan(this, created.plan_id, created.job_id);
    if (options.wait === false) return plan;
    return plan.wait({ onEvent: options.onEvent });
  }

  /** Every plan, newest first. */
  async plans(): Promise<Plan[]> {
    const rows: Json[] = await this.call("plans.list_plans");
    return rows.map((p) => new Plan(this, p.id));
  }

  /** A plan by id. */
  plan(id: string): Plan {
    return new Plan(this, id);
  }

  /** A run by id. */
  run(id: string): Run {
    return new Run(this, id);
  }

  /** A background job by id (downloads, image builds, plans, reviews …). */
  job(id: string): Job {
    return new Job(this, id);
  }

  /** Scored results for some plans (default: every plan except the bundled sample), with the Results page's options. */
  async results(plans?: Plan | string | Array<Plan | string>, options: ResultsOptions = {}): Promise<Results> {
    return Results.load(this, asList(plans).map((p) => (typeof p === "string" ? p : p.id)), options);
  }

  // ---------------------------------------------------------------- catalog and system
  /** Built-in, custom and imported benchmarks. */
  listBenchmarks(): Promise<Json[]> {
    return this.call("benchmarks.list_benchmarks");
  }

  /** Benchmark suites (suite_quick, …). */
  listSuites(): Promise<Json[]> {
    return this.call("benchmarks.list_suites");
  }

  /** Agent harnesses, built-in and your own, with their image status. */
  listHarnesses(): Promise<Json[]> {
    return this.call("harnesses.list_harnesses");
  }

  /** Model files in the server's data folder. */
  listModels(): Promise<Json[]> {
    return this.call("models.list_models");
  }

  /** Search Hugging Face for GGUF models. */
  searchModels(q: string, options: { sort?: string; limit?: number } = {}): Promise<Json[]> {
    return this.call("models.hub_search", { q, ...options });
  }

  /** The server machine's hardware: CPU, RAM, GPUs, Docker. */
  specs(refresh = false): Promise<Json> {
    return this.call("system.get_specs", { refresh });
  }

  /** Live GPU usage on the server. */
  gpu(): Promise<Json> {
    return this.call("system.system_gpu");
  }

  /** Load the bundled Round 1 results so there is data to explore without running anything; returns its plan. */
  async loadSample(): Promise<Plan> {
    const status = await this.call("results.sample_status");
    const pid = status.loaded ? status.plan_id : (await this.call("results.load_sample")).plan_id;
    return new Plan(this, pid);
  }

  /** Remove the bundled sample plan, its runs, reviews and profiles. */
  async unloadSample(): Promise<void> {
    await this.call("results.unload_sample");
  }
}

/**
 * Connect to a LLMDyno server (default: LLMDYNO_URL, or http://127.0.0.1:8777 on this machine). The token defaults to
 * LLMDYNO_TOKEN; the server's own machine needs none. Start a server with `npx llmdyno` or `llmdyno serve`.
 */
export async function connect(url?: string, options: ClientOptions = {}): Promise<Client> {
  const target = url ?? env("LLMDYNO_URL") ?? "http://127.0.0.1:8777";
  const client = new Client(target, { ...options, token: options.token ?? env("LLMDYNO_TOKEN") });
  let info: Record<string, unknown>;
  try {
    info = await client.health();
  } catch (e) {
    if (e instanceof LLMDynoError && (e.status === 401 || e.status === 403)) {
      throw new LLMDynoError(`${target} refused the connection: ${e.message}. Pass { token } (shown by \`llmdyno token\` `
        + "on the server) or set LLMDYNO_TOKEN.", e.status);
    }
    if (e instanceof LLMDynoError && e.status === 503 && !url && !env("LLMDYNO_URL")) {
      throw new LLMDynoError(`${e.message}. Start it with \`npx llmdyno\` (or \`llmdyno serve\`), or pass the server's URL.`, 503);
    }
    throw e;
  }
  if (!info || info.ok !== true) throw new LLMDynoError(`${target} does not look like a LLMDyno server`);
  const theirs = String(info.version ?? "").split(".").slice(0, 2).join(".");
  const ours = VERSION.split(".").slice(0, 2).join(".");
  if (theirs !== ours) {
    warn(`the server runs LLMDyno ${String(info.version)} and this client is ${VERSION}; calls that changed between them may fail`);
  }
  client.server = info;
  return client;
}

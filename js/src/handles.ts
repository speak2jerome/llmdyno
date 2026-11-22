import type { Client, Download } from "./client.ts";
import { LLMDynoError } from "./errors.ts";
import type { LiveEvent, WatchOptions } from "./live.ts";
import type { Results, ResultsOptions } from "./results.ts";

/** A JSON object from the server. The fields are documented in the Python library's reference. */
export type Json = Record<string, any>;

/**
 * Statuses after which a plan or job does nothing more until someone acts. A job is "interrupted" when the server
 * restarted while it ran.
 */
export const TERMINAL = ["done", "failed", "cancelled", "paused", "interrupted"] as const;
/** Statuses of a run that has finished. */
export const RUN_FINISHED = ["done", "failed", "cancelled", "skipped"] as const;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** A model profile: a model plus its exact settings. */
export class Profile {
  /** The profile's id (prof_…). */
  readonly id: string;
  /** Everything the server knows about it, as of the last refresh. */
  data: Json;
  private readonly client: Client;

  /** Wrap a profile row; use dyno.profile(), profiles() or cloudModel() to get one. */
  constructor(client: Client, data: Json) {
    this.client = client;
    this.id = data.id;
    this.data = data;
  }

  /** The profile's name. */
  get name(): string {
    return this.data.name;
  }

  /** "local" (llama.cpp) or "cloud". */
  get kind(): string {
    return this.data.kind;
  }

  /** Its settings: ctx, KV cache, offload, sampling, reasoning … */
  get params(): Json {
    return this.data.params ?? {};
  }

  toString(): string {
    return `Profile ${this.name} (${this.id})`;
  }

  /** Read it again from the server. */
  async refresh(): Promise<this> {
    this.data = await this.client.call("profiles.get_profile", { pid: this.id });
    return this;
  }

  /** Change the name, notes, tags, pricing or settings ({ params: {...} } replaces the settings). */
  async update(patch: Json): Promise<this> {
    this.data = await this.client.call("profiles.patch_profile", { pid: this.id, body: patch });
    return this;
  }

  /** Memory fit of a local profile: verdict ("fits", "tight", "spill", "oom" …), projected VRAM and warnings. */
  async check(exact = false): Promise<Json> {
    if (this.kind !== "local") throw new LLMDynoError("memory checks are for local profiles");
    return this.client.call("profiles.check_profile", {
      body: { model_id: this.data.model_id, params: this.params, exact, profile_id: this.id },
    });
  }

  /** The quick test (about 20 s locally): loads the model, measures speed and VRAM, checks tool calling. */
  async test(): Promise<Json> {
    const { job_id } = await this.client.call("profiles.smoke_profile", { pid: this.id });
    const result = await new Job(this.client, job_id).wait();
    await this.refresh();
    return result;
  }

  /** A copy, optionally with a new name. */
  async duplicate(name?: string): Promise<Profile> {
    let copy = new Profile(this.client, await this.client.call("profiles.duplicate_profile", { pid: this.id }));
    if (name) copy = await copy.update({ name });
    return copy;
  }

  /** The profile as a portable JSON file (no API keys). */
  export(): Promise<Download> {
    return this.client.call("profiles.export_profile", { pid: this.id });
  }

  /** Delete the profile. Results of past runs are kept; the server refuses while its runs are queued or running. */
  async delete(): Promise<void> {
    await this.client.call("profiles.delete_profile", { pid: this.id });
  }
}

/** A background task: a download, image build, plan, review or import. */
export class Job {
  /** The job's id. */
  readonly id: string;
  private readonly client: Client;

  /** A handle on job `id`; dyno.job(id) makes one. */
  constructor(client: Client, id: string) {
    this.client = client;
    this.id = id;
  }

  toString(): string {
    return `Job ${this.id}`;
  }

  /** {status, progress, detail, log, result, …} as it is now. */
  refresh(): Promise<Json> {
    return this.client.call("system.get_job", { jid: this.id });
  }

  /** Stop the job. A download pauses and can be resumed. */
  async cancel(): Promise<void> {
    await this.client.call("system.cancel_job", { jid: this.id });
  }

  /** Wait until the job ends and return its result; a failed, cancelled, paused or interrupted job throws. */
  async wait(options: { pollMs?: number; timeoutMs?: number; onProgress?: (job: Json) => void } = {}): Promise<Json> {
    const deadline = options.timeoutMs ? Date.now() + options.timeoutMs : Infinity;
    for (;;) {
      const j = await this.refresh();
      options.onProgress?.(j);
      if ((TERMINAL as readonly string[]).includes(j.status)) {
        if (j.status !== "done") {
          throw new LLMDynoError(`${j.title || this.id} ${j.status}${j.error ? `: ${j.error}` : ""}`);
        }
        return j.result ?? {};
      }
      if (Date.now() >= deadline) throw new LLMDynoError(`${j.title || this.id} is still ${j.status}`);
      await sleep(options.pollMs ?? 1000);
    }
  }
}

/** One run: a model × harness × benchmark × iteration, with its transcript, files, logs and telemetry. */
export class Run {
  /** The run's id (run_…). */
  readonly id: string;
  private readonly client: Client;

  /** A handle on run `id`; dyno.run(id) and plan.runs() make them. */
  constructor(client: Client, id: string) {
    this.client = client;
    this.id = id;
  }

  toString(): string {
    return `Run ${this.id}`;
  }

  /** The run's summary: status, stage, scores, time, tokens, cost … */
  refresh(): Promise<Json> {
    return this.client.call("runs.get_run", { rid: this.id });
  }

  /** queued, running, grading, done, failed, cancelled or skipped. */
  async status(): Promise<string> {
    return (await this.refresh()).status;
  }

  /** The agent's events: messages, thinking, tool calls and results, in order (from start, at most limit: 20 000). */
  async transcript(options: { start?: number; limit?: number } = {}): Promise<Json[]> {
    const d = await this.client.call("runs.run_transcript", { rid: this.id, start: options.start ?? 0, limit: options.limit ?? 20000 });
    return d.events ?? [];
  }

  /** Every model request through LLMDyno's proxy: tokens, cost, latency. */
  requests(): Promise<Json> {
    return this.client.call("runs.run_proxy", { rid: this.id });
  }

  /** Files the agent left in the workspace (or its home folder). */
  files(options: { home?: boolean } = {}): Promise<Json[]> {
    return this.client.call("runs.run_files", { rid: this.id, root: options.home ? "home" : "workspace" });
  }

  /** One file's text, by its path in the workspace (or, with home: true, in the agent's home folder). */
  readFile(path: string, options: { home?: boolean } = {}): Promise<string> {
    return this.client.call("runs.run_file", { rid: this.id, path, root: options.home ? "home" : "workspace" });
  }

  /** A harness log: stdout or stderr of a stage (default: stdout of stage 1). */
  log(options: { stage?: number; stream?: "stdout" | "stderr" } = {}): Promise<string> {
    const name = `${options.stream ?? "stdout"}_stage${options.stage ?? 1}.log`;
    return this.client.call("runs.run_log", { rid: this.id, name });
  }

  /** The llama-server log of a local run. */
  serverLog(): Promise<string> {
    return this.client.call("runs.run_log", { rid: this.id, name: "server" });
  }

  /** GPU telemetry samples taken during the run. */
  gpu(maxPoints = 600): Promise<Json[]> {
    return this.client.call("runs.run_gpu", { rid: this.id, max_points: maxPoints });
  }

  /** The workspace as a zip archive. */
  download(): Promise<Download> {
    return this.client.call("runs.run_download", { rid: this.id });
  }

  /** Stop the run; it is marked cancelled and what it did so far is kept. */
  async cancel(): Promise<void> {
    await this.client.call("runs.cancel_run", { rid: this.id });
  }

  /** Run it again; returns the job that does it, if one was started. */
  async retry(): Promise<Job | undefined> {
    const r = await this.client.call("runs.retry_run", { rid: this.id });
    return r?.job_id ? new Job(this.client, r.job_id) : undefined;
  }

  /** Grade the finished workspace again (after a grader fix, say) and wait for the new scores. */
  async regrade(): Promise<Json> {
    const { job_id } = await this.client.call("runs.regrade_run", { rid: this.id });
    await new Job(this.client, job_id).wait();
    return this.refresh();
  }
}

/** A benchmark plan: its runs, live status, and results once it finishes. */
export class Plan {
  /** The plan's id (plan_…). */
  readonly id: string;
  private readonly client: Client;
  private jobId: string | undefined;

  /** A handle on plan `id`; dyno.plan(id), plans() and bench({ wait: false }) make them. */
  constructor(client: Client, id: string, jobId?: string) {
    this.client = client;
    this.id = id;
    this.jobId = jobId;
  }

  toString(): string {
    return `Plan ${this.id}`;
  }

  /** {id, name, status, counts, runs, job, …} as it is now. */
  refresh(): Promise<Json> {
    return this.client.call("plans.get_plan", { pid: this.id });
  }

  /** draft, queued, running, paused, done, failed or cancelled. */
  async status(): Promise<string> {
    return (await this.refresh()).status;
  }

  /** Its runs, one per profile × harness × benchmark × iteration. */
  async runs(): Promise<Run[]> {
    const d = await this.refresh();
    return (d.runs ?? []).map((r: Json) => new Run(this.client, r.id));
  }

  /** Live events until the plan stops; see Client.watch(). */
  watch(options: WatchOptions = {}): AsyncGenerator<LiveEvent> {
    return this.client.watch(this, options);
  }

  /**
   * Wait until the plan stops (done, failed, cancelled or paused), then return its Results; a failed plan still
   * returns what finished. onEvent gets every live event on the way.
   */
  async wait(options: { onEvent?: (event: LiveEvent) => void; transcript?: boolean } = {}): Promise<Results> {
    for await (const ev of this.client.watch(this, { transcript: options.transcript, gpu: Boolean(options.onEvent) })) {
      options.onEvent?.(ev);
    }
    return this.results();
  }

  /** Scored results of this plan, with the Results page's options. */
  results(options: ResultsOptions = {}): Promise<Results> {
    return this.client.results(this, options);
  }

  /** Stop the plan: running agents stop, finished results are kept. */
  async cancel(): Promise<void> {
    await this.client.call("plans.cancel_plan", { pid: this.id });
  }

  /** Pause after the runs in progress finish; resume() continues. */
  async pause(): Promise<void> {
    await this.client.call("plans.pause_plan", { pid: this.id });
  }

  /** Continue a paused, cancelled or failed plan that still has queued runs. */
  async resume(): Promise<void> {
    await this.client.call("plans.resume_plan", { pid: this.id });
  }

  /** Run the failed and cancelled runs again (or those with the given statuses); returns how many were queued. */
  async retry(statuses: string[] = ["failed", "cancelled"]): Promise<number> {
    const r = await this.client.call("plans.retry_plan", { pid: this.id, body: { statuses } });
    this.jobId = r.job_id ?? this.jobId;
    return r.requeued;
  }

  /** Give the plan a new name. */
  async rename(name: string): Promise<Json> {
    return this.client.call("plans.rename_plan", { pid: this.id, body: { name } });
  }

  /** Delete the plan and its runs (and, by default, their files). */
  async delete(options: { files?: boolean } = {}): Promise<void> {
    await this.client.call("plans.delete_plan", { pid: this.id, delete_files: options.files ?? true });
  }

  /** The plan's SWE-bench patches in the standard predictions format (JSONL). */
  async swebenchPredictions(): Promise<string> {
    const d = await this.client.call("plans.swebench_predictions", { pid: this.id });
    return d.content;
  }

  /** The job that runs the plan, when it is running. */
  get job(): Job | undefined {
    return this.jobId ? new Job(this.client, this.jobId) : undefined;
  }
}

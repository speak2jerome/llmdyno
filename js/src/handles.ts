import type { Client, Download } from "./client.ts";
import { LLMDynoError } from "./errors.ts";
import type { LiveEvent, WatchOptions } from "./live.ts";
import type { Results, ResultsOptions } from "./results.ts";

/** A JSON object from the server. The fields are documented in the Python library's reference. */
export type Json = Record<string, any>;

/** Statuses after which a plan or job does nothing more until someone acts. */
export const TERMINAL = ["done", "failed", "cancelled", "paused"] as const;
/** Statuses of a run that has finished. */
export const RUN_FINISHED = ["done", "failed", "cancelled", "skipped"] as const;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** A model profile: a model plus its exact settings. */
export class Profile {
  readonly id: string;
  data: Json;
  private readonly client: Client;

  constructor(client: Client, data: Json) {
    this.client = client;
    this.id = data.id;
    this.data = data;
  }

  get name(): string {
    return this.data.name;
  }

  /** "local" (llama.cpp) or "cloud". */
  get kind(): string {
    return this.data.kind;
  }

  get params(): Json {
    return this.data.params ?? {};
  }

  toString(): string {
    return `Profile ${this.name} (${this.id})`;
  }

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
  check(exact = false): Promise<Json> {
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

  async duplicate(name?: string): Promise<Profile> {
    let copy = new Profile(this.client, await this.client.call("profiles.duplicate_profile", { pid: this.id }));
    if (name) copy = await copy.update({ name });
    return copy;
  }

  /** The profile as a portable JSON file (no API keys). */
  export(): Promise<Download> {
    return this.client.call("profiles.export_profile", { pid: this.id });
  }

  async delete(): Promise<void> {
    await this.client.call("profiles.delete_profile", { pid: this.id });
  }
}

/** A background task: a download, image build, plan, review or import. */
export class Job {
  readonly id: string;
  private readonly client: Client;

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

  async cancel(): Promise<void> {
    await this.client.call("system.cancel_job", { jid: this.id });
  }

  /** Wait until the job ends and return its result; a failed or cancelled job throws. */
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
  readonly id: string;
  private readonly client: Client;

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

  async status(): Promise<string> {
    return (await this.refresh()).status;
  }

  /** The agent's events: messages, thinking, tool calls and results, in order. */
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

  readFile(path: string, options: { home?: boolean } = {}): Promise<string> {
    return this.client.call("runs.run_file", { rid: this.id, path, root: options.home ? "home" : "workspace" });
  }

  /** A harness log: stdout or stderr of a stage. */
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
  readonly id: string;
  private readonly client: Client;
  private jobId: string | undefined;

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

  async status(): Promise<string> {
    return (await this.refresh()).status;
  }

  async runs(): Promise<Run[]> {
    const d = await this.refresh();
    return (d.runs ?? []).map((r: Json) => new Run(this.client, r.id));
  }

  /** Live events until the plan stops; see Client.watch(). */
  watch(options: WatchOptions = {}): AsyncGenerator<LiveEvent> {
    return this.client.watch(this, options);
  }

  /** Wait until the plan stops, then return its Results. onEvent gets every live event on the way. */
  async wait(options: { onEvent?: (event: LiveEvent) => void; transcript?: boolean } = {}): Promise<Results> {
    for await (const ev of this.client.watch(this, { transcript: options.transcript, gpu: Boolean(options.onEvent) })) {
      options.onEvent?.(ev);
    }
    return this.results();
  }

  results(options: ResultsOptions = {}): Promise<Results> {
    return this.client.results(this, options);
  }

  async cancel(): Promise<void> {
    await this.client.call("plans.cancel_plan", { pid: this.id });
  }

  async pause(): Promise<void> {
    await this.client.call("plans.pause_plan", { pid: this.id });
  }

  async resume(): Promise<void> {
    await this.client.call("plans.resume_plan", { pid: this.id });
  }

  /** Run the failed and cancelled runs again (or those with the given statuses); returns how many were queued. */
  async retry(statuses: string[] = ["failed", "cancelled"]): Promise<number> {
    const r = await this.client.call("plans.retry_plan", { pid: this.id, body: { statuses } });
    this.jobId = r.job_id ?? this.jobId;
    return r.requeued;
  }

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

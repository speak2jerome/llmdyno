import type { Client } from "./client.ts";
import { InvalidError } from "./errors.ts";
import type { Json } from "./handles.ts";

/** Options for results(): the settings of the dashboard's Results page. Weights are relative, not percentages. */
export interface ResultsOptions {
  /** Include the bundled sample results (default: only when you name its plan). */
  includeSample?: boolean;
  /** Weight of hidden-test correctness in the final score (default 50). */
  correctness?: number;
  /** Weight of instruction following (default 15). */
  instructionFollowing?: number;
  /** Weight of code quality (default 25). A number here, unlike bench()'s quality switch. */
  quality?: number;
  /** Weight of efficiency: speed and cost against the fastest comparable run (default 10). */
  efficiency?: number;
  /** How code quality splits between "static", "probes" and "review". */
  qualityWeights?: Record<string, number>;
  /** Only these benchmarks. */
  benchmarks?: string | string[];
  /** A run passes at this correctness (default 0.8). */
  passThreshold?: number;
  /** What efficiency is measured against: "local" (the fastest local run, the default) or "all" (the fastest run). */
  efficiencyRef?: string;
}

/** A table of the results: export() takes "configs", "cells" or "runs"; rows() takes any of them. */
export type Level = "configs" | "runs" | "cells" | "reviews" | "rubric" | "public";

const pct = (v: unknown): number | null => (v == null ? null : Math.round(Number(v) * 1000) / 10);

/**
 * Scored results, the same tables as the dashboard's Results page. leaderboard() and runs() return plain rows;
 * rows(level) gives any table; export() returns the app's CSV or JSON export.
 */
export class Results {
  readonly data: Json;
  readonly planIds: string[];
  private readonly options: Record<string, string>;
  private readonly labels: Json;
  private readonly client: Client;

  private constructor(client: Client, data: Json, planIds: string[], options: Record<string, string>) {
    this.client = client;
    this.data = data;
    this.planIds = planIds;
    this.options = options;
    this.labels = data.labels ?? {};
  }

  /** Results for these plan ids (all plans except the sample when empty). */
  static async load(client: Client, planIds: string[], o: ResultsOptions = {}): Promise<Results> {
    const saved = await client.call("settings.get_settings");
    const weights: Record<string, number> = { ...(saved.weights ?? {}) };
    if (o.correctness != null) weights.correctness = o.correctness;
    if (o.instructionFollowing != null) weights.instruction_following = o.instructionFollowing;
    if (o.quality != null) weights.quality = o.quality;
    if (o.efficiency != null) weights.efficiency = o.efficiency;
    const benchmarks = o.benchmarks === undefined ? [] : Array.isArray(o.benchmarks) ? o.benchmarks : [o.benchmarks];
    const options = {
      plan_ids: planIds.join(","), weights: JSON.stringify(weights), quality_weights: JSON.stringify({ ...(saved.quality_weights ?? {}), ...(o.qualityWeights ?? {}) }),
      benchmark_ids: benchmarks.join(","),
    };
    const data = await client.call("results.results", {
      ...options, pass_threshold: o.passThreshold ?? 0.8, efficiency_ref: o.efficiencyRef ?? "local",
      include_sample: Boolean(o.includeSample) || planIds.length > 0,
    });
    return new Results(client, data, planIds, options);
  }

  private profileName(r: Json): string {
    return this.labels.profiles?.[r.profile_id]?.name ?? r.profile_id;
  }

  private harnessName(r: Json): string {
    return this.labels.harnesses?.[r.harness_id] ?? r.harness_id;
  }

  /** One row per profile × harness, best first. Scores are 0-100. */
  leaderboard(): Json[] {
    return (this.data.configs ?? []).map((c: Json, i: number) => ({
      rank: i + 1, profile: this.profileName(c), harness: this.harnessName(c), final: pct(c.final),
      correctness: pct(c.correctness), instruction_following: pct(c.instruction_following), quality: pct(c.quality),
      efficiency: pct(c.efficiency), pass_at_k: pct(c.pass_at_k), runs: c.runs, wall_s_total: c.wall_s_total,
      cost_usd_total: c.cost_usd_total, decode_tps: c.decode_tps, peak_vram_mib: c.peak_vram_mib,
      profile_id: c.profile_id, harness_id: c.harness_id,
    }));
  }

  /** The top row of the leaderboard. */
  best(): Json | undefined {
    return this.leaderboard()[0];
  }

  /** One row per run (benchmark × iteration). */
  runs(): Json[] {
    const titles = this.labels.benchmarks ?? {};
    return (this.data.runs ?? []).map((r: Json) => ({
      run_id: r.id, plan_id: r.plan_id, profile: this.profileName(r), harness: this.harnessName(r),
      benchmark: titles[r.benchmark_id]?.title ?? r.benchmark_id, benchmark_id: r.benchmark_id, iteration: r.iteration,
      final: r.final, correctness: r.correctness, instruction_following: r.instruction_following, quality: r.quality,
      tests_passed: r.tests_passed, tests_total: r.tests_total, wall_s: r.wall_s, cost_usd: r.cost_usd,
      generated_tokens: r.generated_tokens, decode_tps: r.decode_tps, ttft_s: r.ttft_median_s,
      peak_context_tokens: r.peak_context_tokens, spill: r.spill_detected,
    }));
  }

  /** One row per profile × harness × benchmark: pass rate and scores over iterations (the heatmap). */
  cells(): Json[] {
    return (this.data.cells ?? []).map((c: Json) => ({ profile: this.profileName(c), harness: this.harnessName(c), ...c }));
  }

  /** Every LLM-judge review behind these results. */
  reviews(): Json[] {
    return [...(this.data.reviews ?? [])];
  }

  /** Average judge score per rubric dimension for each profile × harness. */
  rubric(): Json[] {
    return (this.data.rubric ?? []).map((r: Json) => ({ profile: this.profileName(r), harness: this.harnessName(r), ...r }));
  }

  /** How much the judges agree, and how much each favours its own model family. */
  agreement(): Json {
    return { ...(this.data.agreement ?? {}) };
  }

  /** SWE-bench resolved rate and Aider polyglot solved rate per profile × harness (when such runs exist). */
  public(): Json[] {
    type Group = { pid: string; hid: string; swebench: boolean[]; polyglot: boolean[] };
    const groups = new Map<string, Group>();
    for (const r of this.data.runs ?? []) {
      const kind = String(r.benchmark_id).startsWith("swe_") ? "swebench" : String(r.benchmark_id).startsWith("pg_") ? "polyglot" : undefined;
      if (!kind) continue;
      const key = `${r.profile_id}\u0000${r.harness_id}`;
      const g: Group = groups.get(key) ?? { pid: r.profile_id, hid: r.harness_id, swebench: [], polyglot: [] };
      g[kind].push((r.correctness ?? 0) >= 1);
      groups.set(key, g);
    }
    const rate = (v: boolean[]) => (v.length ? Math.round((1000 * v.filter(Boolean).length) / v.length) / 10 : null);
    return [...groups.values()].map((g) => ({
      profile: this.profileName({ profile_id: g.pid }), harness: this.harnessName({ harness_id: g.hid }),
      swebench_resolved_pct: rate(g.swebench), swebench_runs: g.swebench.length,
      polyglot_solved_pct: rate(g.polyglot), polyglot_runs: g.polyglot.length,
    }));
  }

  /** The rows of one table. */
  rows(level: Level = "configs"): Json[] {
    switch (level) {
      case "configs": return this.leaderboard();
      case "runs": return this.runs();
      case "cells": return this.cells();
      case "reviews": return this.reviews();
      case "rubric": return this.rubric();
      case "public": return this.public();
      default: throw new InvalidError(`level is one of configs, runs, cells, reviews, rubric, public, not ${JSON.stringify(level)}`);
    }
  }

  /** The app's export (CSV or JSON) of one table, with the LLMDyno version recorded. */
  async export(options: { level?: "configs" | "cells" | "runs"; fmt?: "csv" | "json" } = {}): Promise<string> {
    const d = await this.client.call("results.export", { ...this.options, level: options.level ?? "runs", fmt: options.fmt ?? "csv" });
    return d.content;
  }

  /** Each profile's Artificial Analysis index next to its score here (needs an Artificial Analysis key on the server). */
  async reference(): Promise<Json[]> {
    const ref = await this.client.call("references.aa_reference");
    return this.leaderboard().map((row) => {
      const m = ref.matches?.[row.profile_id] ?? {};
      return { profile: row.profile, harness: row.harness, final: row.final, aa_model: m.model, aa_score: m.score, aa_manual: m.manual };
    });
  }

  /** A plain-text leaderboard, like Python's print(results). */
  toString(): string {
    const rows = this.leaderboard();
    if (!rows.length) return "No results yet.";
    const head = ["#", "Profile", "Harness", "Final", "Correct", "Quality", "Runs"];
    const body = rows.map((r) => [r.rank, r.profile, r.harness, r.final, r.correctness, r.quality, r.runs].map((x) => (x == null ? "" : String(x))));
    const widths = head.map((h, i) => Math.max(h.length, ...body.map((b) => b[i].length)));
    const line = (cells: string[]) => cells.map((c, i) => (i < 3 ? c.padEnd(widths[i]) : c.padStart(widths[i]))).join("  ");
    return [line(head), ...body.map(line)].join("\n");
  }
}

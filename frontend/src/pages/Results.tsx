import { useQuery } from "@tanstack/react-query";
import {
  Award, BarChart3, Coins, Download, Gauge as GaugeIco, GitCompare, Printer, Scale, Sparkles, Timer, Trophy, Users,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Logo, LogoName, logoRich, logoUrl, profileLogo } from "../logos";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, download, qs } from "../api";
import { Chart, axis } from "../charts";
import { fmtDur, fmtMib, fmtNum, fmtPct, fmtTokens, fmtUsd } from "../format";
import { useSample, useSettings } from "../queries";
import {
  Badge, Button, Card, Chip, Drawer, Empty, Field, Menu, Notice, PageHead, ScoreCell, Segmented, Select, Skeleton, Table, Toggle, useToast,
} from "../ui";

const PRESETS: Record<string, { label: string; w: any; q: any }> = {
  balanced: { label: "Balanced (default)", w: { correctness: 50, instruction_following: 15, quality: 25, efficiency: 10 }, q: { static: 35, probes: 30, review: 35 } },
  correctness: { label: "Correctness only", w: { correctness: 100, instruction_following: 0, quality: 0, efficiency: 0 }, q: { static: 35, probes: 30, review: 35 } },
  quality: { label: "Code quality focus", w: { correctness: 35, instruction_following: 10, quality: 50, efficiency: 5 }, q: { static: 30, probes: 30, review: 40 } },
  speed: { label: "Speed matters", w: { correctness: 45, instruction_following: 10, quality: 15, efficiency: 30 }, q: { static: 35, probes: 30, review: 35 } },
};
const W_LABEL: Record<string, string> = { correctness: "Correctness", instruction_following: "Instruction following", quality: "Code quality", efficiency: "Efficiency" };
const Q_LABEL: Record<string, string> = { static: "Static analysis", probes: "Robustness probes", review: "Blind review" };
const METRICS: { key: string; label: string; fmt: (v: any) => string; level: ("config" | "cell" | "run")[]; log?: boolean; higher?: boolean }[] = [
  { key: "final", label: "Final score", fmt: (v) => fmtNum(v * 100), level: ["config", "cell", "run"], higher: true },
  { key: "correctness", label: "Correctness", fmt: (v) => fmtPct(v), level: ["config", "cell", "run"], higher: true },
  { key: "instruction_following", label: "Instruction following", fmt: (v) => fmtPct(v), level: ["config", "cell", "run"], higher: true },
  { key: "quality", label: "Code quality", fmt: (v) => fmtNum(v * 100), level: ["config", "cell", "run"], higher: true },
  { key: "static", label: "Static analysis", fmt: (v) => fmtNum(v * 100), level: ["config", "cell", "run"], higher: true },
  { key: "review", label: "Judge review", fmt: (v) => fmtNum(v * 10, 1), level: ["config", "cell", "run"], higher: true },
  { key: "efficiency", label: "Efficiency", fmt: (v) => fmtNum(v * 100), level: ["config", "cell", "run"], higher: true },
  { key: "consistency", label: "Consistency", fmt: (v) => fmtNum(v * 100), level: ["config"], higher: true },
  { key: "pass_at_k", label: "pass@k", fmt: (v) => fmtPct(v), level: ["config"], higher: true },
  { key: "wall_s", label: "Wall time", fmt: (v) => fmtDur(v), level: ["cell", "run"], log: true, higher: false },
  { key: "wall_s_total", label: "Total wall time", fmt: (v) => fmtDur(v), level: ["config"], log: true, higher: false },
  { key: "cost_usd", label: "Cost", fmt: (v) => fmtUsd(v), level: ["cell", "run"], log: true, higher: false },
  { key: "cost_usd_total", label: "Total cost", fmt: (v) => fmtUsd(v), level: ["config"], log: true, higher: false },
  { key: "generated_tokens", label: "Output tokens", fmt: (v) => fmtTokens(v), level: ["cell", "run"], log: true },
  { key: "generated_tokens_total", label: "Total output tokens", fmt: (v) => fmtTokens(v), level: ["config"], log: true },
  { key: "decode_tps", label: "Decode tok/s", fmt: (v) => fmtNum(v, 1), level: ["config", "cell", "run"], higher: true },
  { key: "peak_context_tokens", label: "Peak context", fmt: (v) => fmtTokens(v), level: ["config", "cell", "run"] },
  { key: "sloc_total", label: "Lines of code", fmt: (v) => fmtNum(v), level: ["cell", "run"], log: true },
  { key: "sloc_total_total", label: "Total lines of code", fmt: (v) => fmtNum(v), level: ["config"], log: true },
  { key: "gpu_energy_wh_total", label: "GPU energy (Wh)", fmt: (v) => fmtNum(v, 1), level: ["config"] },
  { key: "peak_vram_mib", label: "Peak VRAM", fmt: (v) => fmtMib(v), level: ["config"] },
  { key: "score_per_dollar", label: "Score per dollar", fmt: (v) => fmtNum(v, 0), level: ["config"], log: true, higher: true },
];
const metric = (k: string) => METRICS.find((m) => m.key === k)!;
const SCORE_KEYS = new Set(["final", "correctness", "instruction_following", "quality", "static", "review", "efficiency", "consistency", "pass_at_k"]);

function useResults(planIds: string[], weights: any, qweights: any, threshold: number, effRef: string, includeSample: boolean, benchIds: string[]) {
  return useQuery({
    enabled: !!weights && !!qweights,
    queryKey: ["results", planIds.join(","), JSON.stringify(weights), JSON.stringify(qweights), threshold, effRef, includeSample, benchIds.join(",")],
    queryFn: () => api.get(`/results${qs({ plan_ids: planIds.join(","), weights: weights && JSON.stringify(weights), quality_weights: qweights && JSON.stringify(qweights), pass_threshold: threshold, efficiency_ref: effRef, include_sample: includeSample, benchmark_ids: benchIds.join(",") })}`),
    placeholderData: (prev: any) => prev,
  });
}

export default function Results() {
  const [sp, setSp] = useSearchParams();
  const nav = useNavigate();
  const toast = useToast();
  const sample = useSample();
  const [planIds, setPlanIds] = useState<string[]>(sp.get("plans") ? sp.get("plans")!.split(",") : []);
  const [weights, setWeights] = useState<any>(null);
  const [qweights, setQweights] = useState<any>(null);
  const [threshold, setThreshold] = useState(0.8);
  const [effRef, setEffRef] = useState("local");
  const [debounced, setDebounced] = useState<any>({ w: null, q: null });
  const [showWeights, setShowWeights] = useState(false);
  const [kind, setKind] = useState<"all" | "local" | "cloud">("all");
  const [harnessF, setHarnessF] = useState<string[]>([]);
  const [benchF, setBenchF] = useState<string[]>([]);
  const [heatMetric, setHeatMetric] = useState("final");
  const [radarSel, setRadarSel] = useState<string[]>([]);
  const [sx, setSx] = useState("wall_s_total");
  const [sy, setSy] = useState("final");
  const [ssize, setSsize] = useState("sloc_total_total");
  const [pareto, setPareto] = useState(true);
  const [boardView, setBoardView] = useState<"chart" | "table">("chart");
  const [compare, setCompare] = useState<string[] | null>(null);
  const [runFilter, setRunFilter] = useState<string | null>(null);
  const settings = useSettings();
  useEffect(() => {
    // start from the saved default weights so the first request is already the right one
    if (settings.data && !weights) {
      setWeights(settings.data.weights);
      setQweights(settings.data.quality_weights);
      setDebounced({ w: settings.data.weights, q: settings.data.quality_weights });
    }
  }, [settings.data, weights]);
  useEffect(() => {
    if (!weights) return;
    const t = setTimeout(() => setDebounced({ w: weights, q: qweights }), 220);
    return () => clearTimeout(t);
  }, [weights, qweights]);
  const res = useResults(planIds, debounced.w, debounced.q, threshold, effRef, true, benchF);
  const data = res.data;
  // once you have plans of your own, start from those rather than mixing in the bundled sample
  const defaulted = useRef(!!sp.get("plans"));
  useEffect(() => {
    if (defaulted.current || !data?.plans) return;
    defaulted.current = true;
    const own = data.plans.filter((p: any) => !p.sample);
    if (own.length && own.length < data.plans.length) setPlanIds(own.map((p: any) => p.id));
  }, [data]);
  useEffect(() => {
    const want = planIds.join(",");
    if ((sp.get("plans") || "") !== want) setSp(want ? { plans: want } : {}, { replace: true });
  }, [planIds, sp, setSp]);

  const L = data?.labels;
  const multiHarness = useMemo(() => new Set((data?.configs || []).map((c: any) => c.harness_id)).size > 1, [data]);
  const cname = (c: any) => `${L?.profiles?.[c.profile_id]?.name || c.profile_id}${multiHarness ? ` · ${L?.harnesses?.[c.harness_id] || c.harness_id}` : ""}`;
  const ckey = (c: any) => `${c.profile_id}|${c.harness_id}`;
  const clogo = (c: any) => profileLogo(L?.profiles?.[c.profile_id]);
  const configs = useMemo(() => (data?.configs || []).filter((c: any) => (kind === "all" || (L?.profiles?.[c.profile_id]?.kind || "local") === kind) && (!harnessF.length || harnessF.includes(c.harness_id))), [data, kind, harnessF, L]);
  const ckeys = new Set(configs.map(ckey));
  const rankOf = (c: any) => configs.findIndex((x: any) => ckey(x) === ckey(c)) + 1;
  const cells = (data?.cells || []).filter((c: any) => ckeys.has(ckey(c)) && (!benchF.length || benchF.includes(c.benchmark_id)));
  const runs = (data?.runs || []).filter((r: any) => ckeys.has(ckey(r)) && (!benchF.length || benchF.includes(r.benchmark_id)));
  const benchIds: string[] = Array.from(new Set<string>((data?.cells || []).map((c: any) => c.benchmark_id))).filter((b) => !benchF.length || benchF.includes(b));
  // scores are only like-for-like when every configuration ran the same benchmarks
  const benchSets = useMemo(() => {
    const m = new Map<string, Set<string>>();
    for (const c of cells) {
      if (!m.has(ckey(c))) m.set(ckey(c), new Set());
      m.get(ckey(c))!.add(c.benchmark_id);
    }
    return [...m.values()];
  }, [cells]); // eslint-disable-line react-hooks/exhaustive-deps
  const mixedBenchmarks = new Set(benchSets.map((x) => [...x].sort().join(","))).size > 1;
  const sharedBenchmarks = benchSets.length ? [...benchSets[0]].filter((b) => benchSets.every((x) => x.has(b))) : [];
  useEffect(() => {
    if (configs.length && !radarSel.length) setRadarSel(configs.slice(0, 4).map(ckey));
  }, [configs.length]); // eslint-disable-line react-hooks/exhaustive-deps

  if (res.isLoading || !weights) return <div className="page"><Skeleton h={500} /></div>;
  if (!data?.configs?.length) return (
    <div className="page">
      <PageHead title="Results" />
      <Card><Empty icon={<BarChart3 size={22} />} title="No finished runs to show yet" action={<div className="row">
        <Button variant="primary" onClick={() => nav("/plans/new")}>Run a benchmark</Button>
        {sample.data?.available && !sample.data?.loaded && <Button icon={<Sparkles size={14} />} onClick={async () => { try { await api.post("/sample"); res.refetch(); sample.refetch(); toast.ok("Sample loaded"); } catch (e) { toast.err("Could not load", e); } }}>Load sample results</Button>}
      </div>}>Results appear here as runs finish: leaderboard, heatmaps, radar comparisons, cost and speed trade-offs, consistency and judge agreement.</Empty></Card>
    </div>
  );

  const best = configs[0];
  const bestLocal = configs.find((c: any) => L.profiles[c.profile_id]?.kind === "local");
  const bestValue = [...configs].filter((c: any) => c.score_per_dollar).sort((a: any, b: any) => b.score_per_dollar - a.score_per_dollar)[0];
  const fastest = [...configs].filter((c: any) => (c.final || 0) >= (best?.final || 0) * 0.85).sort((a: any, b: any) => a.wall_s_total - b.wall_s_total)[0];
  const consistent = [...configs].filter((c: any) => c.consistency !== null && c.consistency !== undefined).sort((a: any, b: any) => b.consistency - a.consistency)[0];
  const pair = data.agreement?.pairs?.[0];
  const tw = Object.values(weights || {}).reduce((a: number, b: any) => a + Number(b), 0) || 1;

  return (
    <div className="page">
      <PageHead title="Results" sub={`${configs.length} configurations · ${runs.length} runs · ${benchIds.length} benchmarks${data.agreement?.judges?.length ? ` · ${data.agreement.judges.length} judge(s)` : ""}`}
        actions={<>
          <Button icon={<Scale size={15} />} onClick={() => setShowWeights((s) => !s)}>{showWeights ? "Hide weights" : "Scoring weights"}</Button>
          <Button icon={<GitCompare size={15} />} onClick={() => setCompare(configs.slice(0, 2).map(ckey))} disabled={configs.length < 2}>Compare</Button>
          <Menu trigger={(o) => <Button icon={<Download size={15} />} onClick={o}>Export</Button>} items={[
            { label: "Configurations (CSV)", onClick: () => download(`/results/export${qs({ plan_ids: planIds.join(","), level: "configs", benchmark_ids: benchF.join(","), weights: JSON.stringify(weights), quality_weights: JSON.stringify(qweights) })}`) },
            { label: "Per benchmark (CSV)", onClick: () => download(`/results/export${qs({ plan_ids: planIds.join(","), level: "cells", benchmark_ids: benchF.join(","), weights: JSON.stringify(weights), quality_weights: JSON.stringify(qweights) })}`) },
            { label: "All runs (CSV)", onClick: () => download(`/results/export${qs({ plan_ids: planIds.join(","), level: "runs", benchmark_ids: benchF.join(","), weights: JSON.stringify(weights), quality_weights: JSON.stringify(qweights) })}`) },
            { label: "All runs (JSON)", onClick: () => download(`/results/export${qs({ plan_ids: planIds.join(","), level: "runs", fmt: "json", benchmark_ids: benchF.join(","), weights: JSON.stringify(weights), quality_weights: JSON.stringify(qweights) })}`) },
            "sep",
            { label: "Print / save as PDF", icon: <Printer size={14} />, onClick: () => window.print() },
          ]} />
        </>} />

      <div className="card no-print" style={{ padding: "12px 16px" }}>
        <div className="row wrap" style={{ gap: 10 }}>
          <span className="label">Plans</span>
          <Chip on={!planIds.length} onClick={() => setPlanIds([])}>All</Chip>
          {data.plans.map((p: any) => <Chip key={p.id} on={planIds.includes(p.id)} onClick={() => setPlanIds((x) => x.includes(p.id) ? x.filter((y) => y !== p.id) : [...x, p.id])}>{p.sample ? "★ " : ""}{p.name.length > 40 ? p.name.slice(0, 40) + "…" : p.name}</Chip>)}
        </div>
        <div className="row wrap mt-12" style={{ gap: 10 }}>
          <span className="label">Show</span>
          <Segmented value={kind} onChange={setKind} options={[{ value: "all", label: "All" }, { value: "local", label: "Local" }, { value: "cloud", label: "Cloud" }]} />
          {multiHarness && <><span className="label" style={{ marginLeft: 8 }}>Harness</span>{Object.entries(L.harnesses).filter(([h]) => (data.configs || []).some((c: any) => c.harness_id === h)).map(([h, n]: any) => <Chip key={h} on={harnessF.includes(h)} onClick={() => setHarnessF((x) => x.includes(h) ? x.filter((y) => y !== h) : [...x, h])}>{n}</Chip>)}</>}
          <span className="label" style={{ marginLeft: 8 }}>Benchmarks</span>
          {(data.benchmarks_available || []).map((b: string) => <Chip key={b} on={benchF.includes(b)} onClick={() => setBenchF((x) => x.includes(b) ? x.filter((y) => y !== b) : [...x, b])}>{(L.benchmarks[b]?.title || b).split(":")[0].slice(0, 26)}</Chip>)}
        </div>
      </div>

      {mixedBenchmarks && (
        <div className="mt-16 no-print">
          <Notice tone="warning" title="Not a like-for-like comparison" action={sharedBenchmarks.length > 0
            ? <Button size="sm" onClick={() => setBenchF(sharedBenchmarks)}>Only shared benchmarks ({sharedBenchmarks.length})</Button>
            : !!data.plans.some((p: any) => p.sample) && <Button size="sm" onClick={() => setPlanIds(data.plans.filter((p: any) => !p.sample).map((p: any) => p.id))}>Hide the sample</Button>}>
            These configurations ran different benchmarks, so a configuration that only did easy tasks can outrank one that did hard ones.
            {sharedBenchmarks.length ? " Filter to the benchmarks they all share for a fair ranking." : " They share no benchmark; compare them within one plan instead."}
          </Notice>
        </div>
      )}

      {showWeights && weights && (
        <Card className="mt-16" title="Scoring weights" sub="Changes re-rank everything instantly. Efficiency compares wall time with the fastest run that passed on each benchmark."
          actions={<>
            <Select value="" onChange={(k: string) => { if (PRESETS[k]) { setWeights(PRESETS[k].w); setQweights(PRESETS[k].q); } }} options={[{ value: "", label: "Presets…" }, ...Object.entries(PRESETS).map(([k, p]) => ({ value: k, label: p.label }))]} aria-label="Weight presets" />
            <Button size="sm" onClick={() => api.post("/results/weights", { weights, quality_weights: qweights }).then(() => toast.ok("Saved as default weights")).catch((e) => toast.err("Could not save", e))}>Save as default</Button>
          </>}>
          <div className="grid grid-2">
            <div className="col">
              <b className="small">Final score ({Math.round(tw)} total → normalised)</b>
              {Object.keys(W_LABEL).map((k) => (
                <div key={k} className="slider-row" style={{ gridTemplateColumns: "170px 1fr 44px" }}>
                  <span className="small">{W_LABEL[k]}</span>
                  <input type="range" min={0} max={100} value={weights[k]} onChange={(e) => setWeights({ ...weights, [k]: +e.target.value })} aria-label={W_LABEL[k]} />
                  <span className="tnum small right">{Math.round((weights[k] / tw) * 100)}%</span>
                </div>
              ))}
            </div>
            <div className="col">
              <b className="small">Code quality = </b>
              {Object.keys(Q_LABEL).map((k) => (
                <div key={k} className="slider-row" style={{ gridTemplateColumns: "170px 1fr 44px" }}>
                  <span className="small">{Q_LABEL[k]}</span>
                  <input type="range" min={0} max={100} value={qweights[k]} onChange={(e) => setQweights({ ...qweights, [k]: +e.target.value })} aria-label={Q_LABEL[k]} />
                  <span className="tnum small right">{qweights[k]}</span>
                </div>
              ))}
              <div className="row wrap mt-8">
                <Field label={`Pass threshold: ${Math.round(threshold * 100)}% of hidden tests`}>
                  <input type="range" min={0.5} max={1} step={0.05} value={threshold} onChange={(e) => setThreshold(+e.target.value)} aria-label="Pass threshold" />
                </Field>
                <Field label="Efficiency reference">
                  <Segmented value={effRef} onChange={setEffRef} options={[{ value: "local", label: "Fastest local run" }, { value: "all", label: "Fastest run" }]} />
                </Field>
              </div>
            </div>
          </div>
        </Card>
      )}

      <div className="grid mt-16" style={{ gridTemplateColumns: "repeat(6, minmax(0, 1fr))" }}>
        <Kpi icon={<Trophy size={14} />} label="Top configuration" value={best ? fmtNum(best.final * 100, 1) : "–"} sub={best && <LogoName id={clogo(best)} size={15}>{cname(best)}</LogoName>} />
        <Kpi icon={<Award size={14} />} label="Best local" value={bestLocal ? fmtNum(bestLocal.final * 100, 1) : "–"} sub={bestLocal ? <LogoName id={clogo(bestLocal)} size={15}>{cname(bestLocal)}{best ? ` · ${fmtNum((bestLocal.final - best.final) * 100, 1)} vs top` : ""}</LogoName> : "no local runs"} />
        <Kpi icon={<Coins size={14} />} label="Best value" value={bestValue ? `${fmtNum(bestValue.score_per_dollar, 0)}` : "–"} sub={bestValue ? <LogoName id={clogo(bestValue)} size={15}>{cname(bestValue)} · points per $</LogoName> : "needs cost data"} />
        <Kpi icon={<Timer size={14} />} label="Fastest strong config" value={fastest ? fmtDur(fastest.wall_s_total) : "–"} sub={fastest ? <LogoName id={clogo(fastest)} size={15}>{cname(fastest)} (≥85% of top)</LogoName> : ""} />
        <Kpi icon={<GaugeIco size={14} />} label="Most consistent" value={consistent ? fmtNum(consistent.consistency * 100) : "–"} sub={consistent ? <LogoName id={clogo(consistent)} size={15}>{cname(consistent)}</LogoName> : "needs 2+ iterations"} />
        <Kpi icon={<Users size={14} />} label="Judge agreement" value={pair ? `r ${pair.pearson}` : "–"} sub={pair ? `${pair.n} runs · ${pair.mean_abs_diff} pt mean gap` : "needs 2 judges"} />
      </div>

      <Card className="mt-16" title="Leaderboard" sub="Bar = weighted points per component; the line shows ±95% confidence across iterations and benchmarks."
        actions={<Segmented value={boardView} onChange={setBoardView} options={[{ value: "chart", label: "Chart" }, { value: "table", label: "Table" }]} />}>
        {boardView === "chart" ? <Leaderboard configs={configs} name={cname} logo={clogo} onClick={(k) => setRunFilter(k)} /> : (
          <Table rowKey={ckey} rows={configs} onRow={(c: any) => setRunFilter(ckey(c))} initialSort={{ key: "final", dir: -1 }} cols={[
            { key: "rank", label: "#", num: true, sort: (c) => rankOf(c), render: (c: any) => rankOf(c) },
            { key: "name", label: "Configuration", sort: (c) => cname(c), className: "nowrap", render: (c: any) => <div className="row" style={{ minWidth: 240, gap: 10, alignItems: "center" }}><Logo id={clogo(c)} size={28} /><div style={{ minWidth: 0 }}><b>{cname(c)}</b><div className="tiny muted">{L.profiles[c.profile_id]?.kind === "cloud" ? L.profiles[c.profile_id]?.provider || "cloud" : L.profiles[c.profile_id]?.quant}{c.spill_runs ? <Badge tone="danger" className="mt-8"> {c.spill_runs} spill</Badge> : null}</div></div></div> },
            { key: "final", label: "Final", num: true, sort: (c) => c.final, render: (c: any) => <ScoreCell v={c.final} digits={1} /> },
            { key: "corr", label: "Correct", num: true, sort: (c) => c.correctness, render: (c: any) => fmtPct(c.correctness) },
            { key: "if", label: "Instr.", num: true, sort: (c) => c.instruction_following, render: (c: any) => fmtPct(c.instruction_following) },
            { key: "q", label: "Quality", num: true, sort: (c) => c.quality, render: (c: any) => fmtNum((c.quality ?? 0) * 100) },
            { key: "rev", label: "Review", num: true, sort: (c) => c.review, render: (c: any) => c.review != null ? fmtNum(c.review * 10, 1) : "–" },
            { key: "eff", label: "Eff.", num: true, sort: (c) => c.efficiency, render: (c: any) => fmtNum((c.efficiency ?? 0) * 100) },
            { key: "cons", label: "Consist.", num: true, sort: (c) => c.consistency, render: (c: any) => c.consistency != null ? fmtNum(c.consistency * 100) : "–" },
            { key: "pk", label: "pass@k", num: true, sort: (c) => c.pass_at_k, render: (c: any) => fmtPct(c.pass_at_k) },
            { key: "time", label: "Time", num: true, sort: (c) => c.wall_s_total, render: (c: any) => fmtDur(c.wall_s_total) },
            { key: "tok", label: "Output", num: true, sort: (c) => c.generated_tokens_total, render: (c: any) => fmtTokens(c.generated_tokens_total) },
            { key: "tps", label: "tok/s", num: true, sort: (c) => c.decode_tps, render: (c: any) => fmtNum(c.decode_tps) },
            { key: "cost", label: "Cost", num: true, sort: (c) => c.cost_usd_total, render: (c: any) => fmtUsd(c.cost_usd_total) },
            { key: "loc", label: "Lines", num: true, sort: (c) => c.sloc_total_total, render: (c: any) => fmtNum(c.sloc_total_total) },
          ]} />
        )}
      </Card>

      <div className="grid grid-2 mt-16">
        <Card title="Per-benchmark heatmap" sub="Click a cell to list its runs." actions={<Select value={heatMetric} onChange={setHeatMetric} options={METRICS.filter((m) => m.level.includes("cell")).map((m) => ({ value: m.key, label: m.label }))} aria-label="Heatmap metric" />}>
          <Heatmap configs={configs} cells={cells} benchIds={benchIds} labels={L} name={cname} logo={clogo} metricKey={heatMetric} onClick={(k: string) => setRunFilter(k)} />
        </Card>
        <Card title="Profile shape" sub="Up to 5 configurations across six normalised dimensions.">
          <div className="pill-list mb-12">{configs.slice(0, 14).map((c: any) => <Chip key={ckey(c)} on={radarSel.includes(ckey(c))} onClick={() => setRadarSel((x) => x.includes(ckey(c)) ? x.filter((y) => y !== ckey(c)) : x.length >= 5 ? x : [...x, ckey(c)])}><LogoName id={clogo(c)} size={14}>{cname(c).slice(0, 30)}</LogoName></Chip>)}</div>
          <Radar configs={configs.filter((c: any) => radarSel.includes(ckey(c)))} all={configs} name={cname} logo={clogo} />
        </Card>
      </div>

      <Card className="mt-16" title="Trade-off explorer" sub="Any metric against any other. The Pareto frontier marks configurations nothing else beats on both axes."
        actions={<div className="row wrap">
          <span className="small muted">X</span><Select value={sx} onChange={setSx} options={METRICS.filter((m) => m.level.includes("config")).map((m) => ({ value: m.key, label: m.label }))} aria-label="X axis" />
          <span className="small muted">Y</span><Select value={sy} onChange={setSy} options={METRICS.filter((m) => m.level.includes("config")).map((m) => ({ value: m.key, label: m.label }))} aria-label="Y axis" />
          <span className="small muted">Size</span><Select value={ssize} onChange={setSsize} options={[{ value: "", label: "Same size" }, ...METRICS.filter((m) => m.level.includes("config")).map((m) => ({ value: m.key, label: m.label }))]} aria-label="Point size" />
          <Toggle checked={pareto} onChange={setPareto} label="Pareto" />
        </div>}>
        <Scatter configs={configs} name={cname} logo={clogo} labels={L} x={sx} y={sy} size={ssize} pareto={pareto} onClick={(k: string) => setRunFilter(k)} />
      </Card>

      <div className="grid grid-2 mt-16">
        <Card title="Consistency" sub="Spread of run scores per configuration (all benchmarks and iterations).">
          <Box configs={configs} runs={runs} name={cname} logo={clogo} ckey={ckey} />
        </Card>
        <Card title="Tokens and cost" sub="Prompt tokens split into cached and uncached, plus output; cost on the right axis.">
          <Tokens configs={configs} runs={runs} name={cname} logo={clogo} ckey={ckey} />
        </Card>
      </div>

      {multiHarness && (
        <Card className="mt-16" title="Harness comparison" sub="Same profile, different harnesses.">
          <HarnessCompare configs={configs} labels={L} />
        </Card>
      )}

      {data.rubric?.length > 0 && (
        <div className="grid grid-2 mt-16">
          <Card title="Rubric dimensions" sub="Mean judge score per dimension (1-10).">
            <RubricHeat rubric={data.rubric.filter((r: any) => ckeys.has(`${r.profile_id}|${r.harness_id}`))} configs={configs} name={cname} logo={clogo} />
          </Card>
          <Card title="Judges">
            {data.agreement.pairs.map((p: any) => <div key={p.a + p.b} className="row between small" style={{ padding: "6px 0", borderBottom: "1px solid var(--border)" }}><span>{p.a_name} ↔ {p.b_name}</span><span className="tnum">r = <b>{p.pearson}</b> · gap {p.mean_abs_diff} · n {p.n}</span></div>)}
            {data.agreement.self_preference.map((s: any) => <Notice key={s.judge_id} tone={Math.abs(s.self_preference) >= 0.75 ? "warning" : "ok"} title={`${s.judge_name}: self-preference ${s.self_preference > 0 ? "+" : ""}${s.self_preference}`}>On {s.family} runs it scores {s.own_delta > 0 ? "+" : ""}{s.own_delta} vs other judges, and {s.other_delta > 0 ? "+" : ""}{s.other_delta} on the rest (n = {s.n_own}).</Notice>)}
            {!data.agreement.pairs.length && <p className="muted small">One judge so far. Add a second on the Judging page to see agreement.</p>}
          </Card>
        </div>
      )}

      <Card className="mt-16" pad={false} title="Runs" sub={runFilter ? `Filtered to ${cname({ profile_id: runFilter.split("|")[0], harness_id: runFilter.split("|")[1] })}${runFilter.split("|")[2] ? ` · ${L.benchmarks[runFilter.split("|")[2]]?.title}` : ""}` : `${runs.length} runs`}
        actions={runFilter && <Button size="sm" onClick={() => setRunFilter(null)}>Clear filter</Button>}>
        <Table rowKey={(r: any) => r.id} maxHeight={520} onRow={(r: any) => nav(`/runs/${r.id}`)} initialSort={{ key: "final", dir: -1 }}
          rows={runs.filter((r: any) => !runFilter || (ckey(r) === runFilter.split("|").slice(0, 2).join("|") && (!runFilter.split("|")[2] || r.benchmark_id === runFilter.split("|")[2])))} cols={[
            { key: "cfg", label: "Configuration", sort: (r) => cname(r), render: (r: any) => <LogoName id={clogo(r)} size={18}><b className="small">{cname(r)}</b></LogoName> },
            { key: "bench", label: "Benchmark", sort: (r) => r.benchmark_id, render: (r: any) => <span className="small">{L.benchmarks[r.benchmark_id]?.title || r.benchmark_id} <span className="muted">#{r.iteration}</span></span> },
            { key: "final", label: "Final", num: true, sort: (r) => r.final, render: (r: any) => <ScoreCell v={r.final} /> },
            { key: "corr", label: "Tests", num: true, sort: (r) => r.correctness, render: (r: any) => fmtPct(r.correctness) },
            { key: "q", label: "Quality", num: true, sort: (r) => r.quality, render: (r: any) => fmtNum((r.quality ?? 0) * 100) },
            { key: "rev", label: "Review", num: true, sort: (r) => r.review, render: (r: any) => r.review != null ? fmtNum(r.review * 10, 1) : "–" },
            { key: "time", label: "Time", num: true, sort: (r) => r.wall_s, render: (r: any) => fmtDur(r.wall_s) },
            { key: "tok", label: "Output", num: true, sort: (r) => r.generated_tokens, render: (r: any) => fmtTokens(r.generated_tokens) },
            { key: "loc", label: "Lines", num: true, sort: (r) => r.sloc_total, render: (r: any) => fmtNum(r.sloc_total) },
            { key: "cost", label: "Cost", num: true, sort: (r) => r.cost_usd, render: (r: any) => fmtUsd(r.cost_usd) },
          ]} />
      </Card>

      {compare && <CompareDrawer keysSel={compare} setKeys={setCompare} configs={data.configs} cells={data.cells} name={cname} ckey={ckey} labels={L} onClose={() => setCompare(null)} />}
    </div>
  );
}

function Kpi({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="card kpi">
      <div className="k row muted small">{icon}{label}</div>
      <div style={{ fontSize: 22, fontWeight: 650, marginTop: 4 }} className="tnum">{value}</div>
      <div className="tiny text-2 ellipsis" title={typeof sub === "string" ? sub : undefined}>{sub}</div>
    </div>
  );
}

const esc = (t: string) => t.replace(/[{}|]/g, "");
/** Category-axis labels with the vendor or model-maker logo beside each name, in a column next to the axis. */
function logoAxis(c: any, names: string[], logos: (string | null)[], width: number, fontSize = 11) {
  const rich = logoRich(c.text2, 14);
  rich.n = { color: c.text2, fontSize, width: width - 22, overflow: "truncate", align: "right" };
  rich.gap = { width: 14 };
  // ECharts does not truncate rich-text segments, so shorten long names here (about 0.6 em per character)
  const maxc = Math.max(8, Math.floor((width - 30) / (fontSize * 0.62)));
  const fit = (t: string) => (t.length > maxc ? t.slice(0, maxc - 1) + "…" : t);
  return { color: c.text2, fontSize, rich, formatter: (_: string, i: number) => `{n|${esc(fit(names[i] || ""))}} ${logos[i] ? `{l_${logos[i]}|}` : "{gap|}"}` };
}
const tipLogo = (id: string | null, color: string) => { const u = logoUrl(id, color); return u ? `<img src="${u}" width="14" height="14" style="vertical-align:-2px;margin-right:6px">` : ""; };

function Leaderboard({ configs, name, logo, onClick }: { configs: any[]; name: (c: any) => string; logo: (c: any) => string | null; onClick: (k: string) => void }) {
  const rows = [...configs].reverse();
  const comps = [["correctness", "Correctness"], ["instruction_following", "Instruction following"], ["quality", "Code quality"], ["efficiency", "Efficiency"]];
  return (
    <Chart height={Math.max(220, rows.length * 30 + 60)} onClick={(p) => p.dataIndex !== undefined && onClick(`${rows[p.dataIndex].profile_id}|${rows[p.dataIndex].harness_id}`)} option={(c: any) => ({
      grid: { left: 8, right: 54, top: 30, bottom: 8, containLabel: true },
      legend: { top: 0, left: 0 },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, formatter: (ps: any[]) => {
        const r = rows[ps[0].dataIndex];
        return `${tipLogo(logo(r), c.text)}<b>${name(r)}</b><br/>Final ${(r.final * 100).toFixed(1)}${r.final_ci ? ` ± ${(r.final_ci * 100).toFixed(1)}` : ""}<br/>` + ps.filter((p) => p.seriesType === "bar").map((p) => `${p.marker}${p.seriesName}: ${p.value.toFixed(1)} pts`).join("<br/>");
      } },
      xAxis: axis("value", { max: 100 }),
      yAxis: axis("category", { data: rows.map((r) => name(r)), axisLabel: logoAxis(c, rows.map(name), rows.map(logo), 250, 11.5) }),
      series: [
        ...comps.map(([k, l], i) => ({ type: "bar", stack: "pts", name: l, data: rows.map((r) => r.points?.[k] ?? 0), barWidth: 16, itemStyle: { color: c.palette[i], borderRadius: i === 3 ? [0, 4, 4, 0] : 0 } })),
        { type: "scatter", name: "±95% CI", data: rows.map((r) => r.final * 100), symbolSize: 0, label: { show: true, position: "right", color: c.text, fontWeight: 600, formatter: (p: any) => p.value.toFixed(1), fontSize: 11.5 }, z: 5 },
      ],
    })} />
  );
}

function Heatmap({ configs, cells, benchIds, labels, name, logo, metricKey, onClick }: any) {
  const m = metric(metricKey);
  const rows = [...configs].reverse();
  const vals = cells.map((c: any) => c[metricKey]).filter((v: any) => v !== null && v !== undefined);
  const min = Math.min(...vals), max = Math.max(...vals);
  const data = cells.map((c: any) => [benchIds.indexOf(c.benchmark_id), rows.findIndex((r: any) => r.profile_id === c.profile_id && r.harness_id === c.harness_id), c[metricKey]]).filter((d: any) => d[0] >= 0 && d[1] >= 0 && d[2] !== null && d[2] !== undefined);
  return (
    <Chart height={Math.max(240, rows.length * 28 + 80)} onClick={(p) => p.value && onClick(`${rows[p.value[1]].profile_id}|${rows[p.value[1]].harness_id}|${benchIds[p.value[0]]}`)} option={(c: any) => ({
      grid: { left: 8, right: 16, top: 8, bottom: 44, containLabel: true },
      tooltip: { formatter: (p: any) => `<b>${name(rows[p.value[1]])}</b><br/>${labels.benchmarks[benchIds[p.value[0]]]?.title}<br/>${m.label}: ${m.fmt(p.value[2])}` },
      xAxis: axis("category", { data: benchIds.map((b: string) => (labels.benchmarks[b]?.title || b).split(":")[0]), axisLabel: { color: c.text2, fontSize: 10.5, interval: 0, rotate: benchIds.length > 3 ? 28 : 0, width: 96, overflow: "truncate" }, splitLine: { show: false } }),
      yAxis: axis("category", { data: rows.map((r: any) => name(r)), axisLabel: logoAxis(c, rows.map(name), rows.map(logo), 210), splitLine: { show: false } }),
      visualMap: { min: isFinite(min) ? min : 0, max: isFinite(max) ? max : 1, calculable: false, orient: "horizontal", left: "center", bottom: 0, itemHeight: 140, itemWidth: 10, textStyle: { color: c.text3, fontSize: 10 },
        inRange: { color: m.higher === false || m.log ? [c.palette[1], c.palette[2], c.palette[3]] : [c.danger, c.warn, c.ok] }, formatter: (v: number) => m.fmt(v) },
      series: [{ type: "heatmap", data, label: { show: true, fontSize: 10.5, color: "#fff", formatter: (p: any) => m.fmt(p.value[2]) }, itemStyle: { borderColor: c.surface, borderWidth: 2, borderRadius: 4 } }],
    })} />
  );
}

function Radar({ configs, all, name, logo }: { configs: any[]; all: any[]; name: (c: any) => string; logo: (c: any) => string | null }) {
  const maxSpd = Math.max(...all.map((c) => c.decode_tps || 0), 1);
  const costs = all.map((c) => c.cost_usd_total).filter((v) => v > 0);
  const dims = [
    { name: "Correctness", f: (c: any) => c.correctness }, { name: "Instructions", f: (c: any) => c.instruction_following },
    { name: "Code quality", f: (c: any) => c.quality }, { name: "Efficiency", f: (c: any) => c.efficiency },
    { name: "Consistency", f: (c: any) => c.consistency ?? c.pass_rate }, { name: "Speed (tok/s)", f: (c: any) => (c.decode_tps || 0) / maxSpd },
    ...(costs.length > 1 ? [{ name: "Cheapness", f: (c: any) => c.cost_usd_total > 0 ? Math.min(...costs) / c.cost_usd_total : 1 }] : []),
  ];
  if (!configs.length) return <p className="muted small">Pick configurations above.</p>;
  return (
    <Chart height={320} option={(c: any) => ({
      legend: { bottom: 0, type: "scroll", data: configs.map((cfg) => ({ name: name(cfg), icon: logoUrl(logo(cfg), c.text) ? "image://" + logoUrl(logo(cfg), c.text) : "circle" })), itemWidth: 14, itemHeight: 14 },
      tooltip: {},
      radar: { indicator: dims.map((d) => ({ name: d.name, max: 1 })), radius: "62%", axisName: { color: c.text2, fontSize: 11 }, splitLine: { lineStyle: { color: c.border } }, splitArea: { show: false }, axisLine: { lineStyle: { color: c.border } } },
      series: [{ type: "radar", data: configs.map((cfg, i) => ({ name: name(cfg), value: dims.map((d) => +(d.f(cfg) ?? 0).toFixed(3)), areaStyle: { opacity: 0.12 }, lineStyle: { width: 2, color: c.palette[i] }, itemStyle: { color: c.palette[i] } })) }],
    })} />
  );
}

function paretoSet(points: { x: number; y: number; k: string }[], xHigher: boolean, yHigher: boolean) {
  const better = (a: any, b: any) => (xHigher ? a.x >= b.x : a.x <= b.x) && (yHigher ? a.y >= b.y : a.y <= b.y) && (a.x !== b.x || a.y !== b.y);
  return points.filter((p) => !points.some((q) => better(q, p)));
}

function Scatter({ configs, name, logo, labels, x, y, size, pareto, onClick }: any) {
  const mx = metric(x), my = metric(y), ms = size ? metric(size) : null;
  const pts = configs.filter((c: any) => c[x] != null && c[y] != null).map((c: any) => ({ x: c[x], y: c[y], s: ms ? c[size] : 1, c, k: `${c.profile_id}|${c.harness_id}` }));
  const smax = Math.max(...pts.map((p: any) => p.s || 0), 1);
  const front = pareto ? paretoSet(pts, !!mx.higher, !!my.higher).sort((a: any, b: any) => a.x - b.x) : [];
  const logX = !!mx.log && pts.every((p: any) => p.x > 0);
  return (
    <Chart height={380} onClick={(p) => p.data?.k && onClick(p.data.k)} option={(c: any) => ({
      grid: { left: 8, right: 24, top: 20, bottom: 30, containLabel: true },
      tooltip: { formatter: (p: any) => p.data?.c ? `${tipLogo(logo(p.data.c), c.text)}<b>${name(p.data.c)}</b><br/>${mx.label}: ${mx.fmt(p.data.value[0])}<br/>${my.label}: ${my.fmt(p.data.value[1])}${ms ? `<br/>${ms.label}: ${ms.fmt(p.data.s)}` : ""}` : "" },
      xAxis: axis(logX ? "log" : "value", { name: mx.label, nameLocation: "middle", nameGap: 26, scale: true, axisLabel: { color: c.text3, fontSize: 11, formatter: (v: number) => mx.fmt(v) } }),
      yAxis: axis("value", { name: my.label, scale: true, axisLabel: { color: c.text3, fontSize: 11, formatter: (v: number) => my.fmt(v) } }),
      series: [
        { type: "scatter", data: pts.map((p: any) => ({ value: [p.x, p.y], c: p.c, k: p.k, s: p.s, symbolSize: ms ? 10 + 30 * Math.sqrt((p.s || 0) / smax) : 14,
          itemStyle: { color: labels.profiles[p.c.profile_id]?.kind === "cloud" ? c.palette[3] : c.palette[0], opacity: 0.8, borderColor: c.surface, borderWidth: 1 },
          label: { show: pts.length <= 24, position: "right", formatter: logo(p.c) ? `{l_${logo(p.c)}|} {n|${esc(name(p.c).slice(0, 22))}}` : esc(name(p.c).slice(0, 22)), color: c.text2, fontSize: 10.5, rich: { ...logoRich(c.text2, 12), n: { color: c.text2, fontSize: 10.5 } } } })), labelLayout: { hideOverlap: true } },
        ...(front.length > 1 ? [{ type: "line", data: front.map((p: any) => [p.x, p.y]), showSymbol: false, lineStyle: { type: "dashed", color: c.ok, width: 1.5 }, silent: true, z: 1 }] : []),
      ],
    })} />
  );
}

function quantiles(v: number[]) {
  const s = [...v].sort((a, b) => a - b);
  const q = (p: number) => {
    const i = (s.length - 1) * p;
    const lo = Math.floor(i), hi = Math.ceil(i);
    return s[lo] + (s[hi] - s[lo]) * (i - lo);
  };
  return [s[0], q(0.25), q(0.5), q(0.75), s[s.length - 1]];
}

function Box({ configs, runs, name, logo, ckey }: any) {
  const rows = [...configs].reverse();
  const data = rows.map((c: any) => {
    const v = runs.filter((r: any) => ckey(r) === ckey(c) && r.final != null).map((r: any) => r.final * 100);
    return v.length ? quantiles(v) : [0, 0, 0, 0, 0];
  });
  const scatter = rows.flatMap((c: any, i: number) => runs.filter((r: any) => ckey(r) === ckey(c) && r.final != null).map((r: any) => [r.final * 100, i + (Math.random() - 0.5) * 0.3]));
  return (
    <Chart height={Math.max(240, rows.length * 26 + 50)} option={(c: any) => ({
      grid: { left: 8, right: 16, top: 10, bottom: 8, containLabel: true },
      tooltip: { trigger: "item" },
      xAxis: axis("value", { min: 0, max: 100 }),
      yAxis: axis("category", { data: rows.map((r: any) => name(r)), axisLabel: logoAxis(c, rows.map(name), rows.map(logo), 210) }),
      series: [{ type: "boxplot", data, itemStyle: { color: c.accent + "22", borderColor: c.accent }, boxWidth: [6, 14] },
        { type: "scatter", data: scatter, symbolSize: 5, itemStyle: { color: c.palette[1], opacity: 0.55 }, tooltip: { formatter: (p: any) => `run score ${p.value[0].toFixed(0)}` } }],
    })} />
  );
}

function Tokens({ configs, runs, name, logo, ckey }: any) {
  const rows = [...configs].reverse();
  const sum = (c: any, f: (r: any) => number) => runs.filter((r: any) => ckey(r) === ckey(c)).reduce((a: number, r: any) => a + (f(r) || 0), 0);
  return (
    <Chart height={Math.max(240, rows.length * 26 + 60)} option={(c: any) => ({
      grid: { left: 8, right: 16, top: 30, bottom: 8, containLabel: true },
      legend: { top: 0, left: 0 },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v: number) => fmtTokens(v) },
      xAxis: [axis("value", { axisLabel: { color: c.text3, fontSize: 11, formatter: (v: number) => fmtTokens(v) } })],
      yAxis: axis("category", { data: rows.map((r: any) => name(r)), axisLabel: logoAxis(c, rows.map(name), rows.map(logo), 210) }),
      series: [
        { type: "bar", stack: "t", name: "Uncached prompt", data: rows.map((r: any) => sum(r, (x) => (x.total_prompt_tokens || 0) - (x.cached_prompt_tokens || 0))), barWidth: 14 },
        { type: "bar", stack: "t", name: "Cached prompt", data: rows.map((r: any) => sum(r, (x) => x.cached_prompt_tokens)) },
        { type: "bar", stack: "t", name: "Output", data: rows.map((r: any) => sum(r, (x) => x.generated_tokens)), itemStyle: { borderRadius: [0, 4, 4, 0] } },
      ],
    })} />
  );
}

function HarnessCompare({ configs, labels }: any) {
  const profs: string[] = Array.from(new Set<string>(configs.map((c: any) => c.profile_id)));
  const hs: string[] = Array.from(new Set<string>(configs.map((c: any) => c.harness_id)));
  return (
    <Chart height={300} option={(c: any) => ({
      grid: { left: 8, right: 16, top: 30, bottom: 8, containLabel: true }, legend: { top: 0 },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v: number) => v?.toFixed(1) },
      xAxis: axis("category", { data: profs.map((p) => labels.profiles[p]?.name || p), axisLabel: { color: c.text2, fontSize: 11, interval: 0, rich: { ...logoRich(c.text2, 16), n: { color: c.text2, fontSize: 11, width: 120, overflow: "truncate", align: "center" } },
        formatter: (_: string, i: number) => { const id = profileLogo(labels.profiles[profs[i]]); return `${id ? `{l_${id}|}
` : ""}{n|${esc(labels.profiles[profs[i]]?.name || profs[i])}}`; } } }),
      yAxis: axis("value", { max: 100 }),
      series: hs.map((h, i) => ({ type: "bar", name: labels.harnesses[h] || h, data: profs.map((p) => { const x = configs.find((cc: any) => cc.profile_id === p && cc.harness_id === h); return x ? +(x.final * 100).toFixed(1) : null; }), itemStyle: { color: c.palette[i], borderRadius: [4, 4, 0, 0] }, barMaxWidth: 26 })),
    })} />
  );
}

function RubricHeat({ rubric, configs, name, logo }: any) {
  const dims: string[] = Array.from(new Set<string>(rubric.flatMap((r: any) => Object.keys(r).filter((k) => !["profile_id", "harness_id"].includes(k)))));
  const rows = [...configs].reverse().filter((c: any) => rubric.some((r: any) => r.profile_id === c.profile_id && r.harness_id === c.harness_id));
  const data: any[] = [];
  rows.forEach((c: any, y: number) => {
    const r = rubric.find((x: any) => x.profile_id === c.profile_id && x.harness_id === c.harness_id);
    dims.forEach((d, x) => r?.[d] != null && data.push([x, y, r[d]]));
  });
  return (
    <Chart height={Math.max(240, rows.length * 26 + 70)} option={(c: any) => ({
      grid: { left: 8, right: 16, top: 8, bottom: 40, containLabel: true },
      tooltip: { formatter: (p: any) => `${name(rows[p.value[1]])}<br/>${dims[p.value[0]]}: ${p.value[2]}` },
      xAxis: axis("category", { data: dims, axisLabel: { color: c.text2, fontSize: 10.5, interval: 0, rotate: 30 }, splitLine: { show: false } }),
      yAxis: axis("category", { data: rows.map((r: any) => name(r)), axisLabel: logoAxis(c, rows.map(name), rows.map(logo), 190), splitLine: { show: false } }),
      visualMap: { min: 1, max: 10, show: false, inRange: { color: [c.danger, c.warn, c.ok] } },
      series: [{ type: "heatmap", data, label: { show: true, fontSize: 10, color: "#fff", formatter: (p: any) => p.value[2].toFixed(1) }, itemStyle: { borderColor: c.surface, borderWidth: 2, borderRadius: 3 } }],
    })} />
  );
}

function CompareDrawer({ keysSel, setKeys, configs, cells, name, ckey, labels, onClose }: any) {
  const [a, b] = keysSel.map((k: string) => configs.find((c: any) => ckey(c) === k));
  const opts = configs.map((c: any) => ({ value: ckey(c), label: name(c) }));
  const rows = METRICS.filter((m) => m.level.includes("config"));
  const benches: string[] = Array.from(new Set<string>(cells.map((c: any) => c.benchmark_id)));
  return (
    <Drawer open onClose={onClose} wide title="Compare configurations" sub="Side by side on every aggregate metric and per benchmark.">
      <div className="grid grid-2 mb-16">
        <Field label="A"><Select value={keysSel[0]} onChange={(v) => setKeys([v, keysSel[1]])} options={opts} aria-label="Configuration A" /></Field>
        <Field label="B"><Select value={keysSel[1]} onChange={(v) => setKeys([keysSel[0], v])} options={opts} aria-label="Configuration B" /></Field>
      </div>
      {a && b && (
        <>
          <Card pad={false}>
            <table className="table">
              <thead><tr><th>Metric</th><th className="num">{name(a)}</th><th className="num">{name(b)}</th><th className="num">Δ (B − A)</th></tr></thead>
              <tbody>{rows.map((m) => {
                const va = a[m.key], vb = b[m.key];
                const d = va != null && vb != null ? vb - va : null;
                const good = d === null || d === 0 || m.higher === undefined ? "" : (d > 0) === m.higher ? "ok" : "danger";
                return <tr key={m.key}><td>{m.label}</td><td className="num">{va != null ? m.fmt(va) : "–"}</td><td className="num">{vb != null ? m.fmt(vb) : "–"}</td>
                  <td className={`num ${good}`}>{d === null ? "–" : SCORE_KEYS.has(m.key) ? `${d > 0 ? "+" : ""}${(d * 100).toFixed(1)} pts` : `${d > 0 ? "+" : d < 0 ? "−" : ""}${m.fmt(Math.abs(d))}`}</td></tr>;
              })}</tbody>
            </table>
          </Card>
          <Card className="mt-16" title="Per benchmark (final score)">
            <Chart height={280} option={(c: any) => ({
              grid: { left: 8, right: 16, top: 30, bottom: 8, containLabel: true }, legend: { top: 0 },
              tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
              xAxis: axis("category", { data: benches.map((x) => (labels.benchmarks[x]?.title || x).split(":")[0].slice(0, 18)), axisLabel: { color: c.text2, fontSize: 11, interval: 0 } }),
              yAxis: axis("value", { max: 100 }),
              series: [a, b].map((cfg, i) => ({ type: "bar", name: name(cfg), data: benches.map((bid) => { const x = cells.find((cc: any) => ckey(cc) === ckey(cfg) && cc.benchmark_id === bid); return x ? +(x.final * 100).toFixed(1) : null; }), itemStyle: { color: c.palette[i], borderRadius: [4, 4, 0, 0] }, barMaxWidth: 30 })),
            })} />
          </Card>
        </>
      )}
    </Drawer>
  );
}


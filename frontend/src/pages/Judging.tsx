import { useQueryClient } from "@tanstack/react-query";
import { Gavel, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Logo, LogoName, profileLogo } from "../logos";
import { api, qs } from "../api";
import { Chart, axis } from "../charts";
import { JobLine, JobPanel } from "../components";
import { fmtUsd, plural } from "../format";
import { usePlans, useProfiles, useJobs } from "../queries";
import {
  Badge, Button, Card, Checkbox, Chip, Empty, Field, Input, Notice, NumInput, PageHead, Select, Table, Textarea, Toggle, useConfirm, useToast,
} from "../ui";

export default function Judging() {
  const [sp] = useSearchParams();
  const plans = usePlans();
  const profiles = useProfiles();
  const jobs = useJobs();
  const nav = useNavigate();
  const toast = useToast();
  const confirm = useConfirm();
  const qc = useQueryClient();
  const [planIds, setPlanIds] = useState<string[]>(sp.get("plan") ? [sp.get("plan")!] : []);
  const [judgeIds, setJudgeIds] = useState<string[]>([]);
  const [defaults, setDefaults] = useState<any>(null);
  const [rubric, setRubric] = useState<any[]>([]);
  const [guidance, setGuidance] = useState("");
  const [opt, setOpt] = useState<any>({ include_static: false, skip_reviewed: true, budget_usd: 1, concurrency: 4, max_output_tokens: 12000 });
  const [jobId, setJobId] = useState<string | null>(null);
  const [res, setRes] = useState<any>(null);
  const [judgeFilter, setJudgeFilter] = useState("all");
  useEffect(() => {
    api.get("/judge/defaults").then((d) => {
      setDefaults(d);
      setRubric(d.rubric);
      setGuidance(d.guidance);
    });
  }, []);
  useEffect(() => {
    if (!planIds.length && plans.data?.length) setPlanIds([plans.data.find((p: any) => !p.sample && p.counts.done)?.id || plans.data[0].id]);
  }, [plans.data, planIds.length]);
  const loadResults = () => {
    if (!planIds.length) return setRes(null);
    api.get(`/results${qs({ plan_ids: planIds.join(",") })}`).then(setRes).catch(() => setRes(null));
  };
  useEffect(loadResults, [planIds.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  const active = jobs.filter((j) => j.kind === "judge" && ["queued", "running"].includes(j.status));
  useEffect(() => {
    const j = jobs.find((x) => x.id === jobId);
    if (j && ["done", "failed", "cancelled"].includes(j.status)) loadResults();
  }, [jobs, jobId]); // eslint-disable-line react-hooks/exhaustive-deps
  const judgeOptions = (profiles.data || []).filter((p: any) => !(p.tags || []).includes("sample"));
  const doneRuns = (plans.data || []).filter((p: any) => planIds.includes(p.id)).reduce((a: number, p: any) => a + (p.counts.done || 0), 0);
  const reviewedBy = (jid: string) => (res?.reviews || []).filter((r: any) => r.judge_id === jid).length;
  const toDo = judgeIds.reduce((a, j) => a + Math.max(0, doneRuns - (opt.skip_reviewed ? reviewedBy(j) : 0)), 0);
  const estCost = judgeIds.reduce((a, j) => {
    const p = judgeOptions.find((x: any) => x.id === j);
    if (!p || p.kind === "local") return a;
    const n = Math.max(0, doneRuns - (opt.skip_reviewed ? reviewedBy(j) : 0));
    return a + n * (25000 * (p.pricing?.input || 0) + 4000 * (p.pricing?.output || 0)) / 1e6;
  }, 0);
  const candidateFamilies = new Set(Object.values(res?.labels?.profiles || {}).map((p: any) => p.vendor || p.arch).filter(Boolean));
  const runningJob = jobs.find((x) => x.id === (jobId || active[0]?.id) && ["queued", "running"].includes(x.status));
  const start = async () => {
    try {
      const r = await api.post("/judge", { judge_profile_ids: judgeIds, plan_ids: planIds, rubric, guidance, ...opt });
      setJobId(r.job_id);
      toast.info("Judging started", `${plural(toDo, "review")}, blind and shuffled`);
    } catch (e) {
      toast.err("Could not start judging", e);
    }
  };
  const reviews = (res?.reviews || []).filter((r: any) => judgeFilter === "all" || r.judge_id === judgeFilter);
  const runById = Object.fromEntries((res?.runs || []).map((r: any) => [r.id, r]));
  const judges = res?.agreement?.judges || [];
  return (
    <div className="page">
      <PageHead title="Judging" sub="LLM judges review the code each agent wrote, blind: no model, harness or profile names, shuffled order. Use two or more judges to measure agreement and self-preference." />
      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1.1fr)", alignItems: "start" }}>
        <div className="col" style={{ gap: 16 }}>
          <Card title="1. What to review">
            <div className="pill-list">
              {(plans.data || []).map((p: any) => <Chip key={p.id} on={planIds.includes(p.id)} onClick={() => setPlanIds((x) => x.includes(p.id) ? x.filter((y) => y !== p.id) : [...x, p.id])}>{p.name} · {p.counts.done || 0} done</Chip>)}
              {!(plans.data || []).length && <span className="muted small">No plans yet.</span>}
            </div>
            <div className="mt-12"><Toggle checked={opt.skip_reviewed} onChange={(v) => setOpt({ ...opt, skip_reviewed: v })} label="Skip runs a judge has already reviewed" /></div>
          </Card>
          <Card title="2. Judges" sub="Any profile can judge. Cloud judges run in parallel; local judges load on the GPU one at a time.">
            {judgeOptions.length ? (
              <div className="col">
                {judgeOptions.map((p: any) => (
                  <Checkbox key={p.id} checked={judgeIds.includes(p.id)} onChange={() => setJudgeIds((x) => x.includes(p.id) ? x.filter((y) => y !== p.id) : [...x, p.id])}>
                    <Logo id={profileLogo(p)} size={20} /> <b>{p.name}</b> <span className="muted small">{p.kind === "local" ? "local" : `${p.provider?.name || ""} · ${fmtUsd(p.pricing?.input)}/${fmtUsd(p.pricing?.output)} per M`}</span>
                    {candidateFamilies.has(p.provider?.vendor) && <Badge tone="warn" className="mt-8">judges its own vendor's runs</Badge>}
                  </Checkbox>
                ))}
              </div>
            ) : <Empty title="No profiles" action={<Button onClick={() => nav("/profiles")}>Create a profile</Button>}>A judge is just a profile, usually a strong cloud model.</Empty>}
            {judgeIds.length === 1 && !judges.some((j: any) => j.id !== judgeIds[0]) && <Notice tone="warning">With one judge there is no agreement check, and a judge may favour code from its own model family. Two judges from different vendors are recommended.</Notice>}
          </Card>
          <Card title="3. Rubric" sub="Each dimension is scored 1-10; the overall score feeds code quality." actions={<>
            <Button size="sm" variant="ghost" icon={<RotateCcw size={13} />} onClick={() => { setRubric(defaults.rubric); setGuidance(defaults.guidance); }}>Reset</Button>
            <Button size="sm" icon={<Plus size={13} />} onClick={() => setRubric([...rubric, { key: `dimension_${rubric.length + 1}`, label: "New dimension", description: "" }])}>Add</Button>
          </>}>
            <div className="col">
              {rubric.map((d, i) => (
                <div key={i} className="row" style={{ alignItems: "flex-start" }}>
                  <Input value={d.key} onChange={(e) => setRubric(rubric.map((x, j) => j === i ? { ...x, key: e.target.value.replace(/\W/g, "_").toLowerCase() } : x))} style={{ width: 140 }} className="mono" aria-label="Dimension key" />
                  <Input value={d.description} onChange={(e) => setRubric(rubric.map((x, j) => j === i ? { ...x, description: e.target.value } : x))} aria-label="Dimension description" />
                  <Button variant="ghost" iconOnly icon={<Trash2 size={13} />} aria-label="Remove dimension" onClick={() => setRubric(rubric.filter((_, j) => j !== i))} disabled={rubric.length <= 1} />
                </div>
              ))}
              <Field label="Guidance for the judge"><Textarea rows={3} value={guidance} onChange={(e) => setGuidance(e.target.value)} /></Field>
            </div>
          </Card>
          <Card title="4. Limits">
            <div className="form-grid">
              <Field label="Budget for this judging job"><NumInput value={opt.budget_usd} onChange={(v) => setOpt({ ...opt, budget_usd: v ?? 0 })} min={0} max={1000} suffix="USD" /></Field>
              <Field label="Parallel reviews (cloud)"><NumInput value={opt.concurrency} onChange={(v) => setOpt({ ...opt, concurrency: Math.round(v || 1) })} min={1} max={16} /></Field>
              <Field label="Max output tokens"><NumInput value={opt.max_output_tokens} onChange={(v) => setOpt({ ...opt, max_output_tokens: Math.round(v || 12000) })} min={1000} max={64000} /></Field>
              <Field label="Context"><Toggle checked={opt.include_static} onChange={(v) => setOpt({ ...opt, include_static: v })} label="Show the judge the static-analysis summary" /></Field>
            </div>
          </Card>
          <Card>
            <div className="row between">
              <div><b>{plural(toDo, "review")}</b><div className="small muted">≈ {fmtUsd(estCost)} for cloud judges (about 25k tokens in, 4k out per review)</div></div>
              <Button variant="primary" icon={<Gavel size={15} />} disabled={!judgeIds.length || !planIds.length || !toDo} onClick={start}>Start judging</Button>
            </div>
            {runningJob && <div className="mt-12"><JobLine job={runningJob} /></div>}
          </Card>
        </div>
        <div className="col" style={{ gap: 16 }}>
          {(jobId || active[0]) && <JobPanel jobId={jobId || active[0]?.id} />}
          {judges.length > 0 && (
            <Card title="Judge agreement" sub="Pearson correlation of overall scores on the same runs; self-preference compares how a judge scores its own vendor's runs versus other judges.">
              {res.agreement.pairs.length ? res.agreement.pairs.map((p: any) => (
                <div key={p.a + p.b} className="row between small" style={{ padding: "6px 0", borderBottom: "1px solid var(--border)" }}>
                  <span>{p.a_name} ↔ {p.b_name}</span>
                  <span className="tnum">r = <b>{p.pearson ?? "–"}</b> · mean gap {p.mean_abs_diff} pts · n = {p.n}</span>
                </div>
              )) : <p className="muted small">Needs two judges reviewing the same runs.</p>}
              {res.agreement.self_preference.map((s: any) => (
                <Notice key={s.judge_id} tone={Math.abs(s.self_preference) >= 0.75 ? "warning" : "ok"} title={`${s.judge_name}: ${s.self_preference > 0 ? "+" : ""}${s.self_preference} points on its own vendor's runs`}>
                  Relative to other judges it scores {familyName(s.family)} runs {s.own_delta > 0 ? "+" : ""}{s.own_delta} and everything else {s.other_delta > 0 ? "+" : ""}{s.other_delta} (n = {s.n_own} own runs). {Math.abs(s.self_preference) < 0.75 ? "No meaningful self-preference." : "Consider weighting another judge more."}
                </Notice>
              ))}
              {res.agreement.pairs[0] && <AgreementScatter res={res} a={res.agreement.pairs[0].a} b={res.agreement.pairs[0].b} />}
            </Card>
          )}
          <Card title="Reviews" sub={`${reviews.length} shown`} actions={judges.length > 0 && <>
            <Select value={judgeFilter} onChange={setJudgeFilter} options={[{ value: "all", label: "All judges" }, ...judges.map((j: any) => ({ value: j.id, label: `${j.name} (${j.reviews})` }))]} aria-label="Filter judge" />
            {judgeFilter !== "all" && <Button size="sm" variant="danger" iconOnly icon={<Trash2 size={13} />} aria-label="Delete this judge's reviews" onClick={async () => {
              if (!(await confirm({ title: "Delete these reviews?", body: "Reviews from this judge on the selected plans are removed; you can judge again.", danger: true, confirm: "Delete reviews" })).ok) return;
              for (const p of planIds) await api.del(`/reviews${qs({ judge_id: judgeFilter, plan_id: p })}`);
              setJudgeFilter("all");
              loadResults();
              qc.invalidateQueries({ queryKey: ["results"] });
            }} />}
          </>} pad={false}>
            {reviews.length ? (
              <Table rowKey={(r: any) => r.run_id + r.judge_id} rows={reviews} maxHeight={520} onRow={(r: any) => nav(`/runs/${r.run_id}`)} cols={[
                { key: "run", label: "Run", width: "42%", render: (r: any) => {
                  const run = runById[r.run_id];
                  const lp = res.labels.profiles[run?.profile_id];
                  return <div style={{ minWidth: 0 }}>
                    <LogoName id={profileLogo(lp)} size={18}><b className="small">{lp?.name || run?.profile_id}</b></LogoName>
                    <div className="tiny muted">{res.labels.benchmarks[run?.benchmark_id]?.title || run?.benchmark_id} · {res.labels.harnesses?.[run?.harness_id] || run?.harness_id}{run?.iteration ? ` #${run.iteration}` : ""}</div>
                    <div className="tiny muted">judged by {r.judge_name}</div>
                  </div>;
                } },
                { key: "overall", label: "Score", num: true, width: 64, sort: (r) => r.overall, render: (r: any) => <b>{r.overall ?? "–"}</b> },
                { key: "summary", label: "Summary", render: (r: any) => <span className="small text-2" style={{ display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{r.summary}</span> },
              ]} />
            ) : <Empty title="No reviews yet">Choose plans and judges on the left.</Empty>}
          </Card>
        </div>
      </div>
    </div>
  );
}

const FAMILY: Record<string, string> = { openai: "OpenAI", anthropic: "Anthropic", google: "Google", qwen: "Qwen", meta: "Meta", mistral: "Mistral",
  deepseek: "DeepSeek", zai: "Z.ai", moonshot: "Moonshot", minimax: "MiniMax", xai: "xAI", microsoft: "Microsoft", ibm: "IBM", nvidia: "NVIDIA" };
const familyName = (f: string) => FAMILY[f] || f;

function AgreementScatter({ res, a, b }: { res: any; a: string; b: string }) {
  const pts = useMemo(() => {
    const by: Record<string, any> = {};
    for (const r of res.reviews) (by[r.run_id] ||= {})[r.judge_id] = r.overall;
    return Object.values(by).filter((x: any) => x[a] != null && x[b] != null).map((x: any) => [x[a] + (Math.random() - 0.5) * 0.25, x[b] + (Math.random() - 0.5) * 0.25]);
  }, [res, a, b]);
  const name = (j: string) => res.agreement.judges.find((x: any) => x.id === j)?.name || j;
  // zoom to the scores that occur: judges rarely go below 5, and a 0-10 axis squeezes every point into a corner
  const lo = pts.length ? Math.max(0, Math.floor(Math.min(...pts.flat())) - 1) : 0;
  return (
    <Chart height={260} option={(c: any) => ({
      grid: { left: 12, right: 16, top: 28, bottom: 36, containLabel: true },
      tooltip: { formatter: (p: any) => `${name(a)}: ${p.value[0].toFixed(0)} · ${name(b)}: ${p.value[1].toFixed(0)}` },
      xAxis: axis("value", { min: lo, max: 10, name: name(a), nameLocation: "middle", nameGap: 26 }),
      yAxis: axis("value", { min: lo, max: 10, name: name(b), nameLocation: "end", nameTextStyle: { align: "left" } }),
      series: [{ type: "scatter", data: pts, symbolSize: 10, itemStyle: { opacity: 0.75 } },
        { type: "line", data: [[lo, lo], [10, 10]], showSymbol: false, lineStyle: { type: "dashed", color: c.text3 }, silent: true }],
    })} />
  );
}

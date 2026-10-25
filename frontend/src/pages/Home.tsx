import { ArrowRight, BarChart3, Boxes, CheckCircle2, Cloud, FlaskConical, Layers, PlayCircle, Sparkles, Wand2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { JobLine, SystemCards } from "../components";
import { Dyno, useDynoState } from "../dyno";
import { fmtAgo, fmtUsd, plural } from "../format";
import { useDeps, useHarnesses, useJobs, useModels, usePlans, useProfiles, useProviders, useSample, useSpecs } from "../queries";
import { Badge, Button, Card, Empty, PageHead, Progress, Skeleton, StatusBadge, useToast } from "../ui";

export default function Home({ onOnboard }: { onOnboard: () => void }) {
  const nav = useNavigate();
  const specs = useSpecs();
  const deps = useDeps();
  const models = useModels();
  const providers = useProviders();
  const profiles = useProfiles();
  const harnesses = useHarnesses();
  const plans = usePlans();
  const sample = useSample();
  const jobs = useJobs();
  const qc = useQueryClient();
  const toast = useToast();
  const readyHarness = (harnesses.data || []).filter((h: any) => h.status === "ready").length;
  const steps = [
    { done: (deps.data || []).filter((d: any) => d.level === "required").every((d: any) => d.ok), label: "Install the requirements", to: "/setup", icon: <CheckCircle2 size={15} /> },
    { done: (models.data || []).some((m: any) => m.status === "ready") || (providers.data || []).length > 0, label: "Add a local model or a cloud provider", to: "/models", icon: <Boxes size={15} /> },
    { done: (profiles.data || []).some((p: any) => !(p.tags || []).includes("sample")), label: "Create an LLM profile", to: "/profiles", icon: <Wand2 size={15} /> },
    { done: readyHarness > 0, label: "Build at least one harness", to: "/harnesses", icon: <Layers size={15} /> },
    { done: (plans.data || []).some((p: any) => !p.sample), label: "Run a benchmark plan", to: "/plans/new", icon: <PlayCircle size={15} /> },
  ];
  const doneCount = steps.filter((s) => s.done).length;
  const realPlans = (plans.data || []).filter((p: any) => !p.sample);
  return (
    <div className="page">
      <PageHead title="Overview" sub="Your setup, recent runs and what to do next."
        actions={<>
          <Button onClick={onOnboard}>Setup wizard</Button>
          <Button variant="primary" icon={<PlayCircle size={15} />} onClick={() => nav("/plans/new")}>New benchmark plan</Button>
        </>} />
      <DynoHero />
      {specs.isLoading ? <Skeleton h={130} /> : <SystemCards specs={specs.data} />}
      <div className="grid grid-3 mt-16" style={{ gridTemplateColumns: "1.15fr 1fr 1fr" }}>
        <Card title="Getting started" sub={`${doneCount} of ${steps.length} done`} actions={<Progress value={doneCount / steps.length} style={{ width: 90 }} tone={doneCount === steps.length ? "ok" : ""} />}>
          <div className="col" style={{ gap: 4 }}>
            {steps.map((s) => (
              <button key={s.label} className="btn ghost" style={{ justifyContent: "flex-start", height: 38 }} onClick={() => nav(s.to)}>
                {s.done ? <CheckCircle2 size={16} className="ok" /> : <span style={{ width: 16, height: 16, border: "2px solid var(--border-strong)", borderRadius: "50%" }} />}
                <span style={{ textDecoration: s.done ? "line-through" : undefined, color: s.done ? "var(--text-3)" : undefined }}>{s.label}</span>
                <ArrowRight size={14} style={{ marginLeft: "auto" }} className="muted" />
              </button>
            ))}
          </div>
        </Card>
        <Card title="Inventory">
          <div className="grid grid-2" style={{ gap: 12 }}>
            {[
              { k: "Local models", v: (models.data || []).filter((m: any) => m.status === "ready").length, to: "/models", i: <Boxes size={14} /> },
              { k: "Cloud providers", v: (providers.data || []).length, to: "/providers", i: <Cloud size={14} /> },
              { k: "LLM profiles", v: (profiles.data || []).length, to: "/profiles", i: <Wand2 size={14} /> },
              { k: "Harnesses ready", v: readyHarness, to: "/harnesses", i: <Layers size={14} /> },
            ].map((x) => (
              <button key={x.k} className="card clickable" style={{ padding: 12, textAlign: "left", font: "inherit", color: "inherit" }} onClick={() => nav(x.to)}>
                <div className="row muted small">{x.i}{x.k}</div>
                <div style={{ fontSize: 24, fontWeight: 650 }} className="tnum">{x.v}</div>
              </button>
            ))}
          </div>
        </Card>
        <Card title="Activity" actions={<Button size="sm" variant="ghost" onClick={() => nav("/jobs")}>All</Button>}>
          {jobs.length ? jobs.slice(0, 5).map((j) => <JobLine key={j.id} job={j} />) : <p className="muted small">Downloads, builds, runs and judging appear here.</p>}
        </Card>
      </div>
      <div className="section-title">
        <h2>Recent plans</h2>
        <div style={{ marginLeft: "auto" }} className="row">
          <Button size="sm" onClick={() => nav("/plans")}>All runs</Button>
          <Button size="sm" icon={<BarChart3 size={13} />} onClick={() => nav("/results")}>Results</Button>
        </div>
      </div>
      {plans.isLoading ? <Skeleton h={90} /> : realPlans.length ? (
        <div className="grid grid-3">
          {realPlans.slice(0, 6).map((p: any) => {
            const done = (p.counts.done || 0) + (p.counts.failed || 0) + (p.counts.cancelled || 0) + (p.counts.skipped || 0);
            return (
              <Card key={p.id} onClick={() => nav(`/plans/${p.id}`)}>
                <div className="row between"><b className="ellipsis">{p.name}</b><StatusBadge status={p.status} /></div>
                <div className="small muted mt-8">{plural(p.n_runs, "run")} · {fmtAgo(p.created_at)} · {fmtUsd(p.spent_usd)} cloud</div>
                <Progress value={done / Math.max(p.n_runs, 1)} style={{ marginTop: 10 }} tone={p.counts.failed ? "warn" : "ok"} />
              </Card>
            );
          })}
        </div>
      ) : (
        <Card>
          <Empty icon={<FlaskConical size={22} />} title="No benchmark plans yet"
            action={<div className="row">
              <Button variant="primary" onClick={() => nav("/plans/new")}>Create a plan</Button>
              {sample.data?.available && !sample.data?.loaded && (
                <Button icon={<Sparkles size={14} />} onClick={async () => {
                  try {
                    await api.post("/sample");
                    qc.invalidateQueries();
                    toast.ok("Sample results loaded");
                    nav("/results");
                  } catch (e) {
                    toast.err("Could not load the sample", e);
                  }
                }}>Explore sample results</Button>
              )}
              {sample.data?.loaded && <Badge tone="accent">Sample results loaded</Badge>}
            </div>}>
            A plan runs profiles × harnesses × benchmarks × iterations and fills the Results dashboard.
          </Empty>
        </Card>
      )}
    </div>
  );
}

function DynoHero() {
  const nav = useNavigate();
  const jobs = useJobs();
  const { state, detail } = useDynoState();
  const plan = jobs.find((j) => j.kind === "plan" && j.status === "running");
  const copy: Record<string, [string, string, React.ReactNode?]> = {
    idle: ["The dyno is ready.", "Strap a model to the rocket: choose profiles, harnesses and benchmarks, and LLMDyno measures memory fit, speed, cost, correctness and code quality.",
      <Button variant="primary" icon={<PlayCircle size={15} />} onClick={() => nav("/plans/new")}>Start a benchmark</Button>],
    running: ["On the dyno.", `${detail}. Every agent runs in a sandbox behind a spend-capped proxy.`,
      plan && <Button variant="primary" onClick={() => nav(`/plans/${plan.ref}`)}>Watch it live</Button>],
    warmup: ["Warming up.", "A quick profile test is checking speed, real VRAM use and tool calling.", null],
    judging: ["On the podium.", `${detail}. Judges see the code blind: no model or harness names.`,
      <Button onClick={() => nav("/judging")}>Open judging</Button>],
    celebrate: ["Plan finished!", "Fresh numbers are on the results dashboard.",
      <Button variant="primary" icon={<BarChart3 size={15} />} onClick={() => nav("/results")}>See results</Button>],
    panic: ["Everything stopped.", "Runs were cancelled, containers removed and llama-server killed. Paused plans and finished results are untouched.", null],
  };
  const [title, sub, action] = copy[state];
  return (
    <Card className="dyno-hero mb-16">
      <div className="row" style={{ gap: 20, alignItems: "center" }}>
        <Dyno state={state} size={104} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <h2 className={state === "panic" ? "danger" : undefined}>{title}</h2>
          <p className="muted mt-4" style={{ maxWidth: 640 }}>{sub}</p>
        </div>
        {action}
      </div>
    </Card>
  );
}

import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, ArrowRight, Check, Cloud, Cpu, Gavel, Hammer, Layers, PlayCircle, RefreshCw, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { LogoName, profileLogo } from "../logos";
import { api } from "../api";
import { VerdictBadge } from "../components";
import { fmtCtx, fmtMin, fmtUsd, plural } from "../format";
import { keys, useBenchmarks, useHarnesses, useProfiles, useProviders, useSuites, useVendors } from "../queries";
import {
  Badge, Button, Card, Checkbox, Empty, Field, Input, Notice, NumInput, PageHead, Skeleton, Spinner, Stepper, Toggle, useToast,
} from "../ui";
import { SmokeSummary } from "./Profiles";

const STEPS = ["Profiles", "Harnesses", "Benchmarks", "Options", "Review & start"];

export default function PlanNew() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const profiles = useProfiles();
  const harnesses = useHarnesses();
  const benchmarks = useBenchmarks();
  const suites = useSuites();
  const providers = useProviders();
  const vendors = useVendors();
  const [step, setStep] = useState(0);
  const [profileIds, setProfileIds] = useState<string[]>([]);
  const [harnessIds, setHarnessIds] = useState<string[]>(["pi"]);
  const [benchIds, setBenchIds] = useState<string[]>([]);
  const [iterations, setIterations] = useState(1);
  const [name, setName] = useState("");
  const [opt, setOpt] = useState<any>({ quality: true, cloud_concurrency: 3, timeout_multiplier: 1, budget_usd: null, allow_spill: false, auto_judge: false, memory_gb: 12 });
  const [judgeIds, setJudgeIds] = useState<string[]>([]);
  const [pf, setPf] = useState<any>(null);
  const [pfBusy, setPfBusy] = useState(false);
  const [ack, setAck] = useState(false);
  const [starting, setStarting] = useState(false);
  const usable = (profiles.data || []).filter((p: any) => !(p.tags || []).includes("sample"));
  const provById = Object.fromEntries((providers.data || []).map((p: any) => [p.id, p]));
  const vendorById = Object.fromEntries((vendors.data || []).map((v: any) => [v.id, v]));

  const stylesOf = (p: any) => {
    if (p.kind === "local") return ["openai-chat", "openai-responses"];
    const prov = provById[p.provider_id];
    if (!prov) return [];
    return prov.vendor === "custom" ? [prov.api_style] : Object.keys(vendorById[prov.vendor]?.styles || { [prov.api_style]: 1 });
  };
  const compatible = (p: any, h: any) => h.apis.some((a: string) => stylesOf(p).includes(a));
  const selectedProfiles = usable.filter((p: any) => profileIds.includes(p.id));
  const selectedHarnesses = (harnesses.data || []).filter((h: any) => harnessIds.includes(h.id));
  const expanded = useMemo(() => {
    const out: string[] = [];
    const bySuite = Object.fromEntries((suites.data || []).map((s: any) => [s.id, s]));
    for (const id of benchIds) for (const b of bySuite[id]?.benchmark_ids || [id]) if (!out.includes(b)) out.push(b);
    return out;
  }, [benchIds, suites.data]);
  const nRuns = profileIds.length * harnessIds.length * expanded.length * iterations;

  const spec = () => ({ name: name.trim() || undefined, profile_ids: profileIds, harness_ids: harnessIds, benchmark_ids: benchIds, iterations,
    options: { ...opt, judge: opt.auto_judge && judgeIds.length ? { judge_profile_ids: judgeIds } : undefined } });
  const runPreflight = async () => {
    setPfBusy(true);
    setAck(false);
    try {
      setPf(await api.post("/plans/preflight", spec()));
    } catch (e) {
      toast.err("Preflight failed", e);
    } finally {
      setPfBusy(false);
    }
  };
  useEffect(() => {
    if (step === 4) runPreflight();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);
  const dangers = (pf?.warnings || []).filter((w: any) => w.ack);
  const start = async () => {
    setStarting(true);
    try {
      const r = await api.post("/plans", { ...spec(), acknowledge_risks: ack, start: true });
      qc.invalidateQueries({ queryKey: keys.plans });
      toast.ok("Plan started", plural(nRuns, "run"));
      nav(`/plans/${r.plan_id}`);
    } catch (e) {
      toast.err("Could not start the plan", e);
    } finally {
      setStarting(false);
    }
  };
  const canNext = [profileIds.length > 0, harnessIds.length > 0 && selectedProfiles.every((p: any) => selectedHarnesses.some((h: any) => compatible(p, h))), expanded.length > 0, !opt.auto_judge || judgeIds.length > 0, true][step];
  const toggle = (arr: string[], set: (x: string[]) => void, id: string) => set(arr.includes(id) ? arr.filter((x) => x !== id) : [...arr, id]);

  return (
    <div className="page">
      <div className="row mb-12"><Link to="/plans" className="row small"><ArrowLeft size={14} /> Runs</Link></div>
      <PageHead title="New benchmark plan" sub="A plan runs every selected profile × harness × benchmark, as many iterations as you choose. Local profiles share the GPU one at a time; cloud runs go in parallel."
        actions={<div className="card" style={{ padding: "8px 14px" }}><span className="small muted">Matrix</span> <b className="tnum">{profileIds.length} × {harnessIds.length} × {expanded.length} × {iterations} = {plural(nRuns, "run")}</b></div>} />
      <div className="stepper">
        {STEPS.map((s, i) => <button key={s} className={`step ${i === step ? "on" : i < step ? "done" : ""}`} onClick={() => i <= step || [0, 1, 2, 3].slice(0, i).every((k) => [profileIds.length > 0, harnessIds.length > 0, expanded.length > 0, true][k]) ? setStep(i) : undefined}><span className="n">{i < step ? <Check size={12} /> : i + 1}</span>{s}</button>)}
      </div>

      {step === 0 && (profiles.isLoading ? <Skeleton h={200} /> : usable.length ? (
        <>
          <div className="row mb-12"><Button size="sm" onClick={() => setProfileIds(usable.map((p: any) => p.id))}>Select all</Button><Button size="sm" variant="ghost" onClick={() => setProfileIds([])}>Clear</Button></div>
          <div className="grid grid-auto">
            {usable.map((p: any) => (
              <Card key={p.id} onClick={() => toggle(profileIds, setProfileIds, p.id)} selected={profileIds.includes(p.id)}>
                <div className="row">
                  <Checkbox checked={profileIds.includes(p.id)} onChange={() => toggle(profileIds, setProfileIds, p.id)}><LogoName id={profileLogo(p)} size={18}><b>{p.name}</b></LogoName></Checkbox>
                  <span className="spacer" />{p.kind === "local" ? <Cpu size={15} className="muted" /> : <Cloud size={15} className="muted" />}
                </div>
                <div className="small muted mt-8">{p.kind === "local" ? `${p.model?.name || "model missing"}` : `${p.provider?.name || "?"} · ${p.remote_model}`} · {fmtCtx(p.params.ctx)}</div>
                <div className="row wrap mt-8">{p.kind === "local" && <VerdictBadge verdict={p.fit?.verdict} />}<SmokeSummary smoke={p.smoke} /></div>
              </Card>
            ))}
          </div>
        </>
      ) : <Card><Empty title="No profiles to run" action={<Button variant="primary" onClick={() => nav("/profiles")}>Create a profile</Button>}>Create at least one local or cloud profile first.</Empty></Card>)}

      {step === 1 && (
        <div className="col" style={{ gap: 16 }}>
          <div className="grid grid-auto">
            {(harnesses.data || []).map((h: any) => {
              const on = harnessIds.includes(h.id);
              const incompatible = selectedProfiles.filter((p: any) => !compatible(p, h));
              return (
                <Card key={h.id} onClick={() => toggle(harnessIds, setHarnessIds, h.id)} selected={on}>
                  <div className="row"><Checkbox checked={on} onChange={() => toggle(harnessIds, setHarnessIds, h.id)}><b>{h.name}</b></Checkbox><span className="muted small mono">v{h.version}</span><span className="spacer" />
                    {h.status === "ready" ? <Badge tone="ok">ready</Badge> : <Badge tone="warn"><Hammer size={11} /> not built</Badge>}</div>
                  <p className="small text-2 mt-8">{h.description}</p>
                  {incompatible.length > 0 && <div className="tiny warn mt-8"><AlertTriangle size={11} /> Not compatible with {incompatible.map((p: any) => p.name).join(", ")} (skipped for those)</div>}
                </Card>
              );
            })}
          </div>
          {selectedProfiles.length > 0 && harnessIds.length > 0 && (
            <Card title="Compatibility" sub="Each profile must work with at least one selected harness. Incompatible pairs are not run.">
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>Profile</th>{selectedHarnesses.map((h: any) => <th key={h.id}>{h.name}</th>)}</tr></thead>
                  <tbody>{selectedProfiles.map((p: any) => (
                    <tr key={p.id}><td><LogoName id={profileLogo(p)} size={18}>{p.name}</LogoName></td>{selectedHarnesses.map((h: any) => <td key={h.id}>{compatible(p, h) ? <Check size={15} className="ok" /> : <span className="row small danger"><X size={14} /> {p.kind === "local" ? "" : `needs ${h.apis.join("/")}`}</span>}</td>)}</tr>
                  ))}</tbody>
                </table>
              </div>
            </Card>
          )}
          {selectedHarnesses.some((h: any) => h.status !== "ready") && <Notice tone="warning" action={<Button size="xs" onClick={() => nav("/harnesses")}>Go to Harnesses</Button>}>Build the selected harness images before starting.</Notice>}
        </div>
      )}

      {step === 2 && (
        <div className="col" style={{ gap: 16 }}>
          <Card title="Suites">
            <div className="grid grid-2">
              {(suites.data || []).map((s: any) => (
                <Checkbox key={s.id} checked={benchIds.includes(s.id)} onChange={() => toggle(benchIds, setBenchIds, s.id)}>
                  <b>{s.name}</b> <span className="muted small">· {s.benchmark_ids.length} benchmarks</span>
                  <div className="tiny muted">{s.description}</div>
                </Checkbox>
              ))}
            </div>
          </Card>
          <Card title="Individual benchmarks">
            <div className="grid grid-2">
              {(benchmarks.data || []).map((b: any) => (
                <Checkbox key={b.id} checked={benchIds.includes(b.id) || expanded.includes(b.id)} disabled={!benchIds.includes(b.id) && expanded.includes(b.id)} onChange={() => toggle(benchIds, setBenchIds, b.id)}>
                  <b>{b.title}</b> <span className="muted small">· {b.category} · ~{fmtMin(b.expected_minutes?.local)}</span>
                  {!benchIds.includes(b.id) && expanded.includes(b.id) && <span className="tiny muted"> (in a selected suite)</span>}
                </Checkbox>
              ))}
            </div>
          </Card>
        </div>
      )}

      {step === 3 && (
        <div className="grid grid-2" style={{ alignItems: "start" }}>
          <Card title="Plan">
            <div className="col" style={{ gap: 14 }}>
              <Field label="Name"><Input value={name} onChange={(e) => setName(e.target.value)} placeholder={`Plan ${new Date().toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}`} /></Field>
              <Field label="Iterations per profile × harness × benchmark" tip="Repeat runs measure consistency: the dashboard shows mean, spread, 95% confidence and pass@k." hint="3 is a good minimum for comparing close models">
                <Stepper value={iterations} onChange={setIterations} min={1} max={20} />
              </Field>
              <Toggle checked={opt.quality} onChange={(v) => setOpt({ ...opt, quality: v })} label="Code-quality analysis after each run (static analysis + probes)" />
            </div>
          </Card>
          <Card title="Limits">
            <div className="form-grid">
              <Field label="Cloud runs in parallel"><NumInput value={opt.cloud_concurrency} onChange={(v) => setOpt({ ...opt, cloud_concurrency: Math.max(1, Math.round(v || 1)) })} min={1} max={16} /></Field>
              <Field label="Plan budget (cloud)" hint="Empty = provider budgets only"><NumInput allowEmpty value={opt.budget_usd} onChange={(v) => setOpt({ ...opt, budget_usd: v })} min={0} max={10000} suffix="USD" /></Field>
              <Field label="Timeout multiplier" tip="Scales every stage timeout, e.g. 2× for slow CPU-offloaded profiles."><NumInput value={opt.timeout_multiplier} onChange={(v) => setOpt({ ...opt, timeout_multiplier: v || 1 })} min={0.25} max={10} suffix="×" /></Field>
              <Field label="Agent memory limit"><NumInput value={opt.memory_gb} onChange={(v) => setOpt({ ...opt, memory_gb: Math.round(v || 12) })} min={2} max={128} suffix="GB" /></Field>
              <div className="full"><Toggle checked={opt.allow_spill} onChange={(v) => setOpt({ ...opt, allow_spill: v })} label="Allow local profiles that spill out of VRAM (results are flagged)" /></div>
            </div>
          </Card>
          <Card title={<span className="row"><Gavel size={15} /> Judge automatically when done</span>} sub="You can always judge later from the Judging page with any rubric.">
            <Toggle checked={opt.auto_judge} onChange={(v) => setOpt({ ...opt, auto_judge: v })} label="Start blind review when the plan finishes" />
            {opt.auto_judge && (
              <div className="col mt-12">
                {(profiles.data || []).filter((p: any) => !(p.tags || []).includes("sample")).map((p: any) => (
                  <Checkbox key={p.id} checked={judgeIds.includes(p.id)} onChange={() => toggle(judgeIds, setJudgeIds, p.id)}><LogoName id={profileLogo(p)} size={18}>{p.name} <span className="muted small">({p.kind})</span></LogoName></Checkbox>
                ))}
                {opt.auto_judge && !judgeIds.length && <span className="tiny warn">Pick at least one judge.</span>}
              </div>
            )}
          </Card>
        </div>
      )}

      {step === 4 && (
        <div className="col" style={{ gap: 16 }}>
          {pfBusy || !pf ? <Card><div className="row"><Spinner /> Checking images, keys, memory fit, budgets and estimates…</div></Card> : (
            <>
              <div className="grid grid-4">
                <Card><div className="stat"><span className="k">Runs</span><span className="v">{pf.n_runs}</span><span className="s">{plural(pf.benchmarks.length, "benchmark")} · {iterations}× each</span></div></Card>
                <Card><div className="stat"><span className="k">Estimated time</span><span className="v">{fmtMin(pf.estimate.minutes)}</span><span className="s">local {fmtMin(pf.estimate.local_minutes)} · cloud {fmtMin(pf.estimate.cloud_minutes)} (÷ parallel)</span></div></Card>
                <Card><div className="stat"><span className="k">Estimated cloud cost</span><span className="v">{fmtUsd(pf.estimate.cost_usd)}</span><span className="s">from reference token usage</span></div></Card>
                <Card><div className="stat"><span className="k">Status</span><span className={`v ${pf.ok ? "ok" : "danger"}`}>{pf.ok ? "Ready" : "Blocked"}</span><span className="s">{pf.blocking.length} blocking · {pf.warnings.length} warnings</span></div></Card>
              </div>
              {pf.blocking.map((b: any, i: number) => <Notice key={i} tone="danger" action={b.harness ? <Button size="xs" onClick={() => nav("/harnesses")}>Build it</Button> : undefined}>{b.text}</Notice>)}
              {pf.warnings.map((w: any, i: number) => <Notice key={i} tone={w.level === "danger" ? "danger" : "warning"}>{w.text}</Notice>)}
              <Card title="Per profile" pad={false}>
                <table className="table">
                  <thead><tr><th>Profile</th><th>Kind</th><th>Memory</th><th className="num">Est. time</th><th className="num">Est. cost</th></tr></thead>
                  <tbody>{pf.profiles.map((r: any) => (
                    <tr key={r.profile_id}><td><b>{r.name}</b></td><td>{r.kind}</td><td>{r.memory ? <VerdictBadge verdict={r.memory.verdict} /> : <span className="muted">–</span>}</td>
                      <td className="num">{fmtMin(r.minutes)}</td><td className="num">{r.kind === "local" ? "GPU energy" : fmtUsd(r.cost)}</td></tr>
                  ))}</tbody>
                </table>
              </Card>
              {dangers.length > 0 && pf.ok && (
                <Notice tone="danger" title="Some profiles carry serious risks">
                  <Checkbox checked={ack} onChange={setAck}>I understand: run anyway and flag the affected results</Checkbox>
                </Notice>
              )}
            </>
          )}
          <div className="row">
            <Button icon={<RefreshCw size={14} />} onClick={runPreflight} loading={pfBusy}>Re-check</Button>
            <span className="spacer" />
            <Button variant="primary" icon={<PlayCircle size={15} />} disabled={!pf?.ok || (dangers.length > 0 && !ack)} loading={starting} onClick={start}>Start {plural(nRuns, "run")}</Button>
          </div>
        </div>
      )}

      {step < 4 && (
        <div className="row mt-16">
          <Button icon={<ArrowLeft size={14} />} disabled={step === 0} onClick={() => setStep(step - 1)}>Back</Button>
          <Button variant="primary" icon={<ArrowRight size={14} />} disabled={!canNext} onClick={() => setStep(step + 1)}>{step === 3 ? "Review" : "Next"}</Button>
          {!canNext && step === 1 && selectedProfiles.length > 0 && <span className="small warn">Every profile needs at least one compatible harness.</span>}
          {!canNext && step === 3 && <span className="small warn">Pick a judge, or turn off automatic judging.</span>}
          <span className="spacer" />
          <Badge tone="outline"><Layers size={11} /> {plural(nRuns, "run")}</Badge>
        </div>
      )}
    </div>
  );
}

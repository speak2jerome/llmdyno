import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, BarChart3, Gavel, Pause, Pencil, Play, RotateCcw, Square, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { LogoName, profileLogo } from "../logos";
import { api } from "../api";
import { Chart, axis } from "../charts";
import { JobPanel } from "../components";
import { plural, fmtDur, fmtMib, fmtNum, fmtTokens, fmtUsd, scoreColor } from "../format";
import { keys, useBenchmarks, useHarnesses, useProfiles } from "../queries";
import { Badge, Button, Card, Notice, PageHead, Progress, ScoreCell, Skeleton, Stat, StatusBadge, Table, useConfirm, useToast } from "../ui";
import { useResync, useTopic } from "../ws";

export default function PlanDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const profiles = useProfiles();
  const harnesses = useHarnesses();
  const benchmarks = useBenchmarks();
  const [plan, setPlan] = useState<any>(null);
  const [runs, setRuns] = useState<Record<string, any>>({});
  const [gpu, setGpu] = useState<any[]>([]);
  const [showLog, setShowLog] = useState(false);
  const [now, setNow] = useState(Date.now() / 1000);
  const load = () => api.get(`/plans/${id}`).then((p) => {
    setPlan(p);
    setRuns(Object.fromEntries(p.runs.map((r: any) => [r.id, r])));
  }).catch((e) => toast.err("Could not load the plan", e));
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);
  useResync(load);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(t);
  }, []);
  const reloadTimer = useRef<any>();
  useTopic(id ? `plan:${id}` : null, (m) => {
    if (m.kind === "run") {
      setRuns((r) => ({ ...r, [m.data.id]: { ...(r[m.data.id] || {}), ...m.data } }));
      // the plan's own "running" event can fire before this page subscribed; a run moving means it started
      if (plan?.status === "queued" && (m.data.status !== "queued" || m.data.stage)) load();
    }
    else if (m.kind === "plan") setPlan((p: any) => ({ ...p, ...m.data }));
    else if (m.kind === "gpu") setGpu((g) => [...g.slice(-180), m.data]);
    clearTimeout(reloadTimer.current);
    reloadTimer.current = setTimeout(() => qc.invalidateQueries({ queryKey: keys.plans }), 800);
  });
  const pname = (pid: string) => (profiles.data || []).find((p: any) => p.id === pid)?.name || pid;
  const plogo = (pid: string) => profileLogo((profiles.data || []).find((p: any) => p.id === pid));
  const hname = (hid: string) => (harnesses.data || []).find((h: any) => h.id === hid)?.name || hid;
  const btitle = (bid: string) => (benchmarks.data || []).find((b: any) => b.id === bid)?.title || bid;
  const list = Object.values(runs);
  const counts = useMemo(() => list.reduce((a: any, r: any) => ({ ...a, [r.status]: (a[r.status] || 0) + 1 }), {}), [list]);
  const finished = (counts.done || 0) + (counts.failed || 0) + (counts.cancelled || 0) + (counts.skipped || 0);
  const doneRuns = list.filter((r: any) => r.status === "done" && r.wall_s);
  const avgWall = doneRuns.length ? doneRuns.reduce((a: number, r: any) => a + r.wall_s, 0) / doneRuns.length : null;
  const remaining = list.filter((r: any) => ["queued", "running", "grading"].includes(r.status)).length;
  const live = plan && ["running", "queued"].includes(plan.status);
  const rows = useMemo(() => {
    const keysSet: string[] = [];
    for (const r of list as any[]) {
      const k = `${r.profile_id}|${r.harness_id}`;
      if (!keysSet.includes(k)) keysSet.push(k);
    }
    return keysSet;
  }, [list]);
  // local runs cost electricity (GPU energy x price per kWh); cloud runs cost provider tokens
  const isLocal = (r: any) => (profiles.data || []).find((p: any) => p.id === r.profile_id)?.kind === "local";
  const apiCost = list.filter((r: any) => !isLocal(r)).reduce((a: number, r: any) => a + (r.cost_usd || 0), 0);
  const energyCost = list.filter(isLocal).reduce((a: number, r: any) => a + (r.cost_usd || 0), 0);
  const act = async (path: string, ok: string) => {
    try {
      await api.post(`/plans/${id}/${path}`);
      toast.ok(ok);
      load();
    } catch (e) {
      toast.err("Action failed", e);
    }
  };
  if (!plan) return <div className="page"><Skeleton h={300} /></div>;
  const elapsed = plan.started_at ? (plan.ended_at || now) - plan.started_at : 0;
  const lastGpu = gpu[gpu.length - 1];
  return (
    <div className="page">
      <div className="row mb-12"><Link to="/plans" className="row small"><ArrowLeft size={14} /> Runs</Link></div>
      <PageHead title={<span className="row">{plan.name} <Button size="xs" variant="ghost" iconOnly icon={<Pencil size={12} />} aria-label="Rename plan" onClick={async () => {
        const r = await confirm({ title: "Rename plan", input: { label: "Name", initial: plan.name }, confirm: "Rename" });
        if (r.ok) api.patch(`/plans/${id}`, { name: r.value }).then(load).catch((e) => toast.err("Could not rename", e));
      }} /></span>}
        sub={<span className="row wrap"><StatusBadge status={plan.status} /> {plural(plan.profile_ids.length, "profile")} · {plural(plan.harness_ids.length, "harness", "harnesses")} · {plural(plan.benchmark_ids.length, "benchmark")} · {plural(plan.iterations, "iteration")}{plan.sample ? " · bundled sample" : ""}</span>}
        actions={<>
          {plan.status === "running" && <Button icon={<Pause size={14} />} onClick={() => act("pause", "Pausing: runs in progress will finish")}>Pause</Button>}
          {["paused", "cancelled", "failed", "done"].includes(plan.status) && (counts.queued || 0) > 0 && <Button variant="primary" icon={<Play size={14} />} onClick={() => act("resume", "Plan resumed")}>Resume</Button>}
          {live && <Button variant="danger" icon={<Square size={13} />} onClick={async () => { if ((await confirm({ title: "Cancel the plan?", body: "Running agents are stopped; finished results are kept.", danger: true, confirm: "Cancel plan" })).ok) act("cancel", "Plan cancelled"); }}>Cancel</Button>}
          {!live && ((counts.failed || 0) + (counts.cancelled || 0)) > 0 && <Button icon={<RotateCcw size={14} />} onClick={() => act("retry", "Retrying failed and cancelled runs")}>{counts.failed && counts.cancelled ? "Retry failed & cancelled" : counts.failed ? "Retry failed" : "Retry cancelled"} ({(counts.failed || 0) + (counts.cancelled || 0)})</Button>}
          <Button icon={<Gavel size={14} />} onClick={() => nav(`/judging?plan=${id}`)} disabled={!counts.done}>Judge</Button>
          <Button icon={<BarChart3 size={14} />} onClick={() => nav(`/results?plans=${id}`)} disabled={!counts.done}>Results</Button>
          {!live && <Button variant="ghost" iconOnly icon={<Trash2 size={14} />} aria-label="Delete plan" onClick={async () => {
            if (!(await confirm({ title: `Delete ${plan.name}?`, body: "Runs, workspaces, transcripts and reviews are removed permanently.", danger: true, confirm: "Delete plan" })).ok) return;
            api.del(`/plans/${id}`).then(() => { qc.invalidateQueries({ queryKey: keys.plans }); nav("/plans"); }).catch((e) => toast.err("Could not delete", e));
          }} />}
        </>} />
      <div className="grid grid-4">
        <Card><Stat label="Progress" value={`${finished} / ${list.length}`} sub={<Progress value={finished / Math.max(1, list.length)} tone={counts.failed ? "warn" : "ok"} style={{ marginTop: 6 }} />} /></Card>
        <Card><Stat label="Elapsed" value={fmtDur(elapsed)} sub={live && avgWall ? `about ${fmtDur(avgWall * remaining)} left at the current pace` : plan.ended_at ? "finished" : "–"} /></Card>
        <Card><Stat label="Outcomes" value={<span className="row" style={{ gap: 10 }}><span className="ok">{counts.done || 0}</span><span className="danger">{counts.failed || 0}</span><span className="muted">{counts.cancelled || 0}</span></span>} sub="done · failed · cancelled" /></Card>
        <Card><Stat label="Spend" value={fmtUsd(apiCost + energyCost)} sub={[
          apiCost || !energyCost ? `API ${fmtUsd(apiCost)}${plan.options?.budget_usd ? ` of ${fmtUsd(plan.options.budget_usd)} cap` : ""}` : "",
          energyCost ? `GPU electricity ${fmtUsd(energyCost)}` : "",
        ].filter(Boolean).join(" · ")} /></Card>
      </div>
      {gpu.length > 1 && (
        <Card className="mt-16" title="GPU (live)" sub={lastGpu ? `${fmtMib(lastGpu.vram_mib)} of ${fmtMib(lastGpu.vram_total_mib, 0)} · ${Math.round(lastGpu.power_w)} W · ${lastGpu.util_pct}% util${lastGpu.shared_mib ? ` · shared ${lastGpu.shared_mib} MiB` : ""}` : ""}>
          <Chart height={130} option={(c: any) => ({
            grid: { left: 4, right: 8, top: 10, bottom: 4, containLabel: true },
            tooltip: { trigger: "axis" },
            xAxis: axis("category", { data: gpu.map((g) => new Date(g.ts * 1000).toLocaleTimeString()), axisLabel: { show: false } }),
            yAxis: [axis("value", { max: lastGpu?.vram_total_mib, axisLabel: { color: c.text3, fontSize: 10, formatter: (v: number) => `${(v / 1024).toFixed(0)}G` } }), axis("value", { splitLine: { show: false }, axisLabel: { color: c.text3, fontSize: 10, formatter: "{value} W" } })],
            series: [{ type: "line", name: "VRAM", showSymbol: false, areaStyle: { opacity: 0.15 }, data: gpu.map((g) => g.vram_mib) },
              { type: "line", name: "Power", yAxisIndex: 1, showSymbol: false, data: gpu.map((g) => g.power_w), lineStyle: { width: 1.5 } }],
          })} />
        </Card>
      )}
      {plan.job && <div className="mt-16">
        <div className="row mb-8"><Button size="sm" variant="ghost" onClick={() => setShowLog((s) => !s)}>{showLog ? "Hide" : "Show"} executor log</Button>
          {plan.job.status === "failed" && <Badge tone="danger">executor failed: {plan.job.detail}</Badge>}</div>
        {showLog && <JobPanel jobId={plan.job.id} />}
      </div>}
      <div className="section-title"><h2>Matrix</h2><span className="sub">Each square is one iteration; colour shows status or score. Click to open the run.</span></div>
      <Card pad={false}>
        <div className="table-wrap" style={{ padding: 10 }}>
          <table className="matrix">
            <thead><tr><th>Profile · harness</th>{plan.benchmark_ids.map((b: string) => <th key={b} title={btitle(b)}>{btitle(b).split(":")[0].slice(0, 28)}</th>)}</tr></thead>
            <tbody>
              {rows.map((k) => {
                const [pid, hid] = k.split("|");
                return (
                  <tr key={k}>
                    <th><LogoName id={plogo(pid)} size={20}><div>{pname(pid)}</div><div className="tiny muted">{hname(hid)}</div></LogoName></th>
                    {plan.benchmark_ids.map((bid: string) => {
                      const cell = (list as any[]).filter((r) => r.profile_id === pid && r.harness_id === hid && r.benchmark_id === bid).sort((a, b) => a.iteration - b.iteration);
                      const doneC = cell.filter((r) => r.status === "done");
                      const mean = doneC.length ? doneC.reduce((a, r) => a + (r.correctness || 0), 0) / doneC.length : null;
                      return (
                        <td key={bid} className="cell">
                          <div className="dots">
                            {cell.map((r) => (
                              <span key={r.id} className={`d ${r.status}`} title={`#${r.iteration} ${r.status}${r.correctness !== null && r.correctness !== undefined ? ` · ${Math.round(r.correctness * 100)}% tests` : ""}${r.stage ? ` · ${r.stage}` : ""}`}
                                style={r.status === "done" ? { background: scoreColor(r.correctness) } : undefined} onClick={() => nav(`/runs/${r.id}`)} role="link" />
                            ))}
                          </div>
                          {mean !== null && <div className="tiny tnum mt-8" style={{ marginTop: 4, color: scoreColor(mean) }}>{Math.round(mean * 100)}% tests</div>}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
      {counts.failed > 0 && <div className="mt-16"><Notice tone="warning">{counts.failed} run(s) failed. Open one to see the error; common causes are a missing image, a model that no longer fits in free VRAM, or a provider rejecting the key.</Notice></div>}
      <div className="section-title"><h2>All runs</h2></div>
      <Card pad={false}>
        <Table rowKey={(r: any) => r.id} rows={list} onRow={(r: any) => nav(`/runs/${r.id}`)} initialSort={{ key: "status", dir: 1 }} maxHeight={560} cols={[
          { key: "profile", label: "Profile", sort: (r) => pname(r.profile_id), render: (r: any) => <LogoName id={plogo(r.profile_id)} size={22}><b>{pname(r.profile_id)}</b><div className="tiny muted">{hname(r.harness_id)}</div></LogoName> },
          { key: "bench", label: "Benchmark", sort: (r) => r.benchmark_id, render: (r: any) => <span className="small">{btitle(r.benchmark_id)} <span className="muted">#{r.iteration}</span></span> },
          { key: "status", label: "Status", sort: (r) => ["running", "grading", "queued", "failed", "done", "cancelled", "skipped"].indexOf(r.status), render: (r: any) => <div><StatusBadge status={r.status} />{r.stage && <div className="tiny muted">{r.stage}</div>}</div> },
          { key: "corr", label: "Tests", num: true, sort: (r) => r.correctness, render: (r: any) => r.correctness !== null && r.correctness !== undefined ? <ScoreCell v={r.correctness} /> : "–" },
          { key: "if", label: "Instr.", num: true, sort: (r) => r.instruction_following, render: (r: any) => <ScoreCell v={r.instruction_following} /> },
          { key: "wall", label: "Time", num: true, sort: (r) => r.wall_s, render: (r: any) => r.wall_s ? fmtDur(r.wall_s) : r.started_at && ["running", "grading"].includes(r.status) ? <span className="info">{fmtDur(now - r.started_at)}</span> : "–" },
          { key: "tok", label: "Output", num: true, sort: (r) => r.generated_tokens, render: (r: any) => fmtTokens(r.generated_tokens) },
          { key: "tps", label: "tok/s", num: true, sort: (r) => r.decode_tps, render: (r: any) => <span className="row" style={{ justifyContent: "flex-end", gap: 4 }}>{fmtNum(r.decode_tps)}{r.spill_detected && <Badge tone="danger" title="VRAM spilled to system RAM during this run">spill</Badge>}</span> },
          { key: "cost", label: "Cost", num: true, sort: (r) => r.cost_usd, render: (r: any) => fmtUsd(r.cost_usd) },
          { key: "err", label: "Error", render: (r: any) => r.error ? <span className="small danger ellipsis" style={{ maxWidth: 260, display: "inline-block" }} title={r.error}>{r.error}</span> : null },
        ]} />
      </Card>
    </div>
  );
}

import { ArrowLeft, CheckCircle2, Download, FileCode2, Folder, RotateCcw, Square, XCircle } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Logo, profileLogo } from "../logos";
import { api, download } from "../api";
import { Chart, axis } from "../charts";
import { Gauge } from "../components";
import { fmtBytes, fmtDur, fmtMib, fmtNum, fmtPct, fmtTokens, fmtUsd } from "../format";
import { useBenchmarks, useHarnesses, useProfiles } from "../queries";
import { applyEvents, emptyState, Transcript, TState } from "../transcript";
import {
  Badge, Button, Card, Code, Empty, KV, Notice, PageHead, ScoreCell, Segmented, Select, Skeleton, Stat, StatusBadge, Table, Tabs, Toggle,
  useConfirm, useToast,
} from "../ui";
import { useResync, useTopic } from "../ws";

type Tab = "transcript" | "files" | "grading" | "quality" | "reviews" | "requests" | "gpu" | "logs" | "details";

export default function RunDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const confirm = useConfirm();
  const profiles = useProfiles();
  const harnesses = useHarnesses();
  const benchmarks = useBenchmarks();
  const [run, setRun] = useState<any>(null);
  const [tab, setTab] = useState<Tab>("transcript");
  const [ts, setTs] = useState<TState>(emptyState());
  const loadedTo = useRef(0);
  const buffer = useRef<any[]>([]);
  const ready = useRef(false);
  const [follow, setFollow] = useState(true);
  const [filter, setFilter] = useState<"all" | "messages" | "tools">("all");
  const [now, setNow] = useState(Date.now() / 1000);
  const load = () => api.get(`/runs/${id}`).then(setRun).catch((e) => toast.err("Could not load the run", e));
  // full transcript from the server; live events that arrive meanwhile are buffered and replayed after it
  const loadTranscript = () => {
    ready.current = false;
    buffer.current = [];
    api.get(`/runs/${id}/transcript`).then((r) => {
      loadedTo.current = r.total;
      ready.current = true;
      const pending = buffer.current.filter((x) => x.i >= r.total).map((x) => x.ev);
      buffer.current = [];
      setTs(applyEvents(emptyState(), [...r.events, ...pending]));
    }).catch(() => { ready.current = true; });
  };
  useEffect(() => {
    setTs(emptyState());
    loadedTo.current = 0;
    load();
    loadTranscript();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);
  // events streamed while the socket was down are gone: reload the run and its transcript
  useResync(() => {
    load();
    loadTranscript();
  });
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(t);
  }, []);
  // live updates: batch deltas into animation frames so streaming stays smooth
  const queue = useRef<any[]>([]);
  const raf = useRef<number | null>(null);
  useTopic(id ? `run:${id}` : null, (m) => {
    if (m.kind === "status") setRun((r: any) => (r ? { ...r, ...m.data } : r));
    if (m.kind !== "transcript") return;
    if (!ready.current) {
      buffer.current.push(m.data);
      return;
    }
    if (m.data.i < loadedTo.current) return;
    loadedTo.current = m.data.i + 1;
    queue.current.push(m.data.ev);
    if (raf.current === null) {
      raf.current = requestAnimationFrame(() => {
        raf.current = null;
        const evs = queue.current;
        queue.current = [];
        setTs((s) => applyEvents(s, evs));
      });
    }
  });
  useEffect(() => {
    if (run && ["done", "failed", "cancelled"].includes(run.status) && run.metrics === undefined) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.status]);
  const prevStatus = useRef<string>();
  useEffect(() => {
    if (prevStatus.current && prevStatus.current !== run?.status && ["done", "failed"].includes(run?.status)) load();
    prevStatus.current = run?.status;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.status]);
  if (!run) return <div className="page"><Skeleton h={400} /></div>;
  const prof = (profiles.data || []).find((p: any) => p.id === run.profile_id);
  const pName = prof?.name || run.snapshot?.profile?.name || run.profile_id;
  const hName = (harnesses.data || []).find((h: any) => h.id === run.harness_id)?.name || run.harness_id;
  const bench = (benchmarks.data || []).find((b: any) => b.id === run.benchmark_id);
  const ctx = run.snapshot?.profile?.params?.ctx || prof?.params?.ctx;
  const m = run.metrics || {};
  const live = ["running", "grading", "queued"].includes(run.status);
  const lastIn = ts.lastUsage ? (ts.lastUsage.input || 0) + (ts.lastUsage.output || 0) : m.peak_context_tokens;
  const elapsed = run.started_at ? (run.ended_at || now) - run.started_at : 0;
  const sample = !!run.snapshot?.sample;
  return (
    <div className="page">
      <div className="row mb-12"><Link to={`/plans/${run.plan_id}`} className="row small"><ArrowLeft size={14} /> Plan</Link></div>
      <PageHead title={<span className="row wrap"><Logo id={profileLogo(prof || run.snapshot?.profile && { ...run.snapshot.profile, vendor: run.snapshot.provider?.vendor, model: run.snapshot.model })} size={30} />{pName} <span className="muted" style={{ fontWeight: 450 }}>on</span> {bench?.title || run.benchmark_id}</span>}
        sub={<span className="row wrap"><StatusBadge status={run.status} />{run.stage && <Badge tone="info">{run.stage}</Badge>}<span>{hName} · iteration {run.iteration} · {fmtDur(elapsed)}</span></span>}
        actions={<>
          {live && <Button variant="danger" icon={<Square size={13} />} onClick={async () => {
            if (!(await confirm({ title: "Stop this run?", danger: true, confirm: "Stop run" })).ok) return;
            api.post(`/runs/${id}/cancel`).then(() => toast.info("Stopping…")).catch((e) => toast.err("Could not stop", e));
          }}>Stop</Button>}
          {!live && !sample && <Button icon={<RotateCcw size={14} />} onClick={() => api.post(`/runs/${id}/retry`).then(() => { toast.ok("Run queued again"); nav(`/plans/${run.plan_id}`); }).catch((e) => toast.err("Could not retry", e))}>Retry</Button>}
          {!sample && run.dir && <Button icon={<Download size={14} />} onClick={() => download(`/runs/${id}/download`)}>Workspace .zip</Button>}
        </>} />
      {run.error && <div className="mb-16"><Notice tone="danger" title="Run failed">{run.error}</Notice></div>}
      <div className="card" style={{ padding: "12px 18px", display: "grid", gridTemplateColumns: "auto repeat(7, minmax(0,1fr))", gap: 18, alignItems: "center" }}>
        <Gauge value={ctx && lastIn ? lastIn / ctx : 0} label="context used" size={64} />
        <Stat label="Context" value={fmtTokens(lastIn)} sub={`of ${fmtTokens(ctx)}`} />
        <Stat label="Tests" value={run.correctness !== null && run.correctness !== undefined ? `${m.tests_passed ?? "?"}/${m.tests_total ?? "?"}` : "–"} sub={run.correctness !== null && run.correctness !== undefined ? fmtPct(run.correctness) : live ? "after grading" : ""} tone={run.correctness >= 0.8 ? "ok" : run.correctness !== null && run.correctness !== undefined ? "warn" : ""} />
        <Stat label="Output tokens" value={fmtTokens(ts.outTokens || m.generated_tokens)} sub={`${fmtTokens(ts.inTokens || m.total_prompt_tokens)} prompt`} />
        <Stat label={live ? "Live speed" : "Decode speed"} value={`${fmtNum(live ? ts.live.tps : m.decode_tps ?? ts.live.tps, 1)}`} sub="tokens/s" />
        <Stat label="Turns" value={ts.turns || m.turns || 0} sub={`${ts.toolCalls || m.n_tool_calls || 0} tool calls`} />
        <Stat label="Cache hit" value={fmtPct(m.cache_hit_ratio ?? (ts.lastUsage?.cached && ts.lastUsage.input ? ts.lastUsage.cached / ts.lastUsage.input : null))} sub="prompt tokens reused" />
        <Stat label="Cost" value={fmtUsd(run.cost_usd ?? ts.cost)} sub={m.cost_basis || (prof?.kind === "local" ? "GPU energy" : "provider tokens")} />
      </div>
      {m.spill_detected && <div className="mt-12"><Notice tone="danger" title="VRAM spilled into system memory during this run">About {fmtNum(m.gpu_spill_mib)} MiB went to shared memory; speed numbers are not representative of this GPU.</Notice></div>}
      <div className="mt-16">
        <Tabs value={tab} onChange={setTab} tabs={[
          { value: "transcript", label: "Transcript", count: ts.items.filter((i) => i.k !== "turn").length },
          { value: "files", label: "Files" }, { value: "grading", label: "Grading" }, { value: "quality", label: "Code quality" },
          { value: "reviews", label: "Reviews", count: run.reviews?.length }, { value: "requests", label: "Requests" },
          { value: "gpu", label: "GPU" }, { value: "logs", label: "Logs" }, { value: "details", label: "Details" },
        ]} />
      </div>
      {tab === "transcript" && (
        <>
          <div className="sticky-bar row wrap">
            <Segmented value={filter} onChange={setFilter} options={[{ value: "all", label: "Everything" }, { value: "messages", label: "Messages" }, { value: "tools", label: "Tool calls" }]} />
            <span className="spacer" />
            {live && <Badge tone="info" dot live>live</Badge>}
            <Toggle checked={follow} onChange={setFollow} label="Follow" />
          </div>
          {sample ? <Notice>This run comes from the bundled sample: metrics and reviews are included, transcripts and files are not.</Notice> : <Transcript state={ts} ctx={ctx} follow={follow && live} filter={filter} />}
        </>
      )}
      {tab === "files" && (sample ? <Notice>Sample runs do not include workspaces.</Notice> : <Files id={id!} />)}
      {tab === "grading" && <Grading run={run} />}
      {tab === "quality" && <Quality q={run.quality} />}
      {tab === "reviews" && <Reviews reviews={run.reviews || []} />}
      {tab === "requests" && (sample ? <Notice>Sample runs do not include request logs.</Notice> : <Requests id={id!} ctx={ctx} />)}
      {tab === "gpu" && <Gpu id={id!} kind={prof?.kind || run.snapshot?.profile?.kind} />}
      {tab === "logs" && (sample ? <Notice>Sample runs do not include logs.</Notice> : <Logs id={id!} stages={bench?.n_stages || 1} local={(prof?.kind || run.snapshot?.profile?.kind) === "local"} />)}
      {tab === "details" && <Details run={run} />}
    </div>
  );
}

function Files({ id }: { id: string }) {
  const [root, setRoot] = useState<"workspace" | "home">("workspace");
  const [files, setFiles] = useState<any[] | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [content, setContent] = useState<string>("");
  useEffect(() => {
    setFiles(null);
    setSel(null);
    api.get(`/runs/${id}/files?root=${root}`).then(setFiles).catch(() => setFiles([]));
  }, [id, root]);
  useEffect(() => {
    if (sel) api.text(`/runs/${id}/file?root=${root}&path=${encodeURIComponent(sel)}`).then(setContent).catch((e) => setContent(String(e)));
  }, [sel, id, root]);
  return (
    <div className="col" style={{ gap: 12 }}>
      <Segmented value={root} onChange={setRoot} options={[{ value: "workspace", label: "Workspace" }, { value: "home", label: "Agent home (configs, sessions)" }]} />
      {!files ? <Skeleton h={300} /> : !files.length ? <Empty icon={<Folder size={20} />} title="No files" /> : (
        <div className="split">
          <div className="card file-tree" style={{ padding: 6, maxHeight: 640, overflowY: "auto" }}>
            {files.map((f) => (
              <div key={f.path} className={`f ${sel === f.path ? "on" : ""}`} onClick={() => setSel(f.path)} title={f.path}>
                <FileCode2 size={12} /><span className="ellipsis" style={{ flex: 1 }}>{f.path}</span><span className="tiny muted">{fmtBytes(f.size)}</span>
              </div>
            ))}
          </div>
          <div>{sel ? <><div className="row between mb-8"><b className="mono small">{sel}</b></div><Code code={content} path={sel} lineNumbers maxHeight={640} /></> : <Card><Empty title="Choose a file">Files the agent created or changed, as it left them.</Empty></Card>}</div>
        </div>
      )}
    </div>
  );
}

function Grading({ run }: { run: any }) {
  const m = run.metrics || {};
  const tests = Object.entries(m.tests || {});
  const checks = { ...(m.task_checks || {}), ...(m.common_checks || {}) };
  if (!run.metrics || !Object.keys(run.metrics).length) return <Notice>Grading results appear when the run finishes.</Notice>;
  return (
    <div className="grid grid-2" style={{ alignItems: "start" }}>
      <Card title="Hidden tests" sub={`${m.tests_passed ?? 0} of ${m.tests_total ?? 0} passed · correctness ${fmtPct(run.correctness)}`}>
        {m.grader_error && <Notice tone="danger" title="Grader error">{m.grader_error}</Notice>}
        <div style={{ maxHeight: 520, overflowY: "auto" }}>
          {tests.length ? tests.map(([t, ok]) => (
            <div key={t} className="row small" style={{ padding: "4px 0", borderBottom: "1px solid var(--border)" }}>
              {ok ? <CheckCircle2 size={14} className="ok" /> : <XCircle size={14} className="danger" />}<span className="mono">{t.split("::").pop()}</span><span className="tiny muted ellipsis">{t.split("::")[0]}</span>
            </div>
          )) : <p className="muted small">Per-test detail is not available for this run.</p>}
        </div>
      </Card>
      <div className="col" style={{ gap: 16 }}>
        <Card title="Instruction-following checks" sub={`score ${fmtPct(run.instruction_following)}`}>
          {Object.entries(checks).map(([k, v]) => (
            <div key={k} className="row small" style={{ padding: "4px 0" }}>{v ? <CheckCircle2 size={14} className="ok" /> : <XCircle size={14} className="danger" />}<span>{k.replace(/_/g, " ")}</span></div>
          ))}
        </Card>
        {m.stage_grades && (
          <Card title="Score after each stage">
            <Chart height={200} option={(c: any) => ({
              tooltip: { trigger: "axis", valueFormatter: (v: number) => `${Math.round(v * 100)}%` },
              xAxis: axis("category", { data: m.stage_grades.map((g: any) => `Stage ${g.stage}`) }),
              yAxis: axis("value", { max: 1, axisLabel: { color: c.text3, formatter: (v: number) => `${v * 100}%` } }),
              series: [{ type: "line", name: "Correctness", data: m.stage_grades.map((g: any) => g.correctness), symbolSize: 8, lineStyle: { width: 2.5 } },
                { type: "line", name: "Instruction following", data: m.stage_grades.map((g: any) => g.instruction_following), symbolSize: 6 }],
              legend: { bottom: 0 }, grid: { left: 8, right: 16, top: 16, bottom: 30, containLabel: true },
            })} />
          </Card>
        )}
        {m.install_attempts?.length > 0 && <Notice tone="warning" title="The agent tried to install packages (the sandbox is offline)">{m.install_attempts.slice(0, 3).map((x: string) => <div key={x} className="mono tiny">{x}</div>)}</Notice>}
        {m.final_text && <Card title="Agent's final message"><div className="small text-2" style={{ whiteSpace: "pre-wrap" }}>{m.final_text}</div></Card>}
      </div>
    </div>
  );
}

function Quality({ q }: { q: any }) {
  const s = q?.static;
  if (!s || !Object.keys(s).length) return <Notice>{q?.error ? `Quality analysis failed: ${q.error}` : "No code-quality analysis for this run (the plan had it off, or the quality image is missing)."}</Notice>;
  return (
    <div className="grid grid-2" style={{ alignItems: "start" }}>
      <Card title="Static analysis" sub="Only files the agent created or changed are measured; per-line metrics keep it size-neutral.">
        <KV items={[
          ["Lines of code", `${fmtNum(s.sloc_total)} (${fmtNum(s.sloc?.python)} Python, ${fmtNum(s.sloc?.python_tests)} tests, ${fmtNum(s.sloc?.typescript)} TS)`],
          ["Files", `${s.files_authored} (${s.files_new} new, ${s.files_modified} modified)`],
          ["Lint findings", `${s.ruff_findings} · ${s.ruff_per_100_sloc} per 100 lines`],
          ["Complexity", `avg ${s.cc_avg ?? "–"} · max ${s.cc_max} · ${fmtPct(s.cc_over_10_share)} of functions over 10`],
          ["Function size", `avg ${s.avg_func_len ?? "–"} lines · ${fmtPct(s.long_funcs_share)} over 50 lines`],
          ["Nesting depth", s.max_nesting], ["Maintainability index", s.mi_avg ?? "–"], ["Duplication", fmtPct(s.duplication)],
          ["Dead code findings", s.dead_code_findings], ["Type hints", fmtPct(s.type_hint_coverage)], ["Docstrings", fmtPct(s.docstring_coverage)],
          ["Own tests", `${s.own_test_functions} · ${s.own_tests_pass === null ? "–" : s.own_tests_pass ? "pass" : "fail"} · coverage ${fmtPct(s.own_test_coverage)}`],
          ["Security (bandit)", `${s.bandit?.HIGH || 0} high · ${s.bandit?.MEDIUM || 0} medium · ${s.bandit?.LOW || 0} low`],
        ]} />
      </Card>
      <div className="col" style={{ gap: 16 }}>
        {q.probes && (
          <Card title="Robustness probes" sub={`${q.probes.passed}/${q.probes.total} passed`}>
            {Object.entries(q.probes.tests || {}).map(([k, v]) => <div key={k} className="row small" style={{ padding: "3px 0" }}>{v ? <CheckCircle2 size={14} className="ok" /> : <XCircle size={14} className="danger" />}<span className="mono">{k}</span></div>)}
          </Card>
        )}
        {Object.keys(s.ruff_by_code || {}).length > 0 && (
          <Card title="Lint findings by rule"><div className="pill-list">{Object.entries(s.ruff_by_code).sort((a: any, b: any) => b[1] - a[1]).map(([k, v]: any) => <Badge key={k}>{k} × {v}</Badge>)}</div></Card>
        )}
        {s.bandit_issues?.length > 0 && <Card title="Security findings">{s.bandit_issues.slice(0, 10).map((b: any, i: number) => <div key={i} className="small" style={{ padding: "3px 0" }}><Badge tone={b.severity === "HIGH" ? "danger" : "warn"}>{b.severity}</Badge> {b.test_id} {b.filename}:{b.line} {b.text}</div>)}</Card>}
      </div>
    </div>
  );
}

function Reviews({ reviews }: { reviews: any[] }) {
  if (!reviews.length) return <Empty title="Not reviewed yet">Start blind judging from the Judging page.</Empty>;
  return (
    <div className="grid grid-2" style={{ alignItems: "start" }}>
      {reviews.map((r) => (
        <Card key={r.id} title={r.judge_name} sub={r.cost_usd ? `cost ${fmtUsd(r.cost_usd)}` : undefined} actions={<span className="score" style={{ fontSize: 22 }}>{r.overall ?? "–"}<span className="muted small">/10</span></span>}>
          <p className="small">{r.summary}</p>
          <div className="col mt-12" style={{ gap: 6 }}>
            {Object.entries(r.scores || {}).map(([k, v]: any) => (
              <div key={k} className="row small" style={{ gap: 10 }}><span style={{ width: 110 }} className="text-2">{k}</span>
                <div className="progress" style={{ flex: 1 }}><div style={{ width: `${(v || 0) * 10}%` }} /></div><span className="tnum" style={{ width: 22, textAlign: "right" }}>{v ?? "–"}</span></div>
            ))}
          </div>
          {r.issues?.length > 0 && <><div className="label mt-12 mb-8">Top issues</div><ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{r.issues.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul></>}
          {r.extras?.length > 0 && <><div className="label mt-12 mb-8">Beyond the spec</div><div className="pill-list">{r.extras.map((x: string, i: number) => <Badge key={i} tone="ok">{x}</Badge>)}</div></>}
        </Card>
      ))}
    </div>
  );
}

function Requests({ id, ctx }: { id: string; ctx?: number }) {
  const [rows, setRows] = useState<any[] | null>(null);
  useEffect(() => {
    api.get(`/runs/${id}/proxy`).then(setRows).catch(() => setRows([]));
  }, [id]);
  const data = useMemo(() => (rows || []).map((r) => {
    const u = r.usage_norm || {};
    const t = r.timings || {};
    const input = u.input ?? ((t.prompt_n || 0) + (t.cache_n || 0));
    const out = u.output ?? t.predicted_n;
    return { ...r, input, cached: u.cached ?? t.cache_n, out, tps: t.predicted_per_second || (out && r.wall_s ? out / Math.max(r.wall_s - (r.ttft_s || 0), 0.1) : null), ctxPct: ctx ? (input + (out || 0)) / ctx : null };
  }), [rows, ctx]);
  if (!rows) return <Skeleton h={300} />;
  if (!rows.length) return <Empty title="No model requests recorded" />;
  return (
    <div className="col" style={{ gap: 16 }}>
      <Card title="Context and speed per request">
        <Chart height={220} option={(c: any) => ({
          tooltip: { trigger: "axis" }, legend: { bottom: 0 }, grid: { left: 8, right: 16, top: 16, bottom: 30, containLabel: true },
          xAxis: axis("category", { data: data.map((r) => r.seq) }),
          yAxis: [axis("value", { axisLabel: { color: c.text3, formatter: (v: number) => fmtTokens(v) } }), axis("value", { splitLine: { show: false }, axisLabel: { color: c.text3, formatter: "{value} t/s" } })],
          series: [{ type: "bar", name: "Prompt tokens", data: data.map((r) => r.input), itemStyle: { borderRadius: 3 } },
            { type: "bar", name: "Cached", data: data.map((r) => r.cached), itemStyle: { borderRadius: 3 } },
            { type: "line", name: "Decode tok/s", yAxisIndex: 1, data: data.map((r) => r.tps && +r.tps.toFixed(1)), symbolSize: 5 }],
        })} />
      </Card>
      <Card pad={false}>
        <Table rowKey={(r: any) => String(r.seq)} rows={data} maxHeight={520} cols={[
          { key: "seq", label: "#", num: true, sort: (r) => r.seq, render: (r: any) => r.seq },
          { key: "in", label: "Prompt", num: true, sort: (r) => r.input, render: (r: any) => fmtTokens(r.input) },
          { key: "cached", label: "Cached", num: true, sort: (r) => r.cached, render: (r: any) => fmtTokens(r.cached) },
          { key: "out", label: "Output", num: true, sort: (r) => r.out, render: (r: any) => fmtTokens(r.out) },
          { key: "ctx", label: "Context", num: true, sort: (r) => r.ctxPct, render: (r: any) => fmtPct(r.ctxPct) },
          { key: "ttft", label: "TTFT", num: true, sort: (r) => r.ttft_s, render: (r: any) => r.ttft_s ? `${r.ttft_s.toFixed(2)}s` : "–" },
          { key: "tps", label: "tok/s", num: true, sort: (r) => r.tps, render: (r: any) => fmtNum(r.tps, 1) },
          { key: "wall", label: "Time", num: true, sort: (r) => r.wall_s, render: (r: any) => fmtDur(r.wall_s) },
          { key: "tools", label: "Tools", render: (r: any) => <span className="small mono">{(r.tool_names || []).join(", ")}</span> },
          { key: "fin", label: "Finish", render: (r: any) => r.budget_blocked ? <Badge tone="danger">budget</Badge> : r.status >= 400 ? <Badge tone="danger">{r.status}</Badge> : <span className="small muted">{r.finish_reason}</span> },
          { key: "cost", label: "Cost", num: true, sort: (r) => r.cost_usd, render: (r: any) => fmtUsd(r.cost_usd) },
        ]} />
      </Card>
    </div>
  );
}

function Gpu({ id, kind }: { id: string; kind?: string }) {
  const [rows, setRows] = useState<any[] | null>(null);
  useEffect(() => {
    api.get(`/runs/${id}/gpu`).then(setRows).catch(() => setRows([]));
  }, [id]);
  if (kind && kind !== "local") return <Notice>GPU telemetry is recorded for local profiles only.</Notice>;
  if (!rows) return <Skeleton h={260} />;
  if (!rows.length) return <Empty title="No GPU samples for this run" />;
  return (
    <Card title="GPU during the run" sub={`peak VRAM ${fmtMib(Math.max(...rows.map((r) => r.vram_mib)))} of ${fmtMib(rows[0].vram_total_mib, 0)}`}>
      <Chart height={300} option={(c: any) => ({
        tooltip: { trigger: "axis" }, legend: { bottom: 0 }, grid: { left: 8, right: 16, top: 16, bottom: 30, containLabel: true },
        xAxis: axis("category", { data: rows.map((r) => new Date(r.ts * 1000).toLocaleTimeString()) }),
        yAxis: [axis("value", { max: rows[0].vram_total_mib, axisLabel: { color: c.text3, formatter: (v: number) => `${(v / 1024).toFixed(0)} GB` } }), axis("value", { splitLine: { show: false }, axisLabel: { color: c.text3 } })],
        series: [{ type: "line", name: "VRAM", showSymbol: false, areaStyle: { opacity: 0.12 }, data: rows.map((r) => r.vram_mib) },
          { type: "line", name: "Shared (spill)", showSymbol: false, data: rows.map((r) => r.shared_mib), lineStyle: { type: "dashed" } },
          { type: "line", name: "Power W", yAxisIndex: 1, showSymbol: false, data: rows.map((r) => r.power_w) },
          { type: "line", name: "Util %", yAxisIndex: 1, showSymbol: false, data: rows.map((r) => r.util_pct) }],
      })} />
    </Card>
  );
}

function Logs({ id, stages, local }: { id: string; stages: number; local: boolean }) {
  const opts = [...Array.from({ length: stages }, (_, i) => [`stdout_stage${i + 1}.log`, `stderr_stage${i + 1}.log`]).flat(), ...(local ? ["server"] : [])];
  const [name, setName] = useState(opts[0]);
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    setText(null);
    api.text(`/runs/${id}/log?name=${name}`).then(setText).catch((e) => setText(String(e)));
  }, [id, name]);
  return (
    <div className="col" style={{ gap: 10 }}>
      <div className="row"><Select value={name} onChange={setName} options={opts.map((o) => ({ value: o, label: o === "server" ? "llama-server log" : o }))} aria-label="Log file" />
        <span className="small muted">Raw harness output; the Transcript tab shows the same session in a readable form.</span></div>
      {text === null ? <Skeleton h={300} /> : <div className="logbox" style={{ maxHeight: 620 }}>{text || "(empty)"}</div>}
    </div>
  );
}

function Details({ run }: { run: any }) {
  const s = run.snapshot || {};
  return (
    <div className="grid grid-2" style={{ alignItems: "start" }}>
      <Card title="Profile as run"><Code code={JSON.stringify(s.profile || {}, null, 2)} lang="json" maxHeight={460} /></Card>
      <div className="col" style={{ gap: 16 }}>
        <Card title="Run"><KV items={[["Run id", <span className="mono small">{run.id}</span>], ["Folder", <span className="mono small">{run.dir || "–"}</span>],
          ["Started", run.started_at ? new Date(run.started_at * 1000).toLocaleString() : "–"], ["Finished", run.ended_at ? new Date(run.ended_at * 1000).toLocaleString() : "–"],
          ["Wall time", fmtDur(run.wall_s)], ["Model time", fmtDur(run.metrics?.model_time_s)], ["Requests", run.metrics?.requests ?? "–"],
          ["Energy", run.metrics?.gpu_energy_wh ? `${run.metrics.gpu_energy_wh} Wh` : "–"], ["Exit codes", (run.metrics?.exit_codes || []).join(", ") || "–"],
          ["Instruction following", <ScoreCell v={run.instruction_following} />]]} /></Card>
        {s.harness && <Card title="Harness"><KV items={[["Name", `${s.harness.name} ${s.harness.version}`], ["Image", <span className="mono small">{s.harness.image}</span>], ["APIs", s.harness.apis.join(", ")]]} /></Card>}
        {s.model && <Card title="Model"><KV items={[["Name", s.model.name], ["Quant", s.model.quant], ["Repo", s.model.repo || "–"], ["Size", fmtBytes(s.model.size_bytes)]]} /></Card>}
      </div>
    </div>
  );
}

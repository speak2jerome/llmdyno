import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, ArrowRight, CheckCircle2, Copy, Download, FileCode2, FileUp, FlaskConical, Layers3, Pencil, Plus, Save, ShieldCheck, Trash2, XCircle,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, download } from "../api";
import { JobPanel } from "../components";
import { fmtBytes, fmtMin } from "../format";
import { keys, useBenchmarks, useJob, useSuites } from "../queries";
import {
  Badge, Button, Card, Checkbox, Chip, Drawer, Empty, Field, Input, KV, Markdown, Menu, Modal, Notice, NumInput, PageHead, Segmented,
  Select, Skeleton, Tabs, Textarea, useConfirm, useToast,
} from "../ui";

const DIFF_TONE: Record<string, string> = { easy: "ok", medium: "info", hard: "warn" };

export default function Benchmarks() {
  const [tab, setTab] = useState<"benchmarks" | "suites">("benchmarks");
  const benchmarks = useBenchmarks();
  const suites = useSuites();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const file = useRef<HTMLInputElement>(null);
  const [cat, setCat] = useState<string>("all");
  const [q, setQ] = useState("");
  const [detail, setDetail] = useState<string | null>(null);
  const [suiteEdit, setSuiteEdit] = useState<any>(null);
  const list = benchmarks.data || [];
  const cats = ["all", ...Array.from(new Set(list.map((b) => b.category)))];
  const shown = list.filter((b) => (cat === "all" || b.category === cat) && (!q || `${b.title} ${b.summary} ${(b.tags || []).join(" ")}`.toLowerCase().includes(q.toLowerCase())));
  const upload = async (f: File) => {
    try {
      const b = await api.upload("/upload/benchmark", f);
      qc.invalidateQueries({ queryKey: keys.benchmarks });
      toast.ok("Benchmark imported", b.title);
    } catch (e) {
      toast.err("Could not import", e);
    }
  };
  return (
    <div className="page">
      <PageHead title="Benchmarks" sub="Tasks with hidden graders: tests are copied in only after the agent finishes. Group them into suites for plans."
        actions={<>
          <input ref={file} type="file" accept=".zip" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ""; }} />
          <Button icon={<FileUp size={15} />} onClick={() => file.current?.click()}>Import zip</Button>
          <Button icon={<Layers3 size={15} />} onClick={() => { setTab("suites"); setSuiteEdit({}); }}>New suite</Button>
          <Button variant="primary" icon={<Plus size={15} />} onClick={() => nav("/benchmarks/new")}>Create benchmark</Button>
        </>} />
      <Tabs value={tab} onChange={setTab} tabs={[{ value: "benchmarks", label: "Benchmarks", count: list.length }, { value: "suites", label: "Suites", count: (suites.data || []).length }]} />
      {tab === "benchmarks" && (
        <>
          <div className="row wrap mb-16">
            {cats.map((c) => <Chip key={c} on={cat === c} onClick={() => setCat(c)}>{c === "all" ? "All" : c}</Chip>)}
            <span className="spacer" />
            <Input style={{ maxWidth: 260 }} placeholder="Search benchmarks" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search benchmarks" />
          </div>
          {benchmarks.isLoading ? <Skeleton h={200} /> : shown.length ? (
            <div className="grid grid-auto" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(330px, 1fr))" }}>
              {shown.map((b) => (
                <Card key={b.id} onClick={() => setDetail(b.id)}>
                  <div className="row between"><Badge tone="accent">{b.category}</Badge><Badge tone={DIFF_TONE[b.difficulty]}>{b.difficulty}</Badge></div>
                  <h3 className="mt-12">{b.title}</h3>
                  <p className="small text-2 mt-8">{b.summary}</p>
                  <div className="pill-list mt-12">
                    <Badge>{b.n_stages} stage{b.n_stages > 1 ? "s" : ""}</Badge>
                    <Badge title="Context needed in reference runs">~{Math.round((b.min_context || 0) / 1000)}k ctx</Badge>
                    <Badge title="Typical local run time">~{fmtMin(b.expected_minutes?.local)}</Badge>
                    {(b.languages || []).map((l: string) => <Badge key={l} tone="outline">{l}</Badge>)}
                    {!b.builtin && <Badge tone="info">custom</Badge>}
                  </div>
                </Card>
              ))}
            </div>
          ) : <Card><Empty icon={<FlaskConical size={22} />} title="No benchmarks match">Clear the filter or create your own.</Empty></Card>}
        </>
      )}
      {tab === "suites" && <Suites suites={suites.data || []} benchmarks={list} onEdit={setSuiteEdit} />}
      {detail && <BenchmarkDrawer id={detail} onClose={() => setDetail(null)} />}
      {suiteEdit && <SuiteModal suite={suiteEdit} benchmarks={list} onClose={() => setSuiteEdit(null)} />}
    </div>
  );
}

function Suites({ suites, benchmarks, onEdit }: { suites: any[]; benchmarks: any[]; onEdit: (s: any) => void }) {
  const qc = useQueryClient();
  const confirm = useConfirm();
  const toast = useToast();
  const byId = Object.fromEntries(benchmarks.map((b) => [b.id, b]));
  return (
    <div className="grid grid-2">
      {suites.map((s) => {
        const mins = s.benchmark_ids.reduce((a: number, id: string) => a + (byId[id]?.expected_minutes?.local || 0), 0);
        return (
          <Card key={s.id} title={<span className="row">{s.name}{s.builtin && <Badge>built-in</Badge>}</span>} sub={s.description}
            actions={!s.builtin && <>
              <Button size="sm" variant="ghost" icon={<Pencil size={13} />} onClick={() => onEdit(s)}>Edit</Button>
              <Button size="sm" variant="ghost" iconOnly icon={<Trash2 size={13} />} aria-label="Delete suite" onClick={async () => {
                if (!(await confirm({ title: `Delete suite ${s.name}?`, danger: true, confirm: "Delete" })).ok) return;
                api.del(`/suites/${s.id}`).then(() => qc.invalidateQueries({ queryKey: keys.suites })).catch((e) => toast.err("Could not delete", e));
              }} />
            </>}>
            <div className="pill-list">{s.benchmark_ids.map((id: string) => <Badge key={id} tone={byId[id] ? "" : "danger"}>{byId[id]?.title || `${id} (missing)`}</Badge>)}</div>
            <div className="tiny muted mt-12">{s.benchmark_ids.length} benchmarks · about {fmtMin(mins)} per local profile and harness</div>
          </Card>
        );
      })}
      <Card onClick={() => onEdit({})}>
        <Empty icon={<Plus size={20} />} title="New suite">Pick any mix of built-in and custom benchmarks.</Empty>
      </Card>
    </div>
  );
}

function SuiteModal({ suite, benchmarks, onClose }: { suite: any; benchmarks: any[]; onClose: () => void }) {
  const [name, setName] = useState(suite.name || "");
  const [desc, setDesc] = useState(suite.description || "");
  const [ids, setIds] = useState<string[]>(suite.benchmark_ids || []);
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  const toast = useToast();
  return (
    <Modal open onClose={onClose} title={suite.id ? `Edit ${suite.name}` : "New suite"} size="wide"
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} disabled={!name.trim() || !ids.length} onClick={async () => {
        setBusy(true);
        try {
          if (suite.id) await api.put(`/suites/${suite.id}`, { name, description: desc, benchmark_ids: ids });
          else await api.post("/suites", { name, description: desc, benchmark_ids: ids });
          qc.invalidateQueries({ queryKey: keys.suites });
          toast.ok(suite.id ? "Suite saved" : "Suite created");
          onClose();
        } catch (e) {
          toast.err("Could not save the suite", e);
        } finally {
          setBusy(false);
        }
      }}>{suite.id ? "Save" : "Create suite"}</Button></>}>
      <div className="form-grid">
        <Field label="Name"><Input value={name} onChange={(e) => setName(e.target.value)} autoFocus /></Field>
        <Field label="Description"><Input value={desc} onChange={(e) => setDesc(e.target.value)} /></Field>
        <Field label={`Benchmarks (${ids.length} selected)`} className="full">
          <div className="col" style={{ maxHeight: 340, overflowY: "auto" }}>
            {benchmarks.map((b) => (
              <Checkbox key={b.id} checked={ids.includes(b.id)} onChange={(v) => setIds((x) => v ? [...x, b.id] : x.filter((y) => y !== b.id))}>
                <b>{b.title}</b> <span className="muted small">· {b.category} · {b.n_stages} stage(s)</span>
              </Checkbox>
            ))}
          </div>
        </Field>
      </div>
    </Modal>
  );
}

function BenchmarkDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const [b, setB] = useState<any>(null);
  const [stage, setStage] = useState(0);
  const [tab, setTab] = useState<"task" | "files" | "grading">("task");
  const [vjob, setVjob] = useState<string | null>(null);
  const { job } = useJob(vjob);
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  useEffect(() => {
    api.get(`/benchmarks/${id}`).then(setB).catch((e) => toast.err("Could not load", e));
  }, [id, toast]);
  const validate = async () => {
    try {
      const r = await api.post(`/benchmarks/${id}/validate`);
      setVjob(r.job_id);
      setTab("grading");
    } catch (e) {
      toast.err("Could not start validation", e);
    }
  };
  const report = job?.status === "done" ? job.result : null;
  return (
    <Drawer open onClose={onClose} wide title={b?.title || "Benchmark"} sub={b ? `${b.category} · ${b.difficulty} · ${b.n_stages} stage(s) · ${b.builtin ? "built-in" : "custom"}${b.origin ? ` · ${b.origin}` : ""}` : ""}
      footer={b && <>
        <Menu align="left" trigger={(o) => <Button onClick={o}>More</Button>} items={[
          { label: "Export as zip", icon: <Download size={14} />, onClick: () => download(`/benchmarks/${id}/export`) },
          { label: "Duplicate to edit", icon: <Copy size={14} />, onClick: async () => {
            const r = await confirm({ title: "Duplicate benchmark", input: { label: "New id", initial: `${id}_copy`, placeholder: "my_benchmark" }, confirm: "Duplicate" });
            if (!r.ok) return;
            try {
              const nb = await api.post(`/benchmarks/${id}/duplicate`, { new_id: r.value });
              qc.invalidateQueries({ queryKey: keys.benchmarks });
              toast.ok("Duplicated", nb.title);
              if (nb.grader?.type === "spec") nav(`/benchmarks/${nb.id}/edit`);
              else onClose();
            } catch (e) {
              toast.err("Could not duplicate", e);
            }
          } },
          ...(!b.builtin ? ["sep" as const, { label: "Delete", icon: <Trash2 size={14} />, danger: true, onClick: async () => {
            if (!(await confirm({ title: `Delete ${b.title}?`, danger: true, confirm: "Delete", body: "Results of past runs are kept." })).ok) return;
            api.del(`/benchmarks/${id}`).then(() => { qc.invalidateQueries({ queryKey: keys.benchmarks }); onClose(); }).catch((e) => toast.err("Could not delete", e));
          } }] : []),
        ]} />
        {!b.builtin && b.grader?.type === "spec" && <Button icon={<Pencil size={14} />} onClick={() => nav(`/benchmarks/${id}/edit`)}>Edit</Button>}
        <Button variant="primary" icon={<ShieldCheck size={14} />} onClick={validate}>Validate grader</Button>
      </>}>
      {!b ? <Skeleton h={300} /> : (
        <>
          <p className="text-2 mb-16">{b.description}</p>
          <Tabs value={tab} onChange={setTab} tabs={[{ value: "task", label: "Task" }, { value: "files", label: "Files", count: b.workspace_files.length + b.stage_files.length }, { value: "grading", label: "Grading" }]} />
          {tab === "task" && (
            <div className="col" style={{ gap: 12 }}>
              {b.prompts.length > 1 && <Segmented value={String(stage)} onChange={(v) => setStage(+v)} options={b.prompts.map((_: any, i: number) => ({ value: String(i), label: `Stage ${i + 1}` }))} />}
              <Card><Markdown text={b.prompts[stage] || ""} /></Card>
              <KV items={[["Timeout", `${Math.round(b.stages[stage].timeout_s / 60)} min for this stage`], ["Context needed", `~${Math.round(b.min_context / 1000)}k tokens in reference runs`],
                ["Typical time", `${fmtMin(b.expected_minutes?.local)} local · ${fmtMin(b.expected_minutes?.cloud)} cloud`],
                ["Typical tokens", b.reference_tokens ? `${Math.round(b.reference_tokens.prompt / 1000)}k prompt · ${Math.round(b.reference_tokens.output / 1000)}k output` : "–"]]} />
            </div>
          )}
          {tab === "files" && (
            <div className="col" style={{ gap: 14 }}>
              <FileList title="Starting workspace" files={b.workspace_files} empty="Empty folder: the agent builds from scratch." />
              {b.stage_files.length > 0 && <FileList title="Files added at later stages" files={b.stage_files} />}
              <FileList title="Reference solution (used only for validation)" files={b.reference_files} empty="No reference solution." />
            </div>
          )}
          {tab === "grading" && (
            <div className="col" style={{ gap: 14 }}>
              <KV items={[["Grader", b.grader.type === "spec" ? "hidden pytest files + checks" : `script ${b.grader.path}`], ["Grader timeout", `${Math.round(b.grader.timeout_s / 60)} min`],
                ["Graded", b.grade_each_stage ? "after every stage" : "after the last stage"], ["Robustness probes", b.has_probes ? "yes (used in code quality)" : "no"]]} />
              <FileList title="Hidden grader files" files={b.grader_files} />
              {vjob && <JobPanel jobId={vjob} compact title="Validating the grader" />}
              {report && <ValidationReport r={report} />}
              {!vjob && <Notice>Validation grades the untouched starting workspace (it should fail) and the reference solution (it should pass).</Notice>}
            </div>
          )}
        </>
      )}
    </Drawer>
  );
}

function ValidationReport({ r }: { r: any }) {
  const row = (label: string, g: any, want: string) => g && (
    <div className="row between small" style={{ padding: "6px 0", borderBottom: "1px solid var(--border)" }}>
      <span>{label} <span className="muted">({want})</span></span>
      <span className="tnum">{g.grader_error ? <Badge tone="danger">grader error</Badge> : <>{g.tests_passed}/{g.tests_total} tests · {g.checks_passed ?? 0}/{g.checks_total ?? 0} checks</>}</span>
    </div>
  );
  return (
    <Card title={<span className="row">{r.ok ? <CheckCircle2 size={16} className="ok" /> : <XCircle size={16} className="danger" />} {r.ok ? "Grader looks correct" : "Grader needs attention"}</span>}>
      {row("Starting workspace", r.starter, "should fail")}
      {row("Reference solution", r.reference, "should pass")}
      {r.note && <p className="tiny muted mt-8">{r.note}</p>}
      {r.problems?.map((p: string, i: number) => <Notice key={i} tone="danger">{p}</Notice>)}
    </Card>
  );
}

function FileList({ title, files, empty }: { title: string; files: any[]; empty?: string }) {
  return (
    <div>
      <div className="label mb-8">{title}</div>
      {files.length ? (
        <div className="card" style={{ maxHeight: 220, overflowY: "auto", padding: 6 }}>
          {files.map((f) => <div key={f.path} className="row between mono small" style={{ padding: "3px 8px" }}><span className="row" style={{ gap: 6 }}><FileCode2 size={12} className="muted" />{f.path}</span><span className="muted">{fmtBytes(f.size)}</span></div>)}
        </div>
      ) : <p className="muted small">{empty || "None"}</p>}
    </div>
  );
}

/* ================================================================== editor */
const STEPS = ["Basics", "Stages", "Starting files", "Grading", "Reference", "Review"];
const CHECK_TYPES = [
  { value: "file_exists", label: "File exists" }, { value: "file_contains", label: "File contains text" }, { value: "glob", label: "Files match a pattern" },
  { value: "command", label: "Command exits with code" }, { value: "test_count", label: "Agent wrote at least N tests" },
];

export function BenchmarkEditor() {
  const { id } = useParams();
  const editing = !!id;
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [vjob, setVjob] = useState<string | null>(null);
  const { job } = useJob(vjob);
  const [s, setS] = useState<any>({
    id: "", title: "", summary: "", description: "", category: "Custom", difficulty: "medium", languages: ["Python"], tags: [],
    stages: [{ prompt: "You are working in /workspace.\n\n", timeout_s: 1200 }], workspace_files: {}, hidden_tests: { "test_hidden.py": "def test_example():\n    assert True\n" },
    checks: [{ name: "readme_present", type: "file_exists", path: "README.md" }], reference_files: {}, min_context: 32000,
    expected_minutes: { local: 5, cloud: 3 }, grade_each_stage: false,
  });
  useEffect(() => {
    if (!id) return;
    api.get(`/benchmarks/${id}/spec`).then(setS).catch((e) => toast.err("Could not load", e));
  }, [id, toast]);
  const set = (p: any) => setS((x: any) => ({ ...x, ...p }));
  const errors = useMemo(() => {
    const e: string[] = [];
    if (!/^[a-z0-9][a-z0-9_]{2,60}$/.test(s.id)) e.push("Id: 3-61 lowercase letters, digits or underscores");
    if (!s.title.trim()) e.push("Title is required");
    if (!s.stages.length || s.stages.some((x: any) => !x.prompt.trim())) e.push("Every stage needs a prompt");
    if (!Object.keys(s.hidden_tests).length && !s.checks.length) e.push("Add hidden tests or checks");
    return e;
  }, [s]);
  const save = async () => {
    setBusy(true);
    try {
      const b = editing ? await api.put(`/benchmarks/${id}`, s) : await api.post("/benchmarks", s);
      qc.invalidateQueries({ queryKey: keys.benchmarks });
      toast.ok(editing ? "Benchmark saved" : "Benchmark created", b.title);
      if (!editing) nav(`/benchmarks/${b.id}/edit`, { replace: true });
      return b;
    } catch (e) {
      toast.err("Could not save", e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="page">
      <div className="row mb-12"><Link to="/benchmarks" className="row small"><ArrowLeft size={14} /> Benchmarks</Link></div>
      <PageHead title={editing ? `Edit ${s.title || id}` : "Create a benchmark"} sub="Agents see the prompts and starting files. Hidden tests and checks are copied in only after the agent finishes."
        actions={<Button variant="primary" icon={<Save size={14} />} loading={busy} disabled={errors.length > 0} onClick={save}>{editing ? "Save" : "Create"}</Button>} />
      <div className="stepper">
        {STEPS.map((x, i) => <button key={x} className={`step ${i === step ? "on" : i < step ? "done" : ""}`} onClick={() => setStep(i)}><span className="n">{i + 1}</span>{x}</button>)}
      </div>
      {step === 0 && (
        <Card>
          <div className="form-grid">
            <Field label="Id" hint="Used in folders and exports; cannot change later" error={s.id && !/^[a-z0-9][a-z0-9_]{2,60}$/.test(s.id) ? "lowercase letters, digits, underscores" : null}>
              <Input value={s.id} onChange={(e) => set({ id: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_") })} disabled={editing} placeholder="csv_report_cli" />
            </Field>
            <Field label="Title"><Input value={s.title} onChange={(e) => set({ title: e.target.value })} placeholder="CSV report CLI" /></Field>
            <Field label="One-line summary" className="full"><Input value={s.summary} onChange={(e) => set({ summary: e.target.value })} /></Field>
            <Field label="Description" className="full"><Textarea rows={3} value={s.description} onChange={(e) => set({ description: e.target.value })} /></Field>
            <Field label="Category"><Input value={s.category} onChange={(e) => set({ category: e.target.value })} /></Field>
            <Field label="Difficulty"><Segmented value={s.difficulty} onChange={(v) => set({ difficulty: v })} options={[{ value: "easy", label: "Easy" }, { value: "medium", label: "Medium" }, { value: "hard", label: "Hard" }]} /></Field>
            <Field label="Languages (comma separated)"><Input value={(s.languages || []).join(", ")} onChange={(e) => set({ languages: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} /></Field>
            <Field label="Tags (comma separated)"><Input value={(s.tags || []).join(", ")} onChange={(e) => set({ tags: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} /></Field>
            <Field label="Context the task needs" tip="Profiles with a smaller context get a warning in the profile editor and plan preflight."><NumInput value={s.min_context} onChange={(v) => set({ min_context: Math.round(v || 32000) })} min={4000} max={1000000} suffix="tokens" /></Field>
            <Field label="Typical minutes (local / cloud)">
              <div className="row"><NumInput value={s.expected_minutes?.local} onChange={(v) => set({ expected_minutes: { ...s.expected_minutes, local: v || 5 } })} min={0.5} max={600} suffix="local" />
                <NumInput value={s.expected_minutes?.cloud} onChange={(v) => set({ expected_minutes: { ...s.expected_minutes, cloud: v || 3 } })} min={0.5} max={600} suffix="cloud" /></div>
            </Field>
          </div>
        </Card>
      )}
      {step === 1 && (
        <div className="col" style={{ gap: 12 }}>
          {s.stages.map((st: any, i: number) => (
            <Card key={i} title={`Stage ${i + 1}`} actions={<>
              <Field label=""><NumInput value={Math.round(st.timeout_s / 60)} onChange={(v) => set({ stages: s.stages.map((x: any, j: number) => j === i ? { ...x, timeout_s: Math.round((v || 20) * 60) } : x) })} min={1} max={240} suffix="min timeout" /></Field>
              {s.stages.length > 1 && <Button size="sm" variant="ghost" iconOnly icon={<Trash2 size={13} />} aria-label="Remove stage" onClick={() => set({ stages: s.stages.filter((_: any, j: number) => j !== i) })} />}
            </>}>
              <Textarea rows={10} value={st.prompt} onChange={(e) => set({ stages: s.stages.map((x: any, j: number) => j === i ? { ...x, prompt: e.target.value } : x) })} placeholder="Markdown prompt the agent receives" />
            </Card>
          ))}
          <div className="row">
            <Button icon={<Plus size={14} />} onClick={() => set({ stages: [...s.stages, { prompt: "", timeout_s: 1200 }] })}>Add stage</Button>
            {s.stages.length > 1 && <Checkbox checked={s.grade_each_stage} onChange={(v) => set({ grade_each_stage: v })}>Grade after every stage (the grader receives STAGE=n)</Checkbox>}
          </div>
          <Notice>Later stages continue the same session for harnesses that support it; others start fresh with the same workspace.</Notice>
        </div>
      )}
      {step === 2 && <FilesEditor title="Starting workspace" hint="Files the agent finds in /workspace. Leave empty to start from an empty folder." files={s.workspace_files} onChange={(f) => set({ workspace_files: f })} />}
      {step === 3 && (
        <div className="col" style={{ gap: 16 }}>
          <FilesEditor title="Hidden tests (pytest)" hint="Run in /work after the agent finishes; correctness = pass rate. Import the agent's modules directly (the workspace is on PYTHONPATH)." files={s.hidden_tests} onChange={(f) => set({ hidden_tests: f })} defaultName="test_hidden.py" />
          <Card title="Instruction-following checks" sub="Each passing check adds to the instruction-following score."
            actions={<Button size="sm" icon={<Plus size={13} />} onClick={() => set({ checks: [...s.checks, { name: `check_${s.checks.length + 1}`, type: "file_exists", path: "" }] })}>Add check</Button>}>
            <div className="col">
              {s.checks.map((c: any, i: number) => {
                const upd = (p: any) => set({ checks: s.checks.map((x: any, j: number) => j === i ? { ...x, ...p } : x) });
                return (
                  <div key={i} className="row wrap" style={{ alignItems: "flex-end", gap: 8 }}>
                    <Field label="Name"><Input value={c.name} onChange={(e) => upd({ name: e.target.value })} style={{ width: 170 }} /></Field>
                    <Field label="Type"><Select value={c.type} onChange={(v) => upd({ type: v })} options={CHECK_TYPES} aria-label="Check type" /></Field>
                    {["file_exists", "file_contains", "test_count"].includes(c.type) && <Field label="Path"><Input value={c.path || ""} onChange={(e) => upd({ path: e.target.value })} placeholder={c.type === "test_count" ? "tests" : "README.md"} style={{ width: 180 }} /></Field>}
                    {c.type === "file_contains" && <Field label="Text"><Input value={c.text || ""} onChange={(e) => upd({ text: e.target.value })} style={{ width: 200 }} /></Field>}
                    {c.type === "glob" && <><Field label="Pattern"><Input value={c.pattern || ""} onChange={(e) => upd({ pattern: e.target.value })} placeholder="templates/*.html" /></Field><Field label="At least"><NumInput value={c.min ?? 1} onChange={(v) => upd({ min: v || 1 })} min={1} max={1000} /></Field></>}
                    {c.type === "command" && <><Field label="Command"><Input className="mono" value={c.cmd || ""} onChange={(e) => upd({ cmd: e.target.value })} placeholder="python -m pytest -q tests" style={{ width: 260 }} /></Field><Field label="Exit code"><NumInput value={c.expect_exit ?? 0} onChange={(v) => upd({ expect_exit: v ?? 0 })} min={0} max={255} /></Field></>}
                    {c.type === "test_count" && <Field label="At least"><NumInput value={c.min ?? 3} onChange={(v) => upd({ min: v || 1 })} min={1} max={1000} /></Field>}
                    <Button variant="ghost" iconOnly icon={<Trash2 size={14} />} aria-label="Remove check" onClick={() => set({ checks: s.checks.filter((_: any, j: number) => j !== i) })} />
                  </div>
                );
              })}
              {!s.checks.length && <p className="muted small">No checks.</p>}
            </div>
          </Card>
        </div>
      )}
      {step === 4 && <FilesEditor title="Reference solution (optional)" hint="Overlaid on the starting workspace during validation; it should pass every hidden test. Never shown to agents." files={s.reference_files} onChange={(f) => set({ reference_files: f })} />}
      {step === 5 && (
        <div className="col" style={{ gap: 14 }}>
          {errors.length ? <Notice tone="danger" title="Fix these first">{errors.join(" · ")}</Notice> : <Notice tone="ok">Ready to save. After saving, validate the grader to make sure the tests fail on the starting files and pass on your reference.</Notice>}
          <Card><KV items={[["Id", s.id || "–"], ["Title", s.title || "–"], ["Stages", s.stages.length], ["Starting files", Object.keys(s.workspace_files).length], ["Hidden test files", Object.keys(s.hidden_tests).length], ["Checks", s.checks.length], ["Reference files", Object.keys(s.reference_files).length]]} /></Card>
          <div className="row">
            <Button variant="primary" icon={<Save size={14} />} loading={busy} disabled={errors.length > 0} onClick={save}>{editing ? "Save" : "Create"}</Button>
            <Button icon={<ShieldCheck size={14} />} disabled={errors.length > 0 || busy} onClick={async () => {
              const b = await save();
              if (!b) return;
              const r = await api.post(`/benchmarks/${b.id}/validate`);
              setVjob(r.job_id);
            }}>Save & validate</Button>
          </div>
          {vjob && <JobPanel jobId={vjob} compact title="Validating the grader" />}
          {job?.status === "done" && <ValidationReport r={job.result} />}
        </div>
      )}
      <div className="row mt-16">
        <Button icon={<ArrowLeft size={14} />} disabled={step === 0} onClick={() => setStep(step - 1)}>Back</Button>
        {step < STEPS.length - 1 && <Button variant="primary" icon={<ArrowRight size={14} />} onClick={() => setStep(step + 1)}>Next</Button>}
      </div>
    </div>
  );
}

function FilesEditor({ title, hint, files, onChange, defaultName = "README.md" }: { title: string; hint: string; files: Record<string, string>; onChange: (f: Record<string, string>) => void; defaultName?: string }) {
  const names = Object.keys(files);
  const [sel, setSel] = useState<string | null>(names[0] || null);
  const up = useRef<HTMLInputElement>(null);
  const toast = useToast();
  const confirm = useConfirm();
  useEffect(() => {
    if (sel && !(sel in files)) setSel(Object.keys(files)[0] || null);
  }, [files, sel]);
  const add = (name: string, content = "") => {
    if (!name.trim() || name.startsWith("/") || name.includes("..")) return toast.err("Use a relative path inside the folder");
    onChange({ ...files, [name.trim()]: content });
    setSel(name.trim());
  };
  return (
    <Card title={title} sub={hint} actions={<>
      <input ref={up} type="file" multiple hidden onChange={async (e) => {
        const fl = Array.from(e.target.files || []);
        const next = { ...files };
        for (const f of fl) {
          if (f.size > 1_000_000) { toast.warn(`${f.name} skipped`, "Files over 1 MB are not supported in the editor"); continue; }
          next[f.name] = await f.text();
        }
        onChange(next);
        if (fl[0]) setSel(fl[0].name);
        e.target.value = "";
      }} />
      <Button size="sm" icon={<FileUp size={13} />} onClick={() => up.current?.click()}>Upload</Button>
      <Button size="sm" icon={<Plus size={13} />} onClick={async () => {
        const r = await confirm({ title: "New file", input: { label: "Path inside the folder", placeholder: "src/app.py", initial: names.includes(defaultName) ? "" : defaultName }, confirm: "Add file" });
        if (r.ok && r.value) add(r.value);
      }}>New file</Button>
    </>}>
      {names.length ? (
        <div className="split" style={{ gridTemplateColumns: "240px 1fr", minHeight: 280 }}>
          <div className="file-tree card" style={{ padding: 6, overflowY: "auto", maxHeight: 420 }}>
            {names.sort().map((n) => (
              <div key={n} className={`f ${sel === n ? "on" : ""}`} onClick={() => setSel(n)}>
                <FileCode2 size={12} /><span className="ellipsis" style={{ flex: 1 }}>{n}</span>
                <button className="btn ghost xs icon" aria-label={`Remove ${n}`} onClick={(e) => { e.stopPropagation(); const { [n]: _, ...rest } = files; onChange(rest); }}><Trash2 size={11} /></button>
              </div>
            ))}
          </div>
          {sel && <Textarea code value={files[sel] ?? ""} onChange={(e) => onChange({ ...files, [sel]: e.target.value })} style={{ minHeight: 360 }} aria-label={`Contents of ${sel}`} />}
        </div>
      ) : <Empty title="No files" action={<Button size="sm" icon={<Plus size={13} />} onClick={() => add(defaultName)}>Add {defaultName}</Button>} />}
    </Card>
  );
}

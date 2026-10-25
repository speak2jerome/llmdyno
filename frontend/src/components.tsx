// Domain components shared across pages: jobs, dependency rows, system cards, memory fit, warnings.
import { Logo } from "./logos";
import {
  AlertTriangle, CheckCircle2, CircleDashed, Cpu, ExternalLink, FolderOpen, HardDrive, ListChecks, MemoryStick,
  MonitorCog, Play, Square, X, XCircle,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "./api";
import { Chart, axis } from "./charts";
import { cls, fmtAgo, fmtBytes, fmtCtx, fmtMib, fmtNum } from "./format";
import { Job, useJob, useJobs } from "./queries";
import { Badge, Button, CopyButton, Input, Modal, Notice, Progress, Select, StatusBadge, Tip, useToast } from "./ui";

/* ------------------------------------------------------------------ jobs */
export function JobsPopover() {
  const jobs = useJobs();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const active = jobs.filter((j) => ["queued", "running"].includes(j.status));
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button className="btn ghost sm" onClick={() => setOpen((o) => !o)} aria-label="Background jobs" title="Background jobs">
        <ListChecks size={14} /> {active.length ? <span className="badge info" style={{ height: 18 }}>{active.length}</span> : "Jobs"}
      </button>
      {open && (
        <div className="menu" style={{ bottom: "calc(100% + 6px)", left: 0, width: 340, padding: 8 }}>
          <div className="row between" style={{ padding: "4px 6px 8px" }}>
            <b>Background jobs</b>
            <Link to="/jobs" onClick={() => setOpen(false)} className="small">See all</Link>
          </div>
          {jobs.slice(0, 7).map((j) => <JobLine key={j.id} job={j} />)}
          {!jobs.length && <div className="muted small" style={{ padding: 8 }}>Nothing yet. Downloads, image builds, runs and judging show up here.</div>}
        </div>
      )}
    </div>
  );
}

export function JobLine({ job }: { job: Job }) {
  const live = ["queued", "running"].includes(job.status);
  return (
    <div style={{ padding: "7px 6px", borderRadius: 8 }} className="hover-row">
      <div className="row" style={{ gap: 6 }}>
        <span className="ellipsis small" style={{ fontWeight: 560, flex: 1 }} title={job.title}>{job.title}</span>
        <StatusBadge status={job.status} />
      </div>
      {live && <Progress value={job.progress} indeterminate={!job.progress} style={{ marginTop: 6 }} />}
      <div className="tiny muted ellipsis mt-8" style={{ marginTop: 4 }}>{job.detail || fmtAgo(job.created_at)}</div>
    </div>
  );
}

export function JobPanel({ jobId, onClose, title, compact }: { jobId?: string | null; onClose?: () => void; title?: string; compact?: boolean }) {
  const { job, log } = useJob(jobId);
  const box = useRef<HTMLDivElement>(null);
  const toast = useToast();
  const [follow, setFollow] = useState(true);
  useEffect(() => {
    if (follow && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [log, follow]);
  if (!jobId) return null;
  const live = job && ["queued", "running"].includes(job.status);
  return (
    <div className="card" style={{ overflow: "hidden" }}>
      <div className="card-head">
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="row" style={{ gap: 8 }}>
            <h3 className="ellipsis">{title || job?.title || "Job"}</h3>
            {job && <StatusBadge status={job.status} />}
          </div>
          <div className="sub ellipsis">{job?.detail || (live ? "working…" : "")}</div>
        </div>
        <div className="actions">
          {live && <Button size="sm" variant="danger" icon={<Square size={12} />} onClick={() => api.post(`/jobs/${jobId}/cancel`).catch((e) => toast.err("Could not cancel", e))}>Cancel</Button>}
          {onClose && <Button size="sm" variant="ghost" iconOnly icon={<X size={15} />} onClick={onClose} aria-label="Close" />}
        </div>
      </div>
      {live && <Progress value={job?.progress} indeterminate={!job?.progress} style={{ borderRadius: 0, height: 3 }} />}
      {!compact && (
        <div ref={box} className="logbox" style={{ border: 0, borderRadius: 0, maxHeight: 260 }}
          onScroll={(e) => { const el = e.currentTarget; setFollow(el.scrollHeight - el.scrollTop - el.clientHeight < 30); }}>
          {log.length ? log.join("\n") : <span className="muted">Waiting for output…</span>}
        </div>
      )}
      {job?.status === "failed" && <div style={{ padding: "10px 14px" }}><Notice tone="danger" title="Failed">{job.detail}</Notice></div>}
    </div>
  );
}

/* ------------------------------------------------------------------ dependencies */
export function DepRow({ dep, onJob, onChanged }: { dep: any; onJob: (id: string) => void; onChanged: () => void }) {
  const toast = useToast();
  const nav = useNavigate();
  const [busy, setBusy] = useState<string | null>(null);
  const [variant, setVariant] = useState<string>(dep.actions.find((a: any) => a.variants)?.variants?.[0]?.id || "");
  const [pathOpen, setPathOpen] = useState(false);
  const [path, setPath] = useState("");
  const savePath = async () => {
    setBusy("path");
    try {
      await api.post(`/system/deps/${dep.id}/action`, { action: "use_existing_llama", path: path.trim() });
      toast.ok("llama.cpp folder saved");
      setPathOpen(false);
      onChanged();
    } catch (e) {
      toast.err("That folder does not work", e);
    } finally {
      setBusy(null);
    }
  };
  const level = dep.level === "required" || dep.level.startsWith("required") ? "required" : dep.level;
  const icoCls = dep.ok ? "ok" : level === "required" ? "missing" : level === "recommended" ? "rec" : "opt";
  const act = async (a: any) => {
    if (a.kind === "link") return window.open(a.url, "_blank", "noopener");
    if (a.kind === "nav") return nav(a.to);
    if (a.kind === "copy") {
      navigator.clipboard?.writeText(a.text);
      return toast.ok("Command copied", a.text);
    }
    if (a.kind === "path") {
      setPath(dep.ok ? (dep.detail.match(/ at (.+)$/)?.[1] || "") : "");
      return setPathOpen(true);
    }
    setBusy(a.id);
    try {
      const r = await api.post(`/system/deps/${dep.id}/action`, { action: a.id, variant: variant || undefined });
      if (r.job_id) onJob(r.job_id);
      if (r.message) toast.info(r.message);
      onChanged();
    } catch (e) {
      toast.err(`${a.label} failed`, e);
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="check-row">
      <div className={cls("ico", icoCls)}>
        {dep.ok ? <CheckCircle2 size={16} /> : level === "required" ? <XCircle size={16} /> : <CircleDashed size={16} />}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="row wrap" style={{ gap: 8 }}>
          <b>{dep.name}</b>
          <Badge tone={level === "required" ? (dep.ok ? "ok" : "danger") : level === "recommended" ? (dep.ok ? "ok" : "warn") : ""}>{dep.level}</Badge>
        </div>
        <div className="text-2 small mt-8" style={{ marginTop: 3 }}>{dep.detail}</div>
        {dep.why && <div className="muted tiny" style={{ marginTop: 2 }}>{dep.why}</div>}
        {!dep.ok && dep.actions.some((a: any) => a.note) && (
          <div className="tiny warn" style={{ marginTop: 4 }}>{dep.actions.find((a: any) => a.note)?.note}</div>
        )}
      </div>
      <div className="row wrap" style={{ justifyContent: "flex-end", maxWidth: 420 }}>
        {dep.actions.filter((a: any) => !(dep.ok && a.kind === "job" && !a.id.startsWith("install_llama"))).map((a: any) => (
          <span key={a.id} className="row" style={{ gap: 6 }}>
            {a.variants && (
              <Select aria-label="llama.cpp build" value={variant} onChange={(v) => setVariant(v)}
                options={a.variants.map((v: any) => ({ value: v.id, label: `${v.label}${v.ok ? "" : " (not recommended)"}` }))} />
            )}
            <Button size="sm" variant={!dep.ok && a.kind === "job" ? "primary" : "default"} loading={busy === a.id}
              icon={a.kind === "link" ? <ExternalLink size={13} /> : a.kind === "path" ? <FolderOpen size={13} /> : a.kind === "job" ? <Play size={13} /> : undefined}
              onClick={() => act(a)}>
              {dep.ok && a.id === "install_llama" ? "Reinstall / update" : a.label}
            </Button>
          </span>
        ))}
      </div>
      <Modal open={pathOpen} onClose={() => setPathOpen(false)} title="Use an existing llama.cpp folder"
        sub="Point to the folder that contains llama-server (and llama-fit-params) from a llama.cpp release."
        footer={<><Button onClick={() => setPathOpen(false)}>Cancel</Button>
          <Button variant="primary" disabled={!path.trim()} loading={busy === "path"} onClick={savePath}>Use this folder</Button></>}>
        <Input autoFocus placeholder="C:\llama.cpp\b11871" value={path} onChange={(e) => setPath(e.target.value)} onFocus={(e) => e.target.select()}
          onKeyDown={(e) => e.key === "Enter" && path.trim() && savePath()} />
      </Modal>
    </div>
  );
}

/* ------------------------------------------------------------------ system */
export function SystemCards({ specs }: { specs: any }) {
  if (!specs) return null;
  const g = specs.summary?.primary_gpu;
  const others = specs.gpus.filter((x: any) => x !== g && !(g && x.uuid && x.uuid === g.uuid));
  return (
    <div className="grid grid-4">
      <div className="card kpi">
        <div className="k row muted small"><Cpu size={14} /> CPU</div>
        <div style={{ fontWeight: 620, marginTop: 6 }} className="ellipsis" title={specs.cpu.name}>{specs.cpu.name}</div>
        <div className="small text-2">{specs.cpu.cores} cores · {specs.cpu.threads} threads{specs.cpu.max_mhz ? ` · ${(specs.cpu.max_mhz / 1000).toFixed(1)} GHz` : ""}</div>
        <div className="row mt-8" style={{ gap: 6 }}>
          <Badge tone={specs.cpu.avx2 ? "ok" : "warn"}>AVX2 {specs.cpu.avx2 ? "yes" : "no"}</Badge>
          <Badge tone={specs.cpu.avx512 ? "ok" : ""}>AVX-512 {specs.cpu.avx512 ? "yes" : "no"}</Badge>
        </div>
      </div>
      <div className="card kpi">
        <div className="k row muted small"><MonitorCog size={14} /> GPU</div>
        {g ? <>
          <div style={{ fontWeight: 620, marginTop: 6 }} className="ellipsis" title={g.name}>{g.name}</div>
          <div className="small text-2">{fmtMib(g.vram_total_mib, 0)} VRAM · {g.vendor}{g.driver ? ` · driver ${g.driver}` : ""}</div>
          <div className="row mt-8 wrap" style={{ gap: 6 }}>
            {g.vram_free_mib !== null && g.vram_free_mib !== undefined && <Badge tone={g.vram_free_mib / g.vram_total_mib < 0.6 ? "warn" : "ok"}>{fmtMib(g.vram_free_mib)} free now</Badge>}
            {g.compute_cap && <Badge>CC {g.compute_cap}</Badge>}
            {g.pcie && <Badge>{g.pcie}</Badge>}
          </div>
        </> : <div className="text-2 mt-8">No discrete GPU detected</div>}
        {others.length > 0 && <div className="tiny muted mt-8">Also: {others.map((o: any) => o.name).join(", ")}</div>}
      </div>
      <div className="card kpi">
        <div className="k row muted small"><MemoryStick size={14} /> Memory</div>
        <div className="stat"><span className="v" style={{ fontSize: 20 }}>{fmtBytes(specs.memory.total_bytes, 0)}</span></div>
        <div className="small text-2">{fmtBytes(specs.memory.available_bytes)} available</div>
        <Progress value={1 - specs.memory.available_bytes / specs.memory.total_bytes} style={{ marginTop: 10 }} />
      </div>
      <div className="card kpi">
        <div className="k row muted small"><HardDrive size={14} /> Disk & OS</div>
        {specs.disks.slice(0, 2).map((d: any) => (
          <div key={d.path} className="small" style={{ marginTop: 6 }}>
            <div className="row between"><span>{d.label}</span><b className="tnum nowrap">{fmtBytes(d.free_bytes, 0)} free</b></div>
            <div className="tiny muted ellipsis" title={d.path}>{d.path}</div>
            <Progress value={1 - d.free_bytes / d.total_bytes} tone={d.free_bytes < 30 * 2 ** 30 ? "warn" : ""} style={{ marginTop: 4 }} />
          </div>
        ))}
        <div className="tiny muted mt-8">{specs.os.pretty} · {specs.os.arch}{specs.os.arch_supported ? "" : " (unsupported)"}</div>
      </div>
    </div>
  );
}

export function NoteList({ notes }: { notes: { level: string; text: string }[] }) {
  return (
    <div className="col">
      {notes.map((n, i) => (
        <Notice key={i} tone={n.level === "danger" ? "danger" : n.level === "warning" ? "warning" : "info"}>{n.text}</Notice>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ memory fit */
export const VERDICT: Record<string, { label: string; tone: string; text: string }> = {
  fits: { label: "Fits in VRAM", tone: "ok", text: "Model and context fit fully on the GPU with headroom." },
  tight: { label: "Tight fit", tone: "warn", text: "Fits, but with little headroom: other apps can push it over." },
  spill: { label: "Spills to RAM", tone: "danger", text: "Exceeds free VRAM: Windows will spill into shared system memory (very slow)." },
  oom: { label: "Out of memory", tone: "danger", text: "Exceeds free VRAM: llama-server will fail to allocate." },
  cpu: { label: "CPU only", tone: "danger", text: "No GPU: everything runs on the CPU." },
};

export function VerdictBadge({ verdict, title }: { verdict?: string; title?: string }) {
  if (!verdict) return <Badge>Not checked</Badge>;
  const v = VERDICT[verdict] || { label: verdict, tone: "" };
  return <Badge tone={v.tone} dot title={title || (v as any).text}>{v.label}</Badge>;
}

const SEG = [
  { key: "weights", label: "Weights", color: "var(--c1)" }, { key: "kv", label: "KV cache", color: "var(--c2)" },
  { key: "compute", label: "Compute", color: "var(--c3)" }, { key: "overhead", label: "CUDA overhead", color: "var(--c10)" },
];

export function MemoryBar({ check }: { check: any }) {
  const mem = check?.memory;
  const gpu = check?.gpu;
  if (!mem) return null;
  const cap = Math.max(gpu?.total_mib || 0, mem.gpu_total, 1);
  const used = (gpu?.total_mib || 0) - (gpu?.free_mib ?? gpu?.total_mib ?? 0);
  return (
    <div className="col" style={{ gap: 10 }}>
      <div className="row between small">
        <b>GPU memory</b>
        <span className="tnum text-2">{fmtMib(mem.gpu_total)} needed · {gpu ? `${fmtMib(gpu.free_mib)} free of ${fmtMib(gpu.total_mib, 0)}` : "no GPU"}</span>
      </div>
      <div className="stackbar" aria-label="GPU memory projection">
        {used > 0 && <div style={{ width: `${(used / cap) * 100}%`, background: "repeating-linear-gradient(45deg, var(--border-strong) 0 4px, var(--surface-3) 4px 8px)" }} title={`${fmtMib(used)} used by other apps`} />}
        {SEG.map((s) => mem.gpu[s.key] ? <div key={s.key} style={{ width: `${(mem.gpu[s.key] / cap) * 100}%`, background: s.color }} title={`${s.label}: ${fmtMib(mem.gpu[s.key], 2)}`} /> : null)}
        {gpu && <div className="limit" style={{ left: `calc(${(Math.min(gpu.total_mib, cap) / cap) * 100}% - 1px)` }} title="VRAM capacity" />}
      </div>
      <div className="legend">
        {used > 0 && <span><i className="sw" style={{ background: "var(--border-strong)" }} />Other apps {fmtMib(used)}</span>}
        {SEG.map((s) => mem.gpu[s.key] ? <span key={s.key}><i className="sw" style={{ background: s.color }} />{s.label} {fmtMib(mem.gpu[s.key], 2)}</span> : null)}
      </div>
      {(mem.cpu?.weights > 0 || mem.cpu?.kv > 0) && (
        <div className="small text-2">System RAM: {fmtMib(mem.cpu_total)} ({fmtMib(mem.cpu.weights)} weights{mem.cpu.kv ? `, ${fmtMib(mem.cpu.kv)} KV` : ""}) · {fmtMib(check.ram_available_mib)} available</div>
      )}
      <div className="tiny muted">
        Source: {mem.source === "llama-fit-params" ? "exact dry-run allocation (llama-fit-params)" : "estimate from the GGUF header (typically within ±70 MiB of llama.cpp)"}
        {check.decode_tps_estimate ? ` · ~${check.decode_tps_estimate} tok/s decode (bandwidth estimate)` : ""}
      </div>
    </div>
  );
}

export function WarningList({ warnings, onFix }: { warnings: any[]; onFix?: (params: any) => void }) {
  if (!warnings?.length) return <Notice tone="ok">No risks found for this configuration.</Notice>;
  const order: Record<string, number> = { danger: 0, warning: 1, info: 2 };
  return (
    <div className="col">
      {[...warnings].sort((a, b) => order[a.level] - order[b.level]).map((w, i) => (
        <Notice key={i} tone={w.level === "danger" ? "danger" : w.level === "warning" ? "warning" : "info"}
          action={w.fix && onFix ? <Button size="xs" onClick={() => onFix(w.fix.params)}>{w.fix.label}</Button> : undefined}>
          {w.text}
        </Notice>
      ))}
    </div>
  );
}

export function ContextChart({ contexts, freeMib, totalMib, current }: { contexts: { ctx: number; gpu_total: number; kv: number }[]; freeMib?: number; totalMib?: number; current?: number }) {
  if (!contexts?.length) return null;
  return (
    <Chart height={200} option={(c: any) => ({
      grid: { left: 8, right: 12, top: 18, bottom: 4, containLabel: true },
      tooltip: { trigger: "axis", valueFormatter: (v: number) => fmtMib(v, 2) },
      xAxis: axis("category", { data: contexts.map((x) => fmtCtx(x.ctx)), name: "context" }),
      yAxis: axis("value", { axisLabel: { color: c.text3, fontSize: 11, formatter: (v: number) => `${(v / 1024).toFixed(0)} GB` } }),
      series: [
        {
          type: "line", name: "GPU memory", smooth: true, symbolSize: 6, data: contexts.map((x) => x.gpu_total), lineStyle: { width: 2.5 },
          areaStyle: { opacity: 0.08 },
          markLine: freeMib || current ? {
            symbol: "none", silent: true, data: [
              { yAxis: freeMib, label: { formatter: "free now", position: "insideStartTop", color: c.warn, fontSize: 11 }, lineStyle: { color: c.warn, type: "dashed" } },
              ...(totalMib ? [{ yAxis: totalMib, label: { formatter: "VRAM", position: "insideStartTop", color: c.danger, fontSize: 11 }, lineStyle: { color: c.danger } }] : []),
              ...(current && contexts.some((x) => x.ctx === current) ? [{ xAxis: fmtCtx(current), label: { formatter: "now", color: c.accent, fontSize: 11 }, lineStyle: { color: c.accent, type: "dotted" } }] : []),
            ],
          } : undefined,
        },
        { type: "bar", name: "KV cache", data: contexts.map((x) => x.kv), barWidth: 10, itemStyle: { color: c.palette[1], opacity: 0.5, borderRadius: 3 } },
      ],
      legend: { show: false },
    })} />
  );
}

/* ------------------------------------------------------------------ misc */
export function VendorIcon({ vendor, name, size = 34 }: { vendor: string; name?: string; size?: number }) {
  return <Logo id={vendor === "custom" ? null : vendor} size={size} title={name} />;
}

export function Gauge({ value, label, size = 74, tone }: { value: number; label?: string; size?: number; tone?: string }) {
  const r = (size - 10) / 2;
  const circ = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(1, value || 0));
  const color = tone || (v > 0.9 ? "var(--danger)" : v > 0.75 ? "var(--warn)" : "var(--accent)");
  return (
    <div className="gauge" style={{ width: size, height: size }} title={label}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-3)" strokeWidth={7} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={7} strokeLinecap="round"
          strokeDasharray={`${circ * v} ${circ}`} style={{ transition: "stroke-dasharray .4s" }} />
      </svg>
      <div className="v tnum" style={{ fontSize: size < 60 ? 12 : 15 }}>{Math.round(v * 100)}%</div>
    </div>
  );
}

export function PathHint({ path }: { path: string }) {
  return (
    <span className="row" style={{ gap: 4 }}>
      <code className="ellipsis" style={{ maxWidth: 420 }} title={path}>{path}</code>
      <CopyButton text={path} label="" />
    </span>
  );
}

export function Kbd({ children }: { children: React.ReactNode }) {
  return <span className="kbd">{children}</span>;
}

export function WarnIcon({ text }: { text: string }) {
  return <Tip text={text}><AlertTriangle size={14} className="warn" /></Tip>;
}

export function NumberCell({ v, digits = 0, suffix = "" }: { v?: number | null; digits?: number; suffix?: string }) {
  return <span className="tnum">{v === null || v === undefined ? "–" : fmtNum(v, digits) + suffix}</span>;
}

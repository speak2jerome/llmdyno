import { useQueryClient } from "@tanstack/react-query";
import { Cloud, Copy, Cpu, Download, FileUp, FlaskConical, MoreHorizontal, Pencil, Plus, Trash2, Wand2, Zap } from "lucide-react";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Logo, profileLogo } from "../logos";
import { api, download } from "../api";
import { VerdictBadge } from "../components";
import { fmtCtx, fmtUsd } from "../format";
import { keys, useJobs, useProfiles } from "../queries";
import { Badge, Button, Card, Empty, Menu, PageHead, Section, Skeleton, Spinner, useConfirm, useToast } from "../ui";

export function SmokeSummary({ smoke }: { smoke: any }) {
  if (!smoke || !smoke.at) return <span className="muted small">Not tested yet</span>;
  if (smoke.error && !smoke.tool_call_ok) return <Badge tone="danger" title={smoke.error}>Test failed</Badge>;
  return (
    <span className="row wrap" style={{ gap: 6 }}>
      {smoke.decode_tps && <Badge tone="info" title="decode speed in the quick test"><Zap size={11} />{smoke.decode_tps} tok/s</Badge>}
      <Badge tone={smoke.tool_call_ok ? "ok" : "danger"} title={smoke.tool_call_detail}>{smoke.tool_call_ok ? "tool calls work" : "tool calls fail"}</Badge>
      {smoke.spill_detected && <Badge tone="danger">spilled to RAM</Badge>}
    </span>
  );
}

export default function Profiles() {
  const profiles = useProfiles();
  const nav = useNavigate();
  const confirm = useConfirm();
  const toast = useToast();
  const qc = useQueryClient();
  const jobs = useJobs();
  const file = useRef<HTMLInputElement>(null);
  const all = profiles.data || [];
  const isSample = (p: any) => (p.tags || []).includes("sample");
  const list = all.filter((p) => !isSample(p));
  const samples = all.filter(isSample);
  const local = list.filter((p) => p.kind === "local");
  const cloud = list.filter((p) => p.kind === "cloud");
  const [showSamples, setShowSamples] = useState(false);
  const test = async (p: any) => {
    try {
      await api.post(`/profiles/${p.id}/smoke`);
      toast.info("Quick test started", p.kind === "local" ? "Loads the model, measures speed and real VRAM, and checks tool calls." : "Sends two short requests: speed and a tool call.");
    } catch (e) {
      toast.err("Could not start the test", e);
    }
  };
  const importFile = async (f: File) => {
    try {
      const body = JSON.parse(await f.text());
      const p = await api.post("/profiles/import", body);
      qc.invalidateQueries({ queryKey: keys.profiles });
      toast.ok("Profile imported", p.name);
    } catch (e) {
      toast.err("Could not import the profile", e);
    }
  };
  const card = (p: any) => {
    const testing = jobs.some((j) => j.kind === "smoke" && j.ref === p.id && ["queued", "running"].includes(j.status));
    const sample = (p.tags || []).includes("sample");
    return (
      <Card key={p.id} onClick={sample ? undefined : () => nav(`/profiles/${p.id}`)}>
        <div className="row" style={{ alignItems: "flex-start" }}>
          <Logo id={profileLogo(p)} size={34} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="row"><b className="ellipsis">{p.name}</b>{sample && <Badge tone="accent">sample</Badge>}</div>
            <div className="small muted ellipsis" style={{ marginTop: 2 }}>
              {p.kind === "local" ? (p.model ? `${p.model.name}` : sample ? "from the bundled sample results" : "model removed") : `${p.provider?.name || "provider removed"} · ${p.remote_model}`}
            </div>
          </div>
          {!sample && (
            <Menu trigger={(o) => <Button size="sm" variant="ghost" iconOnly icon={<MoreHorizontal size={15} />} onClick={o} aria-label="Profile actions" />} items={[
              { label: "Edit", icon: <Pencil size={14} />, onClick: () => nav(`/profiles/${p.id}`) },
              { label: "Run quick test", icon: <FlaskConical size={14} />, onClick: () => test(p) },
              { label: "Duplicate", icon: <Copy size={14} />, onClick: () => api.post(`/profiles/${p.id}/duplicate`).then((n) => { qc.invalidateQueries({ queryKey: keys.profiles }); nav(`/profiles/${n.id}`); }).catch((e) => toast.err("Could not duplicate", e)) },
              { label: "Export JSON", icon: <Download size={14} />, onClick: () => download(`/profiles/${p.id}/export`) },
              "sep",
              { label: "Delete", icon: <Trash2 size={14} />, danger: true, onClick: async () => {
                if (!(await confirm({ title: `Delete ${p.name}?`, body: "Results of past runs are kept.", danger: true, confirm: "Delete" })).ok) return;
                api.del(`/profiles/${p.id}`).then(() => qc.invalidateQueries({ queryKey: keys.profiles })).catch((e) => toast.err("Could not delete", e));
              } },
            ]} />
          )}
        </div>
        <div className="pill-list mt-12">
          {p.kind === "local" && p.model && <Badge tone="accent">{p.model.quant}</Badge>}
          <Badge>{fmtCtx(p.params.ctx)} ctx</Badge>
          {p.kind === "local" && p.params.cache_k && <Badge>KV {p.params.cache_k}{p.params.cache_v !== p.params.cache_k ? `/${p.params.cache_v}` : ""}</Badge>}
          {p.kind === "local" && p.params.gpu_layers !== undefined && p.params.gpu_layers !== "all" && <Badge tone="warn">{p.params.gpu_layers} GPU layers</Badge>}
          {p.kind === "local" && p.params.n_cpu_moe > 0 && <Badge tone="warn">{p.params.n_cpu_moe} MoE layers on CPU</Badge>}
          {p.kind === "cloud" && p.params.reasoning_effort && <Badge>reasoning {p.params.reasoning_effort}</Badge>}
          {p.kind === "cloud" && p.pricing?.input !== undefined && <Badge>{fmtUsd(p.pricing.input)} / {fmtUsd(p.pricing.output)} per M</Badge>}
        </div>
        {!sample && (
          <div className="row between mt-12" style={{ borderTop: "1px solid var(--border)", paddingTop: 10 }}>
            <div className="row" style={{ gap: 6 }}>{p.kind === "local" && <VerdictBadge verdict={p.fit?.verdict} title={p.fit?.verdict ? "last exact memory check" : "run an exact check in the editor"} />}</div>
            {testing ? <span className="row small muted"><Spinner size={13} /> testing…</span> : <SmokeSummary smoke={p.smoke} />}
          </div>
        )}
      </Card>
    );
  };
  return (
    <div className="page">
      <PageHead title="LLM profiles" sub="A profile is a model plus the exact parameters it is benchmarked with: context, KV cache, offload, sampling, reasoning and pricing."
        actions={<>
          <input ref={file} type="file" accept=".json,application/json" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) importFile(f); e.target.value = ""; }} />
          <Button icon={<FileUp size={15} />} onClick={() => file.current?.click()}>Import</Button>
          <Menu trigger={(o) => <Button variant="primary" icon={<Plus size={15} />} onClick={o}>New profile</Button>} items={[
            { label: "Local model (llama.cpp)", icon: <Cpu size={14} />, onClick: () => nav("/profiles/new?kind=local") },
            { label: "Cloud model (API)", icon: <Cloud size={14} />, onClick: () => nav("/profiles/new?kind=cloud") },
          ]} />
        </>} />
      {profiles.isLoading ? <Skeleton h={200} /> : !list.length && !samples.length ? (
        <Card><Empty icon={<Wand2 size={22} />} title="No profiles yet" action={<div className="row">
          <Button variant="primary" icon={<Cpu size={14} />} onClick={() => nav("/profiles/new?kind=local")}>Local profile</Button>
          <Button icon={<Cloud size={14} />} onClick={() => nav("/profiles/new?kind=cloud")}>Cloud profile</Button></div>}>
          Create one profile per configuration you want to compare, for example the same model at two quants or two context sizes.
        </Empty></Card>
      ) : (
        <>
          <Section title="Local" sub={`${local.length} profile(s) · run on this GPU with llama.cpp`}>
            {local.length ? <div className="grid grid-auto">{local.map(card)}</div> : <p className="muted small">No local profiles.</p>}
          </Section>
          <Section title="Cloud" sub={`${cloud.length} profile(s) · run through a provider API with spend caps`}>
            {cloud.length ? <div className="grid grid-auto">{cloud.map(card)}</div> : <p className="muted small">No cloud profiles.</p>}
          </Section>
          {samples.length > 0 && (
            <Section title="Sample profiles" sub={`${samples.length} read-only profiles from the bundled round-1 results`}
              actions={<Button size="sm" variant="ghost" onClick={() => setShowSamples((x) => !x)}>{showSamples ? "Hide" : "Show"}</Button>}>
              {showSamples ? <div className="grid grid-auto">{samples.map(card)}</div> : <p className="muted small">Hidden. They exist so the sample results have names; they cannot be run.</p>}
            </Section>
          )}
        </>
      )}
    </div>
  );
}

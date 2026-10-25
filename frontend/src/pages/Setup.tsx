import { useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { DepRow, JobPanel, NoteList, SystemCards } from "../components";
import { fmtMib } from "../format";
import { keys, useDeps, useSpecs } from "../queries";
import { Button, Card, KV, PageHead, Section, Skeleton, Table, useAction } from "../ui";

export default function Setup() {
  const specs = useSpecs();
  const deps = useDeps();
  const qc = useQueryClient();
  const [jobId, setJobId] = useState<string | null>(null);
  const [rescan, scanning] = useAction(async () => {
    const [s, d] = await Promise.all([api.get("/system/specs?refresh=true"), api.get("/system/deps?refresh=true")]);
    qc.setQueryData(keys.specs, s);
    qc.setQueryData(keys.deps, d);
  });
  const [cleanup, cleaning] = useAction(() => api.post("/system/cleanup"), { ok: (r: any) => r.removed ? `Removed ${r.removed} leftover container${r.removed === 1 ? "" : "s"}` : "No leftover containers" });
  const s = specs.data;
  const groups = [
    { id: "core", title: "Core", sub: "Needed for every benchmark" },
    { id: "local", title: "Local models", sub: "Needed only for models on this machine" },
  ];
  return (
    <div className="page">
      <PageHead title="Setup" sub="System specs and the dependencies LLMDyno needs. Actions run in the background and show their logs below."
        actions={<>
          <Button icon={<Trash2 size={14} />} onClick={() => cleanup()} loading={cleaning} title="Remove proxy/agent containers left behind by a crash">Clean up containers</Button>
          <Button icon={<RefreshCw size={14} />} onClick={() => rescan()} loading={scanning}>Re-scan</Button>
        </>} />
      {specs.isLoading ? <Skeleton h={130} /> : <SystemCards specs={s} />}
      {s && <div className="mt-16"><NoteList notes={s.summary.notes} /></div>}
      {jobId && <div className="mt-16"><JobPanel jobId={jobId} onClose={() => { setJobId(null); rescan(); }} /></div>}
      {groups.map((g) => (
        <Section key={g.id} title={g.title} sub={g.sub}>
          <Card pad={false}>
            <div style={{ padding: "2px 18px" }}>
              {deps.isLoading ? <Skeleton h={120} /> : (deps.data || []).filter((d: any) => d.group === g.id).map((d: any) => (
                <DepRow key={d.id} dep={d} onJob={setJobId} onChanged={() => qc.invalidateQueries({ queryKey: keys.deps })} />
              ))}
            </div>
          </Card>
        </Section>
      ))}
      {s && (
        <Section title="Details">
          <div className="grid grid-2">
            <Card title="GPUs">
              <Table rowKey={(g: any) => g.name + (g.index ?? "")} rows={s.gpus} cols={[
                { key: "name", label: "GPU", render: (g: any) => <b>{g.name}</b> },
                { key: "vendor", label: "Vendor" },
                { key: "vram", label: "VRAM", num: true, render: (g: any) => fmtMib(g.vram_total_mib, 0) },
                { key: "free", label: "Free", num: true, render: (g: any) => g.vram_free_mib != null ? fmtMib(g.vram_free_mib) : "–" },
                { key: "bw", label: "Bandwidth", num: true, render: (g: any) => g.bandwidth_gbs ? `${g.bandwidth_gbs} GB/s` : "–" },
                { key: "backend", label: "Build", render: (g: any) => g.integrated ? <span className="muted">integrated</span> : g.backend.toUpperCase() },
              ]} />
            </Card>
            <Card title="Software">
              <KV items={[
                ["Operating system", s.os.pretty],
                ["Architecture", `${s.os.arch}${s.os.arch_supported ? "" : " (not supported yet)"}`],
                ["Python", s.os.python],
                ["CUDA (driver)", s.cuda_version || "–"],
                ["Docker", s.docker.running ? `${s.docker.server_version} · ${s.docker.engine_os} · ${s.docker.ncpu} CPUs · ${fmtMib((s.docker.mem_total_bytes || 0) / 2 ** 20, 0)}` : s.docker.installed ? "installed, not running" : "not installed"],
                ["GPU in containers", s.docker.nvidia_runtime ? "NVIDIA runtime available" : "not needed (llama-server runs on the host)"],
              ]} />
            </Card>
          </div>
        </Section>
      )}
    </div>
  );
}

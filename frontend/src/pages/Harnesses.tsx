import { useQueryClient } from "@tanstack/react-query";
import { Code2, ExternalLink, Hammer, Layers, Pencil, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { JobPanel } from "../components";
import { fmtAgo, fmtBytes } from "../format";
import { keys, useHarnesses, useJobs } from "../queries";
import {
  Badge, Button, Card, Chip, Code, Drawer, Empty, Field, Input, Modal, Notice, PageHead, Segmented, Select, Skeleton, StatusBadge, Tabs, Textarea,
  useConfirm, useToast,
} from "../ui";

const API_LABEL: Record<string, string> = { "openai-chat": "Chat Completions", "openai-responses": "Responses API", anthropic: "Anthropic Messages" };

export default function Harnesses() {
  const harnesses = useHarnesses();
  const jobs = useJobs();
  const qc = useQueryClient();
  const toast = useToast();
  const [detail, setDetail] = useState<any>(null);
  const [custom, setCustom] = useState<any>(null);
  const [buildJob, setBuildJob] = useState<string | null>(null);
  const build = async (h: any) => {
    try {
      const r = await api.post(`/harnesses/${h.id}/build`);
      setBuildJob(r.job_id);
      toast.info(`Building ${h.name}`, "Usually 1-4 minutes; the log streams below.");
    } catch (e) {
      toast.err("Could not start the build", e);
    }
  };
  useEffect(() => {
    const j = jobs.find((x) => x.id === buildJob);
    if (j && ["done", "failed"].includes(j.status)) qc.invalidateQueries({ queryKey: keys.harnesses });
  }, [jobs, buildJob, qc]);
  const list = harnesses.data || [];
  const buildingIds = new Set(jobs.filter((j) => j.kind === "build" && ["queued", "running"].includes(j.status)).map((j) => j.ref));
  return (
    <div className="page">
      <PageHead title="Agent harnesses" sub="Open-source coding agents, each in its own Docker image built on the offline sandbox. Pick one or several per plan: comparing harnesses on the same model is a benchmark in itself."
        actions={<>
          <Button icon={<Plus size={15} />} onClick={() => setCustom({})}>Custom harness</Button>
          <Button variant="primary" icon={<Hammer size={15} />} disabled={!list.some((h) => h.status !== "ready")} onClick={async () => {
            for (const h of list.filter((x) => x.status !== "ready" && x.builtin)) await build(h);
          }}>Build all missing</Button>
        </>} />
      {buildJob && <div className="mb-16"><JobPanel jobId={buildJob} onClose={() => setBuildJob(null)} /></div>}
      {harnesses.isLoading ? <Skeleton h={220} /> : (
        <div className="grid grid-auto" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))" }}>
          {list.map((h: any) => {
            const building = buildingIds.has(h.id);
            return (
              <Card key={h.id} onClick={() => setDetail(h)}>
                <div className="row" style={{ alignItems: "flex-start" }}>
                  <div className="vendor-ico" style={{ background: "var(--accent)" }}><Layers size={16} /></div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="row"><b>{h.name}</b><span className="muted small mono">v{h.version}</span>{!h.builtin && <Badge tone="accent">custom</Badge>}</div>
                    <div className="tiny muted">{h.license || "licence not set"}</div>
                  </div>
                  <StatusBadge status={building ? "building" : h.status} label={building ? "Building" : h.status === "ready" ? "Image ready" : h.status === "failed" ? "Build failed" : "Not built"} />
                </div>
                <p className="small text-2 mt-12">{h.description}</p>
                <div className="pill-list mt-12">
                  {h.apis.map((a: string) => <Badge key={a}>{API_LABEL[a] || a}</Badge>)}
                  <Badge tone={h.multi_stage === "resume" ? "ok" : ""} title="How multi-stage benchmarks continue">{h.multi_stage === "resume" ? "resumes sessions" : "fresh session per stage"}</Badge>
                  <Badge tone={h.tool_style === "native" ? "" : "warn"}>{h.tool_style === "native" ? "native tool calls" : "text actions"}</Badge>
                </div>
                <div className="row mt-12" style={{ borderTop: "1px solid var(--border)", paddingTop: 10 }} onClick={(e) => e.stopPropagation()}>
                  {h.image_info ? <span className="tiny muted">{fmtBytes(h.image_info.size_bytes)} · {h.built_at ? `built ${fmtAgo(h.built_at)}` : h.image}</span> : <span className="tiny muted">{h.image}</span>}
                  <span className="spacer" />
                  <Button size="sm" variant={h.status === "ready" ? "default" : "primary"} icon={<Hammer size={13} />} loading={building} onClick={() => build(h)}>{h.status === "ready" ? "Rebuild" : "Build"}</Button>
                </div>
              </Card>
            );
          })}
        </div>
      )}
      {!harnesses.isLoading && !list.length && <Empty title="No harnesses" />}
      {detail && <HarnessDrawer h={detail} onClose={() => setDetail(null)} onBuild={() => build(detail)} onEdit={() => { setCustom(detail); setDetail(null); }} />}
      {custom && <CustomHarness initial={custom} onClose={() => setCustom(null)} />}
    </div>
  );
}

function HarnessDrawer({ h, onClose, onBuild, onEdit }: { h: any; onClose: () => void; onBuild: () => void; onEdit: () => void }) {
  const [tab, setTab] = useState<"overview" | "config" | "dockerfile">("overview");
  const [style, setStyle] = useState(h.apis[0]);
  const [preview, setPreview] = useState<any>(null);
  const [dockerfile, setDockerfile] = useState("");
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  useEffect(() => {
    if (tab === "config") api.get(`/harnesses/${h.id}/preview?api_style=${style}`).then(setPreview).catch((e) => setPreview({ error: e.message }));
    if (tab === "dockerfile") api.text(`/harnesses/${h.id}/dockerfile`).then(setDockerfile).catch(() => undefined);
  }, [tab, style, h.id]);
  return (
    <Drawer open onClose={onClose} wide title={`${h.name} ${h.version}`} sub={h.image}
      actions={h.homepage && <Button size="sm" variant="ghost" icon={<ExternalLink size={13} />} onClick={() => window.open(h.homepage, "_blank", "noopener")}>Homepage</Button>}
      footer={<>
        {!h.builtin && <Button variant="danger" icon={<Trash2 size={14} />} onClick={async () => {
          if (!(await confirm({ title: `Delete ${h.name}?`, danger: true, confirm: "Delete" })).ok) return;
          api.del(`/harnesses/custom/${h.id}`).then(() => { qc.invalidateQueries({ queryKey: keys.harnesses }); onClose(); }).catch((e) => toast.err("Could not delete", e));
        }}>Delete</Button>}
        {!h.builtin && <Button icon={<Pencil size={14} />} onClick={onEdit}>Edit</Button>}
        {h.status === "ready" && <Button icon={<Trash2 size={14} />} onClick={async () => {
          if (!(await confirm({ title: "Remove the image?", body: "You can rebuild it any time.", confirm: "Remove image" })).ok) return;
          api.del(`/harnesses/${h.id}/image`).then(() => { qc.invalidateQueries({ queryKey: keys.harnesses }); toast.ok("Image removed"); onClose(); }).catch((e) => toast.err("Could not remove the image", e));
        }}>Remove image</Button>}
        <Button variant="primary" icon={<Hammer size={14} />} onClick={onBuild}>{h.status === "ready" ? "Rebuild" : "Build image"}</Button>
      </>}>
      <Tabs value={tab} onChange={setTab} tabs={[{ value: "overview", label: "Overview" }, { value: "config", label: "Generated config", icon: <Code2 size={13} /> }, { value: "dockerfile", label: "Dockerfile" }]} />
      {tab === "overview" && (
        <div className="col" style={{ gap: 14 }}>
          <p>{h.description}</p>
          {h.status === "failed" && <Notice tone="danger" title="Last build failed">{h.error}</Notice>}
          <div className="grid grid-2">
            <Card title="Strengths">{h.strengths?.length ? <ul style={{ margin: 0, paddingLeft: 18 }}>{h.strengths.map((s: string) => <li key={s}>{s}</li>)}</ul> : <span className="muted">–</span>}</Card>
            <Card title="Caveats">{h.caveats?.length ? <ul style={{ margin: 0, paddingLeft: 18 }}>{h.caveats.map((s: string) => <li key={s}>{s}</li>)}</ul> : <span className="muted">None noted</span>}</Card>
          </div>
          <Card title="How LLMDyno runs it">
            <ul style={{ margin: 0, paddingLeft: 18 }} className="text-2">
              <li>Talks to the per-run proxy at <code>http://dyno-proxy-…:8081</code> using {h.apis.map((a: string) => API_LABEL[a]).join(" or ")}; the proxy holds the real key.</li>
              <li>Runs on an internal Docker network with no internet access, workspace at <code>/workspace</code>, HOME at <code>/home/agent</code> (kept per run).</li>
              <li>{h.multi_stage === "resume" ? "Multi-stage benchmarks continue the same session." : "Multi-stage benchmarks start a new session per stage; files carry over."}</li>
              <li>The transcript (thinking, text, tool calls and results) is captured by the proxy, so it looks the same for every harness.</li>
            </ul>
          </Card>
        </div>
      )}
      {tab === "config" && (
        <div className="col" style={{ gap: 12 }}>
          {h.apis.length > 1 && <Segmented value={style} onChange={setStyle} options={h.apis.map((a: string) => ({ value: a, label: API_LABEL[a] || a }))} />}
          {!preview ? <Skeleton h={200} /> : preview.error ? <Notice tone="danger">{preview.error}</Notice> : (
            <>
              <Field label="Command (stage 1)"><Code code={preview.command} lang="bash" wrap /></Field>
              <Field label="Command (later stages)"><Code code={preview.continue_command} lang="bash" wrap /></Field>
              {Object.keys(preview.env).length > 0 && <Field label="Environment"><Code code={Object.entries(preview.env).map(([k, v]) => `${k}=${v}`).join("\n")} lang="bash" /></Field>}
              {Object.entries(preview.files).map(([path, content]: any) => <Field key={path} label={`~/${path}`}><Code code={content} path={path} /></Field>)}
              <p className="tiny muted">Rendered for an example model; real runs substitute the profile's model id, context and limits.</p>
            </>
          )}
        </div>
      )}
      {tab === "dockerfile" && <Code code={dockerfile || "…"} lang="dockerfile" />}
    </Drawer>
  );
}

function CustomHarness({ initial, onClose }: { initial: any; onClose: () => void }) {
  const editing = !!initial.id;
  const [m, setM] = useState<any>({
    id: initial.id || "", name: initial.name || "", version: initial.version || "1.0.0", description: initial.description || "",
    homepage: initial.homepage || "", license: initial.license || "", apis: initial.apis || ["openai-chat"], multi_stage: initial.multi_stage || "fresh",
    tool_style: initial.tool_style || "native", install: (initial.install || []).join("\n"),
    files: Object.entries(initial.files || {}).map(([path, content]) => ({ path, content })),
    env: Object.entries(initial.env || { OPENAI_BASE_URL: "{openai_base_url}", OPENAI_API_KEY: "proxy-injects-the-key" }).map(([k, v]) => `${k}=${v}`).join("\n"),
    command: initial.command || "my-agent --yes --model {model} \"$PROMPT\"", continue_command: initial.continue_command || "",
  });
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  const toast = useToast();
  const set = (p: any) => setM((x: any) => ({ ...x, ...p }));
  const manifest = () => ({
    id: m.id.trim(), name: m.name.trim(), version: m.version.trim(), description: m.description, homepage: m.homepage, license: m.license,
    apis: m.apis, multi_stage: m.multi_stage, tool_style: m.tool_style, install: m.install.split("\n").filter((l: string) => l.trim()),
    files: Object.fromEntries(m.files.filter((f: any) => f.path.trim()).map((f: any) => [f.path.trim(), f.content])),
    env: Object.fromEntries(m.env.split("\n").filter((l: string) => l.includes("=")).map((l: string) => [l.slice(0, l.indexOf("=")).trim(), l.slice(l.indexOf("=") + 1)])),
    command: m.command, continue_command: m.continue_command || undefined,
  });
  const save = async () => {
    setBusy(true);
    try {
      if (editing) await api.put(`/harnesses/custom/${m.id}`, manifest());
      else await api.post("/harnesses/custom", manifest());
      qc.invalidateQueries({ queryKey: keys.harnesses });
      toast.ok(editing ? "Harness updated" : "Custom harness added", "Build its image next.");
      onClose();
    } catch (e) {
      toast.err("The manifest has problems", e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open onClose={onClose} size="xwide" title={editing ? `Edit ${m.name}` : "Add a custom harness"}
      sub={<>Describe how to install your agent and run it non-interactively. Placeholders: <code>{"{model}"}</code> <code>{"{openai_base_url}"}</code> <code>{"{base_url}"}</code> <code>{"{ctx}"}</code> <code>{"{max_tokens}"}</code> <code>{"{reasoning}"}</code> <code>{"{session_id}"}</code> <code>{"{stage}"}</code> <code>{"{home}"}</code> <code>{"{workspace}"}</code>; the prompt is <code>"$PROMPT"</code>.</>}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={save} disabled={!m.id || !m.name || !m.command.includes("$PROMPT")}>{editing ? "Save" : "Add harness"}</Button></>}>
      <div className="form-grid">
        <Field label="Id" hint="lowercase, e.g. my-agent"><Input value={m.id} onChange={(e) => set({ id: e.target.value.toLowerCase() })} disabled={editing} /></Field>
        <Field label="Name"><Input value={m.name} onChange={(e) => set({ name: e.target.value })} /></Field>
        <Field label="Version"><Input value={m.version} onChange={(e) => set({ version: e.target.value })} /></Field>
        <Field label="Licence"><Input value={m.license} onChange={(e) => set({ license: e.target.value })} placeholder="MIT" /></Field>
        <Field label="Description" className="full"><Input value={m.description} onChange={(e) => set({ description: e.target.value })} /></Field>
        <Field label="APIs it can speak" className="full">
          <div className="pill-list">{["openai-chat", "openai-responses", "anthropic"].map((a) => (
            <Chip key={a} on={m.apis.includes(a)} onClick={() => set({ apis: m.apis.includes(a) ? m.apis.filter((x: string) => x !== a) : [...m.apis, a] })}>{API_LABEL[a]}</Chip>
          ))}</div>
        </Field>
        <Field label="Multi-stage benchmarks"><Select value={m.multi_stage} onChange={(v) => set({ multi_stage: v })} options={[{ value: "fresh", label: "New session per stage" }, { value: "resume", label: "Resume the session (needs a continue command)" }]} aria-label="Multi-stage mode" /></Field>
        <Field label="Tool style"><Select value={m.tool_style} onChange={(v) => set({ tool_style: v })} options={[{ value: "native", label: "Native tool calls" }, { value: "text", label: "Parses actions from text" }]} aria-label="Tool style" /></Field>
        <Field label="Install (Dockerfile lines)" className="full" hint="Network is available only during the build. Use npm_config_offline=false / env -u PIP_NO_INDEX to reach registries.">
          <Textarea code rows={4} value={m.install} onChange={(e) => set({ install: e.target.value })} placeholder={"RUN npm_config_offline=false npm install -g my-agent@1.2.3"} />
        </Field>
        <Field label="Command" className="full"><Textarea code rows={2} value={m.command} onChange={(e) => set({ command: e.target.value })} /></Field>
        <Field label="Continue command (stages 2+)" className="full" hint="Optional; used when the harness resumes sessions"><Textarea code rows={2} value={m.continue_command} onChange={(e) => set({ continue_command: e.target.value })} /></Field>
        <Field label="Environment (KEY=value per line)" className="full"><Textarea code rows={3} value={m.env} onChange={(e) => set({ env: e.target.value })} /></Field>
        <div className="full">
          <div className="row between mb-8"><span className="label">Config files (paths relative to HOME)</span><Button size="xs" icon={<Plus size={12} />} onClick={() => set({ files: [...m.files, { path: "", content: "" }] })}>Add file</Button></div>
          <div className="col">
            {m.files.map((f: any, i: number) => (
              <div key={i} className="card" style={{ padding: 10 }}>
                <div className="row mb-8"><Input className="mono" value={f.path} placeholder=".config/my-agent/config.json" onChange={(e) => set({ files: m.files.map((x: any, j: number) => j === i ? { ...x, path: e.target.value } : x) })} />
                  <Button size="sm" variant="ghost" iconOnly icon={<Trash2 size={13} />} onClick={() => set({ files: m.files.filter((_: any, j: number) => j !== i) })} aria-label="Remove file" /></div>
                <Textarea code rows={4} value={f.content} onChange={(e) => set({ files: m.files.map((x: any, j: number) => j === i ? { ...x, content: e.target.value } : x) })} />
              </div>
            ))}
            {!m.files.length && <p className="muted small">No config files.</p>}
          </div>
        </div>
      </div>
    </Modal>
  );
}

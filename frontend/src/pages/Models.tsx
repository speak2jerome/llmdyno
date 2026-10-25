import { useQueryClient } from "@tanstack/react-query";
import {
  Boxes, Download, ExternalLink, FolderInput, Gauge as GaugeIco, Heart, Info, Lock, Pause, Play, Search, Sparkles, Trash2,
  Wand2, Wrench,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { familyOf, Logo, LogoName, modelLogo } from "../logos";
import { api, qs } from "../api";
import { ContextChart, MemoryBar, VerdictBadge, WarningList } from "../components";
import { fmtAgo, fmtBytes, fmtCtx, fmtMib, fmtNum, plural } from "../format";
import { keys, useJobs, useModels, useSpecs } from "../queries";
import {
  Badge, Button, Card, Drawer, Empty, Field, Input, KV, Menu, Modal, Notice, PageHead, Progress, Skeleton, Spinner,
  StatusBadge, Table, Tabs, Toggle, useAction, useConfirm, useToast,
} from "../ui";
import { useTopic } from "../ws";

const fmtParams = (n?: number) => (!n ? "–" : n >= 1e9 ? `${(n / 1e9).toFixed(n >= 1e10 ? 0 : 1)}B` : `${(n / 1e6).toFixed(0)}M`);

export default function Models() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as "library" | "discover" | "downloads") || "library";
  const models = useModels();
  const [importOpen, setImportOpen] = useState(false);
  const downloading = (models.data || []).filter((m: any) => ["downloading", "queued", "paused", "failed"].includes(m.status));
  return (
    <div className="page">
      <PageHead title="Models" sub="GGUF models on this machine. Discover more on Hugging Face with a memory check for your GPU before you download."
        actions={<>
          <Button icon={<FolderInput size={15} />} onClick={() => setImportOpen(true)}>Import folder</Button>
          <Button variant="primary" icon={<Search size={15} />} onClick={() => setParams({ tab: "discover" })}>Discover models</Button>
        </>} />
      <Tabs value={tab} onChange={(v) => setParams({ tab: v })} tabs={[
        { value: "library", label: "Library", count: (models.data || []).filter((m: any) => m.status === "ready").length },
        { value: "discover", label: "Discover" },
        { value: "downloads", label: "Downloads", count: downloading.length },
      ]} />
      {tab === "library" && <Library models={models.data} loading={models.isLoading} onDiscover={() => setParams({ tab: "discover" })} onImport={() => setImportOpen(true)} />}
      {tab === "discover" && <Discover />}
      {tab === "downloads" && <Downloads models={downloading} />}
      <ImportModal open={importOpen} onClose={() => setImportOpen(false)} />
    </div>
  );
}

function ImportModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [folder, setFolder] = useState("");
  const qc = useQueryClient();
  const [run, busy] = useAction(async () => {
    const r = await api.post("/models/import", { folder: folder.trim() });
    qc.invalidateQueries({ queryKey: keys.models });
    onClose();
    return r;
  }, { ok: (r: any) => r.added ? `Imported ${plural(r.added, "model")}` : "No new GGUF files found in that folder" });
  return (
    <Modal open={open} onClose={onClose} title="Import GGUF files from a folder"
      sub="LLMDyno registers the files where they are; nothing is copied or moved. Split files (-00001-of-00003) are grouped."
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} disabled={!folder.trim()} onClick={() => run()}>Import</Button></>}>
      <Field label="Folder" hint="Searched recursively. mmproj (vision) files are skipped.">
        <Input autoFocus placeholder="C:\Users\me\models" value={folder} onChange={(e) => setFolder(e.target.value)} onKeyDown={(e) => e.key === "Enter" && folder.trim() && run()} />
      </Field>
    </Modal>
  );
}

function Library({ models, loading, onDiscover, onImport }: { models?: any[]; loading: boolean; onDiscover: () => void; onImport: () => void }) {
  const nav = useNavigate();
  const confirm = useConfirm();
  const toast = useToast();
  const qc = useQueryClient();
  const [detail, setDetail] = useState<string | null>(null);
  const ready = (models || []).filter((m) => m.status === "ready");
  if (loading) return <Skeleton h={200} />;
  if (!ready.length) return (
    <Card><Empty icon={<Boxes size={22} />} title="No local models yet" action={<div className="row"><Button variant="primary" onClick={onDiscover}>Discover models</Button><Button onClick={onImport}>Import a folder</Button></div>}>
      Download a quantized GGUF from Hugging Face, or import files you already have.
    </Empty></Card>
  );
  const del = async (m: any) => {
    const r = await confirm({ title: `Remove ${m.name}?`, danger: true, confirm: "Remove",
      body: m.source === "hf" ? "Profiles using it stay but cannot run until you pick another model." : "This removes it from the library. Imported files stay on disk.",
      check: m.source === "hf" ? `Also delete the ${fmtBytes(m.size_bytes)} file from disk (permanent)` : undefined });
    if (!r.ok) return;
    try {
      const res = await api.del(`/models/${m.id}${qs({ delete_files: !!r.checked })}`);
      toast.ok("Model removed", res.removed_files?.length ? `Deleted ${res.removed_files.length} file(s)` : undefined);
      qc.invalidateQueries({ queryKey: keys.models });
    } catch (e) {
      toast.err("Could not remove", e);
    }
  };
  return (
    <>
      <Card pad={false}>
        <Table rowKey={(m: any) => m.id} rows={ready} onRow={(m: any) => setDetail(m.id)} initialSort={{ key: "name", dir: 1 }} cols={[
          { key: "name", label: "Model", sort: (m) => m.name, render: (m: any) => <div className="row" style={{ gap: 10 }}><Logo id={modelLogo(m)} size={30} /><div style={{ minWidth: 0 }}><b>{m.name}</b><div className="tiny muted">{m.repo || m.local_dir}</div></div></div> },
          { key: "quant", label: "Quant", sort: (m) => m.quant, render: (m: any) => <Badge tone="accent">{m.quant}</Badge> },
          { key: "arch", label: "Arch", sort: (m) => m.meta.arch, render: (m: any) => <span className="mono">{m.meta.arch}</span> },
          { key: "params", label: "Params", num: true, sort: (m) => m.meta.n_params, render: (m: any) => fmtParams(m.meta.n_params) },
          { key: "size", label: "Size", num: true, sort: (m) => m.size_bytes, render: (m: any) => fmtBytes(m.size_bytes) },
          { key: "ctx", label: "Trained ctx", num: true, sort: (m) => m.meta.ctx_train, render: (m: any) => fmtCtx(m.meta.ctx_train) },
          { key: "kind", label: "Type", render: (m: any) => <span className="small">{m.meta.expert_count ? `MoE ${m.meta.expert_used}/${m.meta.expert_count}` : "dense"}{m.meta.sliding_window ? " · SWA" : ""}{m.meta.hybrid ? " · hybrid" : ""}</span> },
          { key: "tools", label: "Tools", render: (m: any) => m.meta.chat_template_tools ? <Badge tone="ok">yes</Badge> : <Badge tone="danger">no</Badge> },
          { key: "src", label: "Source", render: (m: any) => <span className="small muted">{m.source === "hf" ? "Hugging Face" : "imported"}</span> },
          { key: "act", label: "", render: (m: any) => (
            <div className="row" style={{ justifyContent: "flex-end" }} onClick={(e) => e.stopPropagation()}>
              <Button size="sm" icon={<Wand2 size={13} />} onClick={() => nav(`/profiles/new?kind=local&model=${m.id}`)}>Create profile</Button>
              <Menu trigger={(o) => <Button size="sm" variant="ghost" iconOnly icon={<Wrench size={14} />} onClick={o} aria-label="More" />} items={[
                { label: "Details", icon: <Info size={14} />, onClick: () => setDetail(m.id) },
                ...(m.repo ? [{ label: "Open on Hugging Face", icon: <ExternalLink size={14} />, onClick: () => window.open(`https://huggingface.co/${m.repo}`, "_blank", "noopener") }] : []),
                "sep" as const,
                { label: "Remove", icon: <Trash2 size={14} />, danger: true, onClick: () => del(m) },
              ]} />
            </div>
          ) },
        ]} />
      </Card>
      {detail && <ModelDrawer id={detail} onClose={() => setDetail(null)} />}
    </>
  );
}

function ModelDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const [m, setM] = useState<any>(null);
  const specs = useSpecs();
  const nav = useNavigate();
  useEffect(() => {
    api.get(`/models/${id}`).then(setM).catch(() => setM({ error: true }));
  }, [id]);
  const g = specs.data?.summary?.primary_gpu;
  return (
    <Drawer open onClose={onClose} title={<LogoName id={modelLogo(m)} size={26}>{m?.name || "Model"}</LogoName>} sub={m?.repo}
      footer={<Button variant="primary" icon={<Wand2 size={14} />} onClick={() => nav(`/profiles/new?kind=local&model=${id}`)}>Create profile</Button>}>
      {!m ? <Skeleton h={300} /> : m.error ? <Notice tone="danger">Could not load this model.</Notice> : (
        <div className="col" style={{ gap: 18 }}>
          <KV items={[
            ["Architecture", <span className="mono">{m.meta.arch}</span>], ["Parameters", fmtParams(m.meta.n_params)],
            ["Quantization", m.quant], ["File size", fmtBytes(m.size_bytes)], ["Layers", m.meta.n_layer],
            ["Embedding", fmtNum(m.meta.n_embd)], ["Attention heads", `${m.meta.n_head} (KV ${m.meta.key_length}-dim)`],
            ["Trained context", fmtNum(m.meta.ctx_train)], ["Vocabulary", fmtNum(m.meta.n_vocab)],
            ["Mixture of experts", m.meta.expert_count ? `${m.meta.expert_used} of ${m.meta.expert_count} active` : "no"],
            ["Sliding window", m.meta.sliding_window ? `${m.meta.sliding_window} tokens` : "no"],
            ["Tool calling", m.meta.chat_template_tools ? "chat template supports tools" : "no tool section in the chat template"],
            ["Thinking", m.meta.chat_template_thinking ? "template has a thinking mode" : "–"],
            ["Recommended sampling", Object.keys(m.meta.sampling || {}).length ? Object.entries(m.meta.sampling).map(([k, v]) => `${k} ${Number.isInteger(Number(v)) ? v : Number(v).toFixed(2)}`).join(" · ") : "–"],
            ["Files", <span className="mono small">{m.paths.join("\n")}</span>],
          ]} />
          <div>
            <h3 className="mb-8">Memory by context (q8_0 KV, all layers on GPU)</h3>
            <ContextChart contexts={m.contexts} freeMib={g?.vram_free_mib} totalMib={g?.vram_total_mib} />
          </div>
          <div>
            <h3 className="mb-8">Tensor types</h3>
            <div className="pill-list">
              {Object.entries(m.meta.tensor_types || {}).slice(0, 12).map(([t, b]: any) => <Badge key={t}>{t} · {fmtBytes(b)}</Badge>)}
            </div>
          </div>
        </div>
      )}
    </Drawer>
  );
}

function Discover() {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [results, setResults] = useState<any[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [repo, setRepo] = useState<string | null>(null);
  const [rec, setRec] = useState<any>(null);
  useEffect(() => {
    api.get("/models/recommended/list").then(setRec).catch(() => undefined);
  }, []);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 350);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => {
    if (debounced.length < 2) {
      setResults(null);
      return;
    }
    setBusy(true);
    setErr(null);
    api.get(`/hub/search${qs({ q: debounced })}`).then(setResults).catch((e) => setErr(e.message)).finally(() => setBusy(false));
  }, [debounced]);
  return (
    <div className="col" style={{ gap: 18 }}>
      <div className="input-group" style={{ maxWidth: 640 }}>
        <Input placeholder="Search Hugging Face GGUF repositories, e.g. qwen3.8 27b, gemma 4, gpt-oss" value={q} onChange={(e) => setQ(e.target.value)} autoFocus aria-label="Search models" />
        <span className="addon">{busy ? <Spinner size={14} /> : <Search size={14} />}</span>
      </div>
      {err && <Notice tone="danger">{err}</Notice>}
      {results && (
        <Card pad={false} title={`${results.length} repositories`} sub="Sorted by downloads">
          <Table rowKey={(r: any) => r.repo} rows={results} onRow={(r: any) => setRepo(r.repo)} cols={[
            { key: "repo", label: "Repository", render: (r: any) => <span className="row"><Logo id={familyOf(r.repo)} size={26} /><b>{r.repo}</b>{r.gated && <Badge tone="warn"><Lock size={11} /> gated</Badge>}</span> },
            { key: "dl", label: "Downloads", num: true, sort: (r) => r.downloads, render: (r: any) => fmtNum(r.downloads) },
            { key: "likes", label: "Likes", num: true, sort: (r) => r.likes, render: (r: any) => <span className="row" style={{ justifyContent: "flex-end", gap: 4 }}><Heart size={12} />{fmtNum(r.likes)}</span> },
            { key: "upd", label: "Updated", render: (r: any) => <span className="small muted">{r.updated ? fmtAgo(Date.parse(r.updated) / 1000) : "–"}</span> },
          ]} empty={<Empty title="No GGUF repositories match">Try a shorter name, such as the model family.</Empty>} />
        </Card>
      )}
      {!results && rec && (
        <>
          <div className="row"><Sparkles size={16} className="info" /><h2>Recommended starting points</h2>
            {rec.gpu && <span className="muted small">for your {rec.gpu.name} ({fmtMib(rec.gpu.vram_total_mib, 0)})</span>}</div>
          <div className="grid grid-3">
            {rec.items.map((r: any) => (
              <Card key={r.repo} onClick={() => setRepo(r.repo)}>
                <div className="row between"><LogoName id={familyOf(r.family, r.repo)} size={26}><b>{r.family}</b></LogoName><Badge>{r.kind}</Badge></div>
                <div className="tiny muted mono mt-8" style={{ marginTop: 2 }}>{r.repo}</div>
                <p className="small text-2 mt-8">{r.why}</p>
                <div className="row mt-12">
                  <Button size="sm" icon={<GaugeIco size={13} />}>Choose a quant</Button>
                  {r.downloaded && <Badge tone="ok">in library</Badge>}
                </div>
              </Card>
            ))}
          </div>
        </>
      )}
      {repo && <RepoDrawer repo={repo} onClose={() => setRepo(null)} />}
    </div>
  );
}

function RepoDrawer({ repo, onClose }: { repo: string; onClose: () => void }) {
  const [info, setInfo] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [showMmproj, setShowMmproj] = useState(false);
  const [checks, setChecks] = useState<Record<string, any>>({});
  const [open, setOpen] = useState<string | null>(null);
  const models = useModels();
  const toast = useToast();
  const qc = useQueryClient();
  const nav = useNavigate();
  useEffect(() => {
    api.get(`/hub/repo${qs({ repo })}`).then(setInfo).catch((e) => setErr(e.message));
  }, [repo]);
  const have = useMemo(() => new Set((models.data || []).filter((m: any) => m.repo === repo).map((m: any) => m.files.join("|"))), [models.data, repo]);
  const check = async (v: any) => {
    setOpen(v.id);
    if (checks[v.id]) return;
    setChecks((c) => ({ ...c, [v.id]: { loading: true } }));
    try {
      const r = await api.post("/hub/estimate", { repo, variant_id: v.id });
      setChecks((c) => ({ ...c, [v.id]: r }));
    } catch (e: any) {
      setChecks((c) => ({ ...c, [v.id]: { error: e.message } }));
    }
  };
  const dl = async (v: any) => {
    try {
      await api.post("/models/download", { repo, variant_id: v.id });
      toast.ok("Download started", `${repo} · ${v.quant}`);
      qc.invalidateQueries({ queryKey: keys.models });
      nav("/models?tab=downloads");
    } catch (e) {
      toast.err("Could not start the download", e);
    }
  };
  const variants = (info?.variants || []).filter((v: any) => showMmproj || !v.mmproj);
  return (
    <Drawer open onClose={onClose} wide title={<LogoName id={familyOf(repo)} size={26}>{repo}</LogoName>} sub={info ? `${fmtNum(info.downloads)} downloads${info.license ? ` · ${info.license}` : ""}${info.base_model ? ` · base: ${[].concat(info.base_model).join(", ")}` : ""}` : "Loading…"}
      actions={<Button size="sm" variant="ghost" icon={<ExternalLink size={13} />} onClick={() => window.open(`https://huggingface.co/${repo}`, "_blank", "noopener")}>Hugging Face</Button>}>
      {err && <Notice tone="danger" title="Could not read the repository">{err}</Notice>}
      {!info && !err && <Skeleton h={260} />}
      {info && (
        <div className="col" style={{ gap: 12 }}>
          <div className="row between">
            <span className="text-2 small">"Check fit" reads only the file header (a few MB) to project memory on your GPU.</span>
            <Toggle checked={showMmproj} onChange={setShowMmproj} label="Show vision projectors" />
          </div>
          {info.gated && <Notice tone="warning">Gated repository: add a Hugging Face token in Settings and accept the terms on huggingface.co first.</Notice>}
          <Card pad={false}>
            <table className="table">
              <thead><tr><th>Quant</th><th>File</th><th className="num">Size</th><th>First look</th><th /></tr></thead>
              <tbody>
                {variants.map((v: any) => {
                  const c = checks[v.id];
                  const owned = have.has(v.files.map((f: any) => f.path.split("/").pop()).join("|"));
                  return [
                    <tr key={v.id}>
                      <td><Badge tone={v.mmproj ? "" : "accent"}>{v.quant}</Badge></td>
                      <td className="mono small ellipsis" style={{ maxWidth: 340 }} title={v.id}>{v.id}{v.files.length > 1 ? ` (${v.files.length} parts)` : ""}</td>
                      <td className="num">{fmtBytes(v.size_bytes)}</td>
                      <td>{v.mmproj ? <span className="muted small">vision</span> : c?.check ? <VerdictBadge verdict={c.check.verdict} /> :
                        v.fits_hint === "likely" ? <Badge tone="ok">likely fits</Badge> : v.fits_hint === "tight" ? <Badge tone="warn">tight</Badge> : v.fits_hint === "no" ? <Badge tone="danger">too big for VRAM</Badge> : null}</td>
                      <td className="right nowrap">
                        {!v.mmproj && <Button size="sm" onClick={() => (open === v.id ? setOpen(null) : check(v))} icon={<GaugeIco size={13} />}>{open === v.id ? "Hide" : "Check fit"}</Button>}{" "}
                        {owned ? <Badge tone="ok">downloaded</Badge> : <Button size="sm" variant="primary" icon={<Download size={13} />} onClick={() => dl(v)}>Download</Button>}
                      </td>
                    </tr>,
                    open === v.id && (
                      <tr key={v.id + "-c"}>
                        <td colSpan={5} style={{ background: "var(--surface-2)" }}>
                          {!c || c.loading ? <div className="row muted"><Spinner /> Reading the GGUF header…</div> : c.error ? <Notice tone="danger">{c.error}</Notice> : (
                            <div className="grid grid-2" style={{ alignItems: "start" }}>
                              <div className="col" style={{ gap: 12 }}>
                                <div className="row"><VerdictBadge verdict={c.check.verdict} /><span className="small text-2">at {fmtCtx(c.params.ctx)} context, {c.params.cache_k} KV, all layers on GPU</span></div>
                                <MemoryBar check={c.check} />
                                <WarningList warnings={c.check.warnings} />
                              </div>
                              <div>
                                <div className="small text-2 mb-8">Projected GPU memory by context</div>
                                <ContextChart contexts={c.contexts} freeMib={c.check.gpu?.free_mib} totalMib={c.check.gpu?.total_mib} />
                                <div className="tiny muted">{c.meta.arch} · {c.meta.n_layer} layers · {c.meta.expert_count ? `MoE ${c.meta.expert_used}/${c.meta.expert_count}` : "dense"} · trained context {fmtCtx(c.meta.ctx_train)}</div>
                              </div>
                            </div>
                          )}
                        </td>
                      </tr>
                    ),
                  ];
                })}
              </tbody>
            </table>
          </Card>
        </div>
      )}
    </Drawer>
  );
}

function Downloads({ models }: { models: any[] }) {
  const [live, setLive] = useState<Record<string, any>>({});
  const toast = useToast();
  const qc = useQueryClient();
  const confirm = useConfirm();
  const jobs = useJobs();
  useTopic("models", (m) => m.data?.id && setLive((l) => ({ ...l, [m.data.id]: { ...(l[m.data.id] || {}), ...m.data } })));
  if (!models.length) return <Card><Empty icon={<Download size={22} />} title="No downloads in progress">Downloads you start from Discover appear here with speed and time left. They resume if interrupted.</Empty></Card>;
  return (
    <div className="col">
      {models.map((m0) => {
        const m = { ...m0, ...(live[m0.id] || {}) };
        const job = jobs.find((j) => j.kind === "download" && j.ref === m.id && ["queued", "running"].includes(j.status));
        const lastFailed = jobs.find((j) => j.kind === "download" && j.ref === m.id && j.status === "failed");
        return (
          <Card key={m.id}>
            <div className="row" style={{ gap: 14 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="row"><Logo id={modelLogo(m)} size={24} /><b className="ellipsis">{m.name}</b><Badge tone="accent">{m.quant}</Badge><StatusBadge status={m.status} /></div>
                <div className="small muted mt-8" style={{ marginTop: 3 }}>{m.repo} · {fmtBytes(m.size_bytes)}{job?.detail ? ` · ${job.detail}` : ""}</div>
                <Progress value={m.progress} style={{ marginTop: 10 }} indeterminate={m.status === "queued"} tone={m.status === "failed" ? "danger" : m.status === "paused" ? "warn" : ""} />
                {m.status === "failed" && (m.error || lastFailed?.detail) && <div className="small danger mt-8">{m.error || lastFailed?.detail}</div>}
              </div>
              <div className="row">
                {job ? <Button icon={<Pause size={14} />} onClick={() => api.post(`/models/${m.id}/pause`).then(() => toast.info("Pausing…")).catch((e) => toast.err("Could not pause", e))}>Pause</Button>
                  : <Button variant="primary" icon={<Play size={14} />} onClick={() => api.post(`/models/${m.id}/resume`).then(() => qc.invalidateQueries({ queryKey: keys.models })).catch((e) => toast.err("Could not resume", e))}>Resume</Button>}
                <Button variant="danger" iconOnly icon={<Trash2 size={14} />} aria-label="Cancel download" disabled={!!job} title={job ? "Pause first" : "Cancel and delete the partial file"}
                  onClick={async () => {
                    const r = await confirm({ title: "Cancel this download?", body: "The partial file is deleted.", danger: true, confirm: "Cancel download" });
                    if (!r.ok) return;
                    api.del(`/models/${m.id}?delete_files=true`).then(() => qc.invalidateQueries({ queryKey: keys.models })).catch((e) => toast.err("Could not cancel", e));
                  }} />
              </div>
            </div>
          </Card>
        );
      })}
      <p className="small muted">Downloads keep going in the background while you use other pages, and resume from where they stopped.</p>
    </div>
  );
}

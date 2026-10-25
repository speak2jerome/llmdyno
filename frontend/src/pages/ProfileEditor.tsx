import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Cloud, Cpu, Download, FlaskConical, RefreshCw, Save, Search, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, download, qs } from "../api";
import { ContextChart, JobPanel, MemoryBar, VerdictBadge, WarningList } from "../components";
import { fmtBytes, fmtCtx, fmtNum, fmtUsd } from "../format";
import { keys, useBenchmarks, useLatestJob, useModels, useProviders, useVendors } from "../queries";
import {
  Badge, Button, Card, Checkbox, Field, Input, KV, Notice, NumInput, PageHead, Segmented, Select, Skeleton, Spinner, Textarea, Toggle,
  useConfirm, useToast,
} from "../ui";
import { SmokeSummary } from "./Profiles";

const CTX_STOPS = [8192, 16384, 32768, 49152, 65536, 98304, 131072, 196608, 262144, 524288, 1048576];
const KV_TYPES = ["f16", "bf16", "q8_0", "q5_1", "q5_0", "q4_1", "q4_0", "iq4_nl", "f32"];

function deepMerge(a: any, b: any) {
  const out = { ...a };
  for (const [k, v] of Object.entries(b || {})) out[k] = v && typeof v === "object" && !Array.isArray(v) && typeof a?.[k] === "object" ? { ...a[k], ...(v as any) } : v;
  return out;
}

export default function ProfileEditor() {
  const { id } = useParams();
  const [sp] = useSearchParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const models = useModels();
  const providers = useProviders();
  const vendors = useVendors();
  const benchmarks = useBenchmarks();
  const isNew = !id;
  const [kind, setKind] = useState<"local" | "cloud">((sp.get("kind") as any) || "local");
  const [name, setName] = useState("");
  const [modelId, setModelId] = useState<string>(sp.get("kind") === "cloud" ? "" : sp.get("model") || "");
  const [providerId, setProviderId] = useState<string>(sp.get("provider") || "");
  const [remoteModel, setRemoteModel] = useState(sp.get("kind") === "cloud" ? sp.get("model") || "" : "");
  const [params, setParams] = useState<any>(null);
  const [pricing, setPricing] = useState<any>({});
  const [notes, setNotes] = useState("");
  const [loaded, setLoaded] = useState<any>(null);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [check, setCheck] = useState<any>(null);
  const [checking, setChecking] = useState(false);
  const [exactBusy, setExactBusy] = useState(false);
  const [benchCtx, setBenchCtx] = useState<string[]>(["t1_flask_site", "t2_fastapi_worker_ts", "t3_long_iterative", "t4_data_ml", "t5_bugfix_semver"]);
  const smokeJob = useLatestJob("smoke", id);
  const [smokeJobId, setSmokeJobId] = useState<string | null>(null);

  // load existing profile
  useEffect(() => {
    if (!id) return;
    api.get(`/profiles/${id}`).then((p) => {
      setLoaded(p);
      setKind(p.kind);
      setName(p.name);
      setModelId(p.model_id || "");
      setProviderId(p.provider_id || "");
      setRemoteModel(p.remote_model || "");
      setParams(p.params);
      setPricing(p.pricing || {});
      setNotes(p.notes || "");
      setDirty(false);
    }).catch((e) => toast.err("Could not load the profile", e));
  }, [id, toast]);

  // defaults for new profiles
  useEffect(() => {
    if (!isNew) return;
    if (kind === "local" && modelId) {
      api.get(`/profiles/defaults${qs({ kind: "local", model_id: modelId })}`).then((d) => setParams(d));
      const m = (models.data || []).find((x: any) => x.id === modelId);
      if (m && !name) setName(`${m.name}`);
    } else if (kind === "cloud") {
      api.get(`/profiles/defaults?kind=cloud`).then((d) => setParams(d));
    } else {
      setParams(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, modelId, isNew]);

  const model = (models.data || []).find((m: any) => m.id === modelId);
  useEffect(() => {
    // suggest a name once the model list has loaded (new profiles only)
    if (isNew && kind === "local" && model && !name) setName(`${model.name} · ${Math.round((params?.ctx || 65536) / 1024)}k`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model?.id]);
  // cloud: name the profile after the model and reasoning effort until the user types their own name
  const autoName = useRef("");
  useEffect(() => {
    if (!isNew || kind !== "cloud" || !remoteModel) return;
    if (name && name !== autoName.current) return;
    const n = `${remoteModel}${params?.reasoning_effort ? ` · ${params.reasoning_effort} reasoning` : ""}`;
    autoName.current = n;
    setName(n);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remoteModel, params?.reasoning_effort, kind, isNew]);
  const provider = (providers.data || []).find((p: any) => p.id === providerId);
  const vendor = (vendors.data || []).find((v: any) => v.id === provider?.vendor);
  const set = (patch: any) => {
    setParams((p: any) => deepMerge(p, patch));
    setDirty(true);
  };

  // live memory check (debounced)
  const timer = useRef<any>();
  useEffect(() => {
    if (kind !== "local" || !modelId || !params) return;
    clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      setChecking(true);
      try {
        setCheck(await api.post("/profiles/check", { model_id: modelId, params, benchmark_ids: benchCtx }));
      } catch (e: any) {
        setCheck({ errors: [e.message] });
      } finally {
        setChecking(false);
      }
    }, 380);
    return () => clearTimeout(timer.current);
  }, [kind, modelId, params, benchCtx]);

  const exact = async () => {
    setExactBusy(true);
    try {
      setCheck(await api.post("/profiles/check", { model_id: modelId, params, exact: true, profile_id: id, benchmark_ids: benchCtx }));
      toast.ok("Exact check done", "llama-fit-params allocated this configuration in a dry run.");
    } catch (e) {
      toast.err("Exact check failed", e);
    } finally {
      setExactBusy(false);
    }
  };

  const save = async (andTest = false) => {
    setSaving(true);
    try {
      let p;
      const body: any = { name: name.trim(), params, notes, pricing };
      if (isNew) {
        p = await api.post("/profiles", { ...body, kind, model_id: modelId || undefined, provider_id: providerId || undefined, remote_model: remoteModel });
      } else {
        p = await api.patch(`/profiles/${id}`, { ...body, remote_model: remoteModel });
      }
      qc.invalidateQueries({ queryKey: keys.profiles });
      setDirty(false);
      toast.ok(isNew ? "Profile created" : "Profile saved", p.name);
      if (andTest) {
        const r = await api.post(`/profiles/${p.id}/smoke`);
        setSmokeJobId(r.job_id);
      }
      if (isNew) nav(`/profiles/${p.id}`, { replace: true });
    } catch (e) {
      toast.err("Could not save", e);
    } finally {
      setSaving(false);
    }
  };

  const del = async () => {
    if (!(await confirm({ title: `Delete ${name}?`, danger: true, confirm: "Delete", body: "Results of past runs are kept." })).ok) return;
    try {
      await api.del(`/profiles/${id}`);
      qc.invalidateQueries({ queryKey: keys.profiles });
      nav("/profiles");
    } catch (e) {
      toast.err("Could not delete", e);
    }
  };

  const readyModels = (models.data || []).filter((m: any) => m.status === "ready");
  const canSave = name.trim() && params && !check?.errors && (kind === "local" ? modelId : providerId && remoteModel.trim());
  const nLayer = model?.meta?.n_layer || 0;

  return (
    <div className="page">
      <div className="row mb-12"><Link to="/profiles" className="row small"><ArrowLeft size={14} /> Profiles</Link></div>
      <PageHead title={isNew ? (kind === "local" ? "New local profile" : "New cloud profile") : name || "Profile"}
        icon={kind === "local" ? <Cpu size={20} className="info" /> : <Cloud size={20} className="info" />}
        sub={kind === "local" ? "Runs on this machine with llama.cpp. The panel on the right updates the memory projection as you change settings."
          : "Runs through a provider's API. The sandbox proxy injects your key and stops at the provider budget."}
        actions={<>
          {!isNew && <Button variant="danger" icon={<Trash2 size={14} />} onClick={del}>Delete</Button>}
          {!isNew && <Button icon={<Download size={14} />} onClick={() => download(`/profiles/${id}/export`)}>Export</Button>}
          <Button icon={<FlaskConical size={14} />} disabled={!canSave} loading={saving} onClick={() => save(true)} title={kind === "local" ? "Save, then load the model and measure speed, real VRAM use and tool calling" : "Save, then send two short requests to check latency, speed and tool calling (a fraction of a cent)"}>Save & test</Button>
          <Button variant="primary" icon={<Save size={14} />} disabled={!canSave || (!dirty && !isNew)} loading={saving} onClick={() => save(false)}>{isNew ? "Create profile" : "Save"}</Button>
        </>} />
      {isNew && (
        <div className="mb-16"><Segmented value={kind} onChange={(v) => { setKind(v); setParams(null); setCheck(null); }} options={[
          { value: "local", label: <span className="row" style={{ gap: 6 }}><Cpu size={13} />Local model</span> },
          { value: "cloud", label: <span className="row" style={{ gap: 6 }}><Cloud size={13} />Cloud API</span> }]} /></div>
      )}
      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1.25fr) minmax(360px, 1fr)", alignItems: "start" }}>
        <div className="col" style={{ gap: 16 }}>
          <Card title="Identity">
            <div className="form-grid">
              <Field label="Profile name" className="full"><Input value={name} onChange={(e) => { setName(e.target.value); setDirty(true); }} placeholder={kind === "cloud" ? "gpt-6-luna · medium reasoning" : "Qwen3.8 27B Q3_K_XL · 64k"} /></Field>
              {kind === "local" ? (
                <Field label="Model" className="full" hint={readyModels.length ? undefined : <>No models yet: <Link to="/models?tab=discover">download one</Link> or import a folder.</>}>
                  <Select value={modelId} onChange={(v) => { setModelId(v); setDirty(true); }} disabled={!isNew} aria-label="Model"
                    options={[{ value: "", label: "Choose a downloaded model…" }, ...readyModels.map((m: any) => ({ value: m.id, label: `${m.name} · ${fmtBytes(m.size_bytes)}` }))]} />
                </Field>
              ) : (
                <>
                  <Field label="Provider" hint={(providers.data || []).length ? undefined : <>No providers: <Link to="/providers">add one</Link> first.</>}>
                    <Select value={providerId} onChange={(v) => { setProviderId(v); setDirty(true); }} disabled={!isNew} aria-label="Provider"
                      options={[{ value: "", label: "Choose a provider…" }, ...(providers.data || []).map((p: any) => ({ value: p.id, label: `${p.name}${p.has_key || p.vendor === "custom" ? "" : " (no key)"}` }))]} />
                  </Field>
                  <ModelPicker provider={provider} value={remoteModel} onChange={(v) => { setRemoteModel(v); setDirty(true); }} />
                </>
              )}
              <Field label="Notes" className="full"><Textarea rows={2} value={notes} onChange={(e) => { setNotes(e.target.value); setDirty(true); }} placeholder="Why this configuration exists, what to compare it with…" /></Field>
            </div>
          </Card>
          {!params ? (kind === "local" && !modelId ? <Notice>Choose a model to see its parameters.</Notice> : kind === "cloud" ? <Skeleton h={300} /> : <Skeleton h={300} />) :
            kind === "local" ? <LocalParams params={params} set={set} model={model} nLayer={nLayer} /> :
              <CloudParams params={params} set={set} vendor={vendor} provider={provider} remoteModel={remoteModel} pricing={pricing} setPricing={(p: any) => { setPricing(p); setDirty(true); }} />}
        </div>
        <div className="col" style={{ gap: 16, position: "sticky", top: 16, maxHeight: "calc(100vh - 32px)", overflowY: "auto", paddingRight: 2 }}>
          {kind === "local" ? (
            <Card title={<span className="row">Memory fit {checking && <Spinner size={13} />}</span>} actions={check?.verdict && <VerdictBadge verdict={check.verdict} />}>
              {!modelId ? <p className="muted small">Choose a model.</p> : !check ? <Skeleton h={160} /> : check.errors ? (
                <Notice tone="danger" title="Invalid parameters">{check.errors.join("; ")}</Notice>
              ) : (
                <div className="col" style={{ gap: 14 }}>
                  <MemoryBar check={check} />
                  <div className="row">
                    <Button size="sm" icon={<RefreshCw size={13} />} loading={exactBusy} onClick={exact} title="Dry-run allocation with llama-fit-params using the exact arguments">Exact check</Button>
                    <span className="tiny muted">{check.memory.source === "llama-fit-params" ? "exact numbers shown" : "estimate shown; exact check takes ~2 s"}</span>
                  </div>
                  {check.fit_error && <Notice tone="warning">Exact check unavailable: {check.fit_error}</Notice>}
                  <WarningList warnings={check.warnings} onFix={(p) => set(p)} />
                  <div>
                    <div className="small text-2 mb-8">GPU memory by context at these settings</div>
                    <ContextChart contexts={check.contexts} freeMib={check.gpu?.free_mib} totalMib={check.gpu?.total_mib} current={params?.ctx} />
                  </div>
                  <Field label="Check context needs against" tip="Benchmarks declare how much context reference runs needed; profiles below that get a warning.">
                    <div className="pill-list">
                      {(benchmarks.data || []).map((b: any) => (
                        <button key={b.id} className={`chip ${benchCtx.includes(b.id) ? "on" : ""}`} onClick={() => setBenchCtx((x) => x.includes(b.id) ? x.filter((y) => y !== b.id) : [...x, b.id])}>
                          {b.title.split(":")[0]} · {Math.round((b.min_context || 0) / 1000)}k
                        </button>
                      ))}
                    </div>
                  </Field>
                </div>
              )}
            </Card>
          ) : (
            <CloudCostCard params={params} pricing={pricing} benchmarks={benchmarks.data || []} />
          )}
          <Card title="Quick test" sub={kind === "local" ? "Loads the model, measures real VRAM, spill and tok/s, then checks a tool call." : "Two short requests: speed, then a tool call."}
            actions={!isNew && <Button size="sm" icon={<FlaskConical size={13} />} onClick={async () => {
              try {
                if (dirty) await save(false);
                const r = await api.post(`/profiles/${id}/smoke`);
                setSmokeJobId(r.job_id);
              } catch (e) {
                toast.err("Could not start the test", e);
              }
            }}>Run test</Button>}>
            {isNew ? <p className="muted small">Save the profile first.</p> : (
              <div className="col">
                {(smokeJobId || (smokeJob && ["queued", "running"].includes(smokeJob.status))) && <JobPanel jobId={smokeJobId || smokeJob?.id} compact />}
                <SmokeResult smoke={loaded?.smoke} id={id!} />
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function SmokeResult({ smoke: initial, id }: { smoke: any; id: string }) {
  const [smoke, setSmoke] = useState(initial);
  const job = useLatestJob("smoke", id);
  useEffect(() => setSmoke(initial), [initial]);
  useEffect(() => {
    if (job?.status === "done" || job?.status === "failed") api.get(`/profiles/${id}`).then((p) => setSmoke(p.smoke)).catch(() => undefined);
  }, [job?.status, id]);
  if (!smoke?.at) return <p className="muted small">No test results yet.</p>;
  return (
    <div className="col">
      <SmokeSummary smoke={smoke} />
      {smoke.error && <Notice tone={smoke.tool_call_ok ? "warning" : "danger"}>{smoke.error}</Notice>}
      <KV items={[
        ...(smoke.load_s !== undefined ? [["Load time", `${smoke.load_s}s`] as [string, string]] : []),
        ...(smoke.vram_used_mib !== undefined && smoke.vram_used_mib !== null ? [["Real VRAM used", `${fmtNum(smoke.vram_used_mib)} MiB (projected ${fmtNum(smoke.projected_gpu_mib)})`] as [string, string]] : []),
        ...(smoke.shared_delta_mib !== undefined && smoke.shared_delta_mib !== null ? [["Spill to shared RAM", `${smoke.shared_delta_mib} MiB`] as [string, string]] : []),
        ...(smoke.decode_tps ? [["Decode speed", `${smoke.decode_tps} tok/s`] as [string, string]] : []),
        ...(smoke.prefill_tps ? [["Prefill speed", `${smoke.prefill_tps} tok/s`] as [string, string]] : []),
        ...(smoke.latency_s ? [["Latency", `${smoke.latency_s}s`] as [string, string]] : []),
        ["Tool call", smoke.tool_call_detail || "–"],
        ...(smoke.cost_usd !== undefined ? [["Cost", fmtUsd(smoke.cost_usd)] as [string, string]] : []),
      ]} />
      {smoke.sample && <details><summary className="small muted" style={{ cursor: "pointer" }}>Sample output</summary><pre className="code wrap small mt-8">{smoke.sample}</pre></details>}
    </div>
  );
}

function ModelPicker({ provider, value, onChange }: { provider: any; value: string; onChange: (v: string) => void }) {
  const [models, setModels] = useState<string[]>(provider?.models_cache || []);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  useEffect(() => setModels(provider?.models_cache || []), [provider?.id, provider?.models_cache]);
  const refresh = async () => {
    if (!provider) return;
    setBusy(true);
    try {
      const r = await api.post(`/providers/${provider.id}/test`);
      if (!r.ok) toast.err("Could not list models", r.error);
      setModels(r.models || []);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Field label="Model id" hint={models.length ? `${models.length} models listed by the provider` : "Type the provider's model id, or refresh the list"}>
      <div className="input-group">
        <Input list="provider-models" value={value} onChange={(e) => onChange(e.target.value)} placeholder="e.g. gpt-6-luna, claude-sonnet-5-5" disabled={!provider} />
        <button type="button" className="addon" style={{ cursor: provider ? "pointer" : "not-allowed", border: "1px solid var(--border-strong)", borderLeft: 0 }} onClick={refresh} disabled={!provider} title="Refresh model list">
          {busy ? <Spinner size={13} /> : <RefreshCw size={13} />}
        </button>
      </div>
      <datalist id="provider-models">{models.map((m) => <option key={m} value={m} />)}</datalist>
    </Field>
  );
}

function Group({ title, children, sub }: { title: string; sub?: string; children: React.ReactNode }) {
  return <Card title={title} sub={sub}><div className="form-grid">{children}</div></Card>;
}

function LocalParams({ params: p, set, model, nLayer }: { params: any; set: (x: any) => void; model: any; nLayer: number }) {
  const ctxTrain = model?.meta?.ctx_train || 262144;
  const stops = CTX_STOPS.filter((c) => c <= Math.max(ctxTrain, 8192));
  const allLayers = p.gpu_layers === "all";
  const moe = (model?.meta?.expert_count || 0) > 0;
  const rec = model?.meta?.sampling || {};
  const [sameKV, setSameKV] = useState(p.cache_k === p.cache_v);
  const ctxIdx = Math.max(0, stops.findIndex((c) => c >= p.ctx));
  return (
    <>
      <Group title="Context & KV cache" sub="The largest memory lever after the weights.">
        <Field label="Context window" className="full" tip="Tokens the model can attend to. Agentic coding typically needs 32k-128k; the KV cache grows linearly with it."
          hint={`Model trained for ${fmtCtx(ctxTrain)}${model?.meta?.sliding_window ? ` · sliding-window layers cap their cache at ${model.meta.sliding_window} tokens` : ""}`}>
          <div className="slider-row">
            <input type="range" min={0} max={stops.length - 1} step={1} value={ctxIdx} onChange={(e) => set({ ctx: stops[+e.target.value] })} aria-label="Context size" />
            <NumInput value={p.ctx} onChange={(v) => v && set({ ctx: Math.round(v) })} min={1024} max={4194304} aria-label="Context tokens" />
          </div>
          <div className="pill-list">{stops.map((c) => <button key={c} type="button" className={`chip ${p.ctx === c ? "on" : ""}`} onClick={() => set({ ctx: c })}>{fmtCtx(c)}</button>)}</div>
        </Field>
        <Field label="K cache type" tip="q8_0 halves KV memory with negligible quality loss; q4 saves more but hurts long-context recall.">
          <Select value={p.cache_k} onChange={(v) => set(sameKV ? { cache_k: v, cache_v: v } : { cache_k: v })} options={KV_TYPES.map((t) => ({ value: t, label: t }))} aria-label="K cache type" />
        </Field>
        <Field label="V cache type">
          <Select value={p.cache_v} onChange={(v) => { set({ cache_v: v }); setSameKV(v === p.cache_k); }} options={KV_TYPES.map((t) => ({ value: t, label: t }))} aria-label="V cache type" />
        </Field>
        <Field label="Flash attention" tip="Required for a quantized V cache; usually faster and smaller.">
          <Segmented value={p.flash_attn} onChange={(v) => set({ flash_attn: v })} options={[{ value: "on", label: "On" }, { value: "auto", label: "Auto" }, { value: "off", label: "Off" }]} />
        </Field>
        {model?.meta?.sliding_window ? (
          <Field label="Full-size SWA cache" tip="Keep the whole context for sliding-window layers too. Only needed for some prompt-cache reuse patterns; costs memory.">
            <Toggle checked={!!p.swa_full} onChange={(v) => set({ swa_full: v })} label={p.swa_full ? "On" : "Off"} />
          </Field>
        ) : <div />}
      </Group>
      <Group title="GPU offload" sub="Everything on the GPU is fastest; offloading trades speed for memory.">
        <Field label="Layers on GPU" className="full" tip="'All' keeps every layer in VRAM. Fewer layers move the rest to system RAM and the CPU, which is much slower.">
          <div className="row wrap">
            <Toggle checked={allLayers} onChange={(v) => set({ gpu_layers: v ? "all" : Math.max(nLayer - 4, 0) })} label="All layers" />
            {!allLayers && (
              <div className="slider-row" style={{ flex: 1, minWidth: 240 }}>
                <input type="range" min={0} max={nLayer} value={p.gpu_layers} onChange={(e) => set({ gpu_layers: +e.target.value })} aria-label="GPU layers" />
                <NumInput value={p.gpu_layers} onChange={(v) => v !== null && set({ gpu_layers: Math.round(v) })} min={0} max={nLayer} />
              </div>
            )}
          </div>
        </Field>
        {moe && (
          <Field label="MoE expert layers on CPU" className="full" tip="Keeps the expert weights of the first N layers in system RAM: the usual way to run a MoE bigger than VRAM. Attention stays on the GPU."
            hint={p.n_cpu_moe ? `${p.n_cpu_moe} of ${nLayer} layers' experts in RAM` : "0 = all experts on the GPU"}>
            <div className="slider-row">
              <input type="range" min={0} max={nLayer} value={p.n_cpu_moe || 0} onChange={(e) => set({ n_cpu_moe: +e.target.value })} aria-label="MoE layers on CPU" />
              <NumInput value={p.n_cpu_moe || 0} onChange={(v) => set({ n_cpu_moe: Math.round(v || 0) })} min={0} max={nLayer} />
            </div>
          </Field>
        )}
        <Field label="llama.cpp auto-fit" tip="llama.cpp can silently reduce GPU layers to keep a memory margin. Off = LLMDyno controls placement exactly, and warns you instead.">
          <Toggle checked={!!p.auto_fit} onChange={(v) => set({ auto_fit: v })} label={p.auto_fit ? "On (may offload silently)" : "Off (recommended)"} />
        </Field>
        <Field label="Safety margin" hint="Kept free when checking fit">
          <NumInput value={p.fit_margin_mib ?? 1024} onChange={(v) => set({ fit_margin_mib: v ?? 1024 })} min={0} max={8192} suffix="MiB" />
        </Field>
      </Group>
      <Group title="Performance">
        <Field label="CPU threads" hint="Empty = automatic"><NumInput allowEmpty value={p.threads} onChange={(v) => set({ threads: v === null ? null : Math.round(v) })} min={1} max={256} placeholder="auto" /></Field>
        <Field label="Parallel slots" tip="Each slot gets ctx / slots tokens. Agents run one at a time, so 1 is right for benchmarking."><NumInput value={p.parallel ?? 1} onChange={(v) => set({ parallel: Math.max(1, Math.round(v || 1)) })} min={1} max={16} /></Field>
        <Field label="Batch size" hint="Empty = 2048"><NumInput allowEmpty value={p.batch} onChange={(v) => set({ batch: v === null ? null : Math.round(v) })} min={32} max={16384} placeholder="2048" /></Field>
        <Field label="Micro-batch (ubatch)" hint="Empty = 512; larger speeds up prefill but needs more compute memory"><NumInput allowEmpty value={p.ubatch} onChange={(v) => set({ ubatch: v === null ? null : Math.round(v) })} min={32} max={8192} placeholder="512" /></Field>
        <Field label="Memory mapping"><div className="col"><Checkbox checked={!!p.mlock} onChange={(v) => set({ mlock: v })}>Lock model in RAM (mlock)</Checkbox><Checkbox checked={!!p.no_mmap} onChange={(v) => set({ no_mmap: v })}>Disable mmap</Checkbox></div></Field>
      </Group>
      <Card title="Sampling" sub="Empty fields use the model's defaults." actions={Object.keys(rec).length > 0 && (
        <Button size="sm" icon={<Sparkles size={13} />} onClick={() => set({ sampling: { temperature: rec.temp !== undefined ? +Number(rec.temp).toFixed(2) : null, top_p: rec.top_p !== undefined ? +Number(rec.top_p).toFixed(2) : null, top_k: rec.top_k ?? null, min_p: rec.min_p !== undefined ? +Number(rec.min_p).toFixed(3) : null } })}>Use model's recommended</Button>)}>
        <div className="form-grid" style={{ gridTemplateColumns: "repeat(3, minmax(0,1fr))" }}>
          {[["temperature", "Temperature", 0, 2], ["top_p", "Top-p", 0, 1], ["top_k", "Top-k", 0, 1000], ["min_p", "Min-p", 0, 1], ["repeat_penalty", "Repeat penalty", 0.5, 2], ["presence_penalty", "Presence penalty", -2, 2]].map(([k, l, mn, mx]) => (
            <Field key={k as string} label={l as string}>
              <NumInput allowEmpty value={p.sampling?.[k as string]} onChange={(v) => set({ sampling: { [k as string]: v } })} min={mn as number} max={mx as number} placeholder="default" />
            </Field>
          ))}
        </div>
      </Card>
      <Group title="Reasoning & output">
        <Field label="Thinking mode" tip="Passed to the chat template (enable_thinking). Auto leaves the template's default.">
          <Segmented value={p.thinking || "auto"} onChange={(v) => set({ thinking: v })} options={[{ value: "auto", label: "Auto" }, { value: "on", label: "On" }, { value: "off", label: "Off" }]} />
        </Field>
        <Field label="Reasoning budget" hint="Empty = unlimited; 0 disables thinking in llama.cpp"><NumInput allowEmpty value={p.reasoning_budget} onChange={(v) => set({ reasoning_budget: v === null ? null : Math.round(v) })} min={-1} max={262144} placeholder="unlimited" suffix="tokens" /></Field>
        <Field label="Max output tokens per turn" tip="What harnesses may request per reply. Reasoning models need 8k or more."><NumInput value={p.max_output_tokens} onChange={(v) => set({ max_output_tokens: Math.round(v || 16384) })} min={256} max={262144} suffix="tokens" /></Field>
      </Group>
      <Card title="Advanced" sub="Raw llama-server arguments, one per line. Model, host, port and context are managed above.">
        <Textarea code rows={3} value={(p.extra_args || []).join("\n")} onChange={(e) => set({ extra_args: e.target.value.split("\n").map((x) => x.trim()).filter(Boolean) })} placeholder={"--override-tensor\nblk\\.(1[0-9])\\.ffn_.*_exps=CPU"} />
        <Field label="Chat-template kwargs (JSON)" className="mt-12">
          <JsonInput value={p.template_kwargs || {}} onChange={(v) => set({ template_kwargs: v })} />
        </Field>
      </Card>
    </>
  );
}

function JsonInput({ value, onChange }: { value: any; onChange: (v: any) => void }) {
  const [text, setText] = useState(JSON.stringify(value));
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => setText(JSON.stringify(value)), [value]);
  return (
    <>
      <Input className="mono" value={text} onChange={(e) => setText(e.target.value)} onBlur={() => {
        try {
          const v = JSON.parse(text || "{}");
          if (typeof v !== "object" || Array.isArray(v)) throw new Error("must be an object");
          setErr(null);
          onChange(v);
        } catch (e: any) {
          setErr(e.message);
        }
      }} />
      {err && <div className="error small danger">{err}</div>}
    </>
  );
}

function CloudParams({ params: p, set, vendor, provider, remoteModel, pricing, setPricing }: any) {
  const [lookup, setLookup] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const doLookup = async () => {
    if (!provider || !remoteModel) return;
    setBusy(true);
    try {
      const r = await api.get(`/pricing/lookup${qs({ vendor: provider.vendor, model: remoteModel })}`);
      setLookup(r.match || { none: true });
      if (r.match && r.match.match === "exact") {
        setPricing({ input: r.match.input, cached: r.match.cached ?? r.match.input, output: r.match.output });
        if (r.match.context && (!p.ctx || p.ctx === 200000)) set({ ctx: Math.min(r.match.context, 1048576) });
      }
    } catch (e) {
      toast.err("Price lookup failed", e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Group title="Model limits & reasoning">
        <Field label="Context window" tip="Told to the harness so it knows when to compact. Use the model's real limit."><NumInput value={p.ctx} onChange={(v) => set({ ctx: Math.round(v || 128000) })} min={4096} max={4194304} suffix="tokens" /></Field>
        <Field label="Max output tokens per turn"><NumInput value={p.max_output_tokens} onChange={(v) => set({ max_output_tokens: Math.round(v || 16384) })} min={256} max={262144} suffix="tokens" /></Field>
        <Field label="Reasoning effort" className="full" tip="Mapped per harness and API: reasoning_effort, Responses reasoning.effort, or Anthropic thinking budgets.">
          <Segmented value={p.reasoning_effort || "none"} onChange={(v) => set({ reasoning_effort: v === "none" ? null : v })} options={["none", "minimal", "low", "medium", "high", "max"].map((x) => ({ value: x, label: x[0].toUpperCase() + x.slice(1) }))} />
        </Field>
        <Field label="Temperature" hint="Empty = provider default (some reasoning models reject it)"><NumInput allowEmpty value={p.temperature} onChange={(v) => set({ temperature: v })} min={0} max={2} placeholder="default" /></Field>
        <Field label="API style" tip="How harnesses talk to this provider. The native style keeps caching and reasoning features.">
          <Select value={p.api_style || ""} onChange={(v) => set({ api_style: v || null })} aria-label="API style"
            options={[{ value: "", label: `Provider default${provider ? ` (${provider.api_style})` : ""}` }, ...Object.keys(vendor?.styles || {}).map((s) => ({ value: s, label: s }))]} />
        </Field>
      </Group>
      <Card title="Pricing" sub="USD per million tokens. Used for cost tracking and the spend cap." actions={<Button size="sm" icon={<Search size={13} />} loading={busy} disabled={!remoteModel} onClick={doLookup}>Look up price</Button>}>
        <div className="form-grid" style={{ gridTemplateColumns: "repeat(3, minmax(0,1fr))" }}>
          <Field label="Input"><NumInput allowEmpty value={pricing.input} onChange={(v) => setPricing({ ...pricing, input: v })} min={0} max={1000} suffix="$/M" /></Field>
          <Field label="Cached input"><NumInput allowEmpty value={pricing.cached} onChange={(v) => setPricing({ ...pricing, cached: v })} min={0} max={1000} suffix="$/M" /></Field>
          <Field label="Output"><NumInput allowEmpty value={pricing.output} onChange={(v) => setPricing({ ...pricing, output: v })} min={0} max={1000} suffix="$/M" /></Field>
        </div>
        {lookup && (lookup.none ? <Notice tone="warning" >No price found for {remoteModel}. Enter it from the provider's pricing page.</Notice> : (
          <div className="mt-12">
            <Notice tone={lookup.match === "exact" ? "ok" : "warning"} title={lookup.match === "exact" ? `Matched ${lookup.name}` : `Closest match: ${lookup.name} (check it is the same model)`}
              action={lookup.match !== "exact" && <Button size="xs" onClick={() => setPricing({ input: lookup.input, cached: lookup.cached ?? lookup.input, output: lookup.output })}>Use these prices</Button>}>
              {fmtUsd(lookup.input)} in · {fmtUsd(lookup.cached)} cached · {fmtUsd(lookup.output)} out per million tokens · context {fmtNum(lookup.context)} · source: OpenRouter catalog
            </Notice>
          </div>
        ))}
      </Card>
    </>
  );
}

function CloudCostCard({ params, pricing, benchmarks }: { params: any; pricing: any; benchmarks: any[] }) {
  const rows = useMemo(() => benchmarks.filter((b) => b.reference_tokens).map((b) => {
    const t = b.reference_tokens;
    const cost = ((t.prompt * (1 - t.cache_hit)) * (pricing.input || 0) + t.prompt * t.cache_hit * (pricing.cached ?? pricing.input ?? 0) + t.output * (pricing.output || 0)) / 1e6;
    return { ...b, cost };
  }), [benchmarks, pricing]);
  const total = rows.reduce((a, r) => a + r.cost, 0);
  return (
    <Card title="Cost estimate" sub="Per run, from token usage in reference runs (about 85% of prompt tokens cached).">
      {!pricing.input && !pricing.output ? <Notice tone="warning">Add prices to estimate cost and enable the spend cap.</Notice> : (
        <div className="col">
          {rows.map((r) => (
            <div key={r.id} className="row between small"><span className="ellipsis">{r.title}</span><b className="tnum">{fmtUsd(r.cost)}</b></div>
          ))}
          <hr style={{ margin: "6px 0" }} />
          <div className="row between"><b>All built-in benchmarks, one iteration</b><b className="tnum">{fmtUsd(total)}</b></div>
          <div className="tiny muted">Context window {fmtCtx(params?.ctx)} · reasoning {params?.reasoning_effort || "off"}. Reasoning-heavy settings can use several times more output tokens.</div>
        </div>
      )}
      <Badge tone="outline" className="mt-12">The proxy enforces the provider budget even if this estimate is off</Badge>
    </Card>
  );
}

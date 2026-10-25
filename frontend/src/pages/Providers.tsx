import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Cloud, ExternalLink, KeyRound, List, MoreHorizontal, Pencil, Plus, RotateCcw, Search, Trash2, Wand2, Wifi, XCircle } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { VendorIcon } from "../components";
import { fmtAgo, fmtUsd } from "../format";
import { keys, useProviders, useVendors } from "../queries";
import {
  Badge, Button, Card, Empty, Field, Input, Menu, Modal, Notice, NumInput, PageHead, Progress, Section, Select, Skeleton, useConfirm, useToast,
} from "../ui";

export default function Providers() {
  const providers = useProviders();
  const vendors = useVendors();
  const [adding, setAdding] = useState<any>(null);
  const [gallery, setGallery] = useState(false);
  const list = providers.data || [];
  return (
    <div className="page">
      <PageHead title="Cloud providers" sub="API keys are encrypted on this machine (Windows DPAPI or a 0600 file) and only ever reach the per-run proxy, never an agent sandbox. Each provider has a hard spend cap."
        actions={<Button variant="primary" icon={<Plus size={15} />} onClick={() => setGallery(true)}>Add provider</Button>} />
      {providers.isLoading ? <Skeleton h={160} /> : list.length ? (
        <div className="grid grid-auto" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))" }}>{list.map((p: any) => <ProviderCard key={p.id} p={p} vendor={(vendors.data || []).find((v: any) => v.id === p.vendor)} />)}</div>
      ) : (
        <Card><Empty icon={<Cloud size={22} />} title="No cloud providers yet" action={<Button variant="primary" onClick={() => setGallery(true)}>Add a provider</Button>}>
          Add OpenAI, Anthropic, Gemini, DeepSeek, Kimi, GLM, Qwen, MiniMax, xAI, Mistral, OpenRouter, Groq, Together, Fireworks, Cerebras, or any OpenAI-compatible endpoint (Ollama, LM Studio, vLLM).
        </Empty></Card>
      )}
      <Section title="Supported vendors" sub="Click one to add it">
        <div className="grid grid-auto" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))" }}>
          {(vendors.data || []).map((v: any) => (
            <Card key={v.id} onClick={() => setAdding(v)}>
              <div className="row"><VendorIcon vendor={v.id} name={v.name} /><div style={{ minWidth: 0 }}><b className="ellipsis">{v.name}</b><div className="tiny muted">{Object.keys(v.styles).join(" · ")}</div></div></div>
            </Card>
          ))}
        </div>
      </Section>
      <Modal open={gallery} onClose={() => setGallery(false)} title="Add a provider" sub="Choose a vendor" size="wide">
        <div className="grid grid-3">
          {(vendors.data || []).map((v: any) => (
            <Card key={v.id} onClick={() => { setGallery(false); setAdding(v); }}>
              <div className="row"><VendorIcon vendor={v.id} name={v.name} /><div><b>{v.name}</b><div className="tiny muted">{v.api_style}</div></div></div>
            </Card>
          ))}
        </div>
      </Modal>
      {adding && <AddProvider vendor={adding} onClose={() => setAdding(null)} />}
    </div>
  );
}

function AddProvider({ vendor, onClose }: { vendor: any; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState(vendor.name);
  const [style, setStyle] = useState(vendor.api_style);
  const [base, setBase] = useState(vendor.styles[vendor.api_style] || vendor.base_url);
  const [key, setKey] = useState("");
  const [budget, setBudget] = useState<number | null>(5);
  const [busy, setBusy] = useState(false);
  const custom = vendor.id === "custom";
  const save = async () => {
    setBusy(true);
    try {
      const p = await api.post("/providers", { vendor: vendor.id, name, api_style: style, base_url: custom ? base : undefined, api_key: key || undefined, budget_usd: budget ?? 0 });
      qc.invalidateQueries({ queryKey: keys.providers });
      if (key || custom) {
        const t = await api.post(`/providers/${p.id}/test`);
        if (t.ok) toast.ok(`${name} connected`, `${t.models.length} models available · ${t.latency_ms} ms`);
        else toast.warn(`${name} added, but the connection test failed`, t.error);
        qc.invalidateQueries({ queryKey: keys.providers });
      } else toast.ok(`${name} added`, "Add an API key to use it.");
      onClose();
    } catch (e) {
      toast.err("Could not add the provider", e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open onClose={onClose} title={<span className="row"><VendorIcon vendor={vendor.id} name={vendor.name} /> Add {vendor.name}</span>}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} disabled={!name.trim() || (custom && !base.trim())} onClick={save}>{key || custom ? "Add & test" : "Add"}</Button></>}>
      <div className="col" style={{ gap: 14 }}>
        {vendor.notes && <Notice>{vendor.notes}</Notice>}
        <Field label="Display name"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
        {Object.keys(vendor.styles).length > 1 && (
          <Field label="API style" tip="openai-chat = Chat Completions; openai-responses = Responses API; anthropic = Messages API. Harnesses pick a style both sides support.">
            <Select value={style} onChange={(v) => { setStyle(v); if (!custom) setBase(vendor.styles[v] || vendor.base_url); }} options={Object.keys(vendor.styles).map((s) => ({ value: s, label: s }))} aria-label="API style" />
          </Field>
        )}
        <Field label="Base URL" hint={custom ? "Use host.docker.internal instead of localhost for servers on this machine." : "Fixed for this vendor"}>
          <Input value={base} onChange={(e) => setBase(e.target.value)} disabled={!custom} className="mono" />
        </Field>
        <Field label="API key" hint={vendor.keys_url ? <a href={vendor.keys_url} target="_blank" rel="noreferrer" className="row" style={{ gap: 4, display: "inline-flex" }}>Get a key <ExternalLink size={11} /></a> : custom ? "Optional for local servers" : undefined}>
          <Input type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder={custom ? "optional" : "sk-…"} />
        </Field>
        <Field label="Budget (hard cap)" tip="The proxy refuses requests once spend reaches this. Judging and quick tests count too." hint="USD across all plans for this provider">
          <NumInput value={budget} onChange={setBudget} min={0} max={100000} suffix="USD" />
        </Field>
      </div>
    </Modal>
  );
}

function ProviderCard({ p, vendor }: { p: any; vendor: any }) {
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const nav = useNavigate();
  const [testing, setTesting] = useState(false);
  const [keyOpen, setKeyOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [modelsOpen, setModelsOpen] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: keys.providers });
  const test = async () => {
    setTesting(true);
    try {
      const r = await api.post(`/providers/${p.id}/test`);
      if (r.ok) toast.ok("Connection works", `${r.models.length} models · ${r.latency_ms} ms`);
      else toast.err("Connection failed", r.error);
      refresh();
    } catch (e) {
      toast.err("Connection test failed", e);
    } finally {
      setTesting(false);
    }
  };
  const lc = p.last_check || {};
  const frac = p.budget_usd ? p.spent_usd / p.budget_usd : 0;
  return (
    <Card>
      <div className="row" style={{ alignItems: "flex-start" }}>
        <VendorIcon vendor={p.vendor} name={vendor?.name || p.name} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <b className="ellipsis">{p.name}</b>
          <div className="tiny muted mono ellipsis" title={p.base_url}>{p.base_url}</div>
        </div>
        <Menu trigger={(o) => <Button size="sm" variant="ghost" iconOnly icon={<MoreHorizontal size={15} />} onClick={o} aria-label="Provider actions" />} items={[
          { label: "Edit", icon: <Pencil size={14} />, onClick: () => setEditOpen(true) },
          { label: p.has_key ? "Replace API key" : "Add API key", icon: <KeyRound size={14} />, onClick: () => setKeyOpen(true) },
          { label: "Remove API key", icon: <XCircle size={14} />, disabled: !p.has_key, onClick: async () => {
            if (!(await confirm({ title: "Remove the API key?", danger: true, confirm: "Remove key" })).ok) return;
            api.del(`/providers/${p.id}/key`).then(refresh).catch((e) => toast.err("Could not remove", e));
          } },
          { label: "Reset spend counter", icon: <RotateCcw size={14} />, onClick: async () => {
            if (!(await confirm({ title: "Reset the spend counter?", body: "Only LLMDyno's own counter is reset; your provider still bills what was used.", confirm: "Reset" })).ok) return;
            api.post(`/providers/${p.id}/reset-spend`).then(refresh).catch((e) => toast.err("Could not reset", e));
          } },
          "sep",
          { label: "Delete provider", icon: <Trash2 size={14} />, danger: true, onClick: async () => {
            if (!(await confirm({ title: `Delete ${p.name}?`, body: "The stored key is deleted too.", danger: true, confirm: "Delete" })).ok) return;
            api.del(`/providers/${p.id}`).then(refresh).catch((e) => toast.err("Could not delete", e));
          } },
        ]} />
      </div>
      <div className="pill-list mt-12">
        <Badge>{p.api_style}</Badge>
        {p.has_key ? <Badge tone="ok"><KeyRound size={11} /> {p.key_hint}</Badge> : p.vendor === "custom" ? <Badge>no key needed</Badge> : <Badge tone="warn">no API key</Badge>}
        {lc.at && (lc.ok ? <Badge tone="ok" title={`tested ${fmtAgo(lc.at)}`}><CheckCircle2 size={11} /> {lc.n_models} models · {lc.latency_ms} ms</Badge> : <Badge tone="danger" title={lc.error}><XCircle size={11} /> test failed</Badge>)}
      </div>
      {p.vendor !== "custom" && (
        <div className="mt-12">
          <div className="row between small"><span className="text-2">Spend</span><span className="tnum"><b>{fmtUsd(p.spent_usd)}</b> of {fmtUsd(p.budget_usd)}</span></div>
          <Progress value={frac} tone={frac > 0.9 ? "danger" : frac > 0.7 ? "warn" : "ok"} style={{ marginTop: 6 }} />
        </div>
      )}
      <div className="row mt-12" style={{ gap: 6 }}>
        <Button size="sm" icon={<Wifi size={13} />} loading={testing} onClick={test} disabled={!p.has_key && p.vendor !== "custom"}>Test</Button>
        <Button size="sm" icon={<List size={13} />} onClick={() => setModelsOpen(true)} disabled={!p.models_cache?.length}>Models</Button>
        <Button size="sm" icon={<Wand2 size={13} />} onClick={() => nav(`/profiles/new?kind=cloud`)}>New profile</Button>
      </div>
      {keyOpen && <KeyModal p={p} onClose={() => { setKeyOpen(false); refresh(); }} />}
      {editOpen && <EditModal p={p} vendor={vendor} onClose={() => { setEditOpen(false); refresh(); }} />}
      {modelsOpen && <ModelsModal p={p} onClose={() => setModelsOpen(false)} />}
    </Card>
  );
}

function KeyModal({ p, onClose }: { p: any; onClose: () => void }) {
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  return (
    <Modal open onClose={onClose} title={`API key for ${p.name}`} sub="Stored encrypted on this machine. It is never shown again."
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} disabled={!key.trim()} onClick={async () => {
        setBusy(true);
        try {
          await api.put(`/providers/${p.id}/key`, { api_key: key.trim() });
          const t = await api.post(`/providers/${p.id}/test`);
          t.ok ? toast.ok("Key saved and verified", `${t.models.length} models`) : toast.warn("Key saved, but the test failed", t.error);
          onClose();
        } catch (e) {
          toast.err("Could not save the key", e);
        } finally {
          setBusy(false);
        }
      }}>Save & test</Button></>}>
      <Input type="password" autoFocus autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder="Paste the key" />
    </Modal>
  );
}

function EditModal({ p, vendor, onClose }: { p: any; vendor: any; onClose: () => void }) {
  const [name, setName] = useState(p.name);
  const [budget, setBudget] = useState<number | null>(p.budget_usd);
  const [style, setStyle] = useState(p.api_style);
  const [base, setBase] = useState(p.base_url);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  return (
    <Modal open onClose={onClose} title={`Edit ${p.name}`}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={async () => {
        setBusy(true);
        try {
          await api.patch(`/providers/${p.id}`, { name, budget_usd: budget ?? 0, api_style: style, ...(p.vendor === "custom" ? { base_url: base } : {}) });
          toast.ok("Provider updated");
          onClose();
        } catch (e) {
          toast.err("Could not update", e);
        } finally {
          setBusy(false);
        }
      }}>Save</Button></>}>
      <div className="col" style={{ gap: 14 }}>
        <Field label="Display name"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="API style"><Select value={style} onChange={setStyle} options={Object.keys(vendor?.styles || { [p.api_style]: "" }).map((s) => ({ value: s, label: s }))} aria-label="API style" /></Field>
        {p.vendor === "custom" && <Field label="Base URL"><Input className="mono" value={base} onChange={(e) => setBase(e.target.value)} /></Field>}
        <Field label="Budget (hard cap)" hint={`Spent so far: ${fmtUsd(p.spent_usd)}`}><NumInput value={budget} onChange={setBudget} min={0} max={100000} suffix="USD" /></Field>
      </div>
    </Modal>
  );
}

function ModelsModal({ p, onClose }: { p: any; onClose: () => void }) {
  const [q, setQ] = useState("");
  const nav = useNavigate();
  const list = useMemo(() => (p.models_cache || []).filter((m: string) => m.toLowerCase().includes(q.toLowerCase())), [p.models_cache, q]);
  return (
    <Modal open onClose={onClose} title={`${p.name} models`} sub={`${p.models_cache.length} listed by the provider`} size="wide">
      <div className="input-group mb-12"><Input autoFocus placeholder="Filter" value={q} onChange={(e) => setQ(e.target.value)} /><span className="addon"><Search size={13} /></span></div>
      <div style={{ maxHeight: 420, overflowY: "auto" }}>
        {list.map((m: string) => (
          <div key={m} className="row between hover-row" style={{ padding: "6px 8px", borderRadius: 6 }}>
            <span className="mono small">{m}</span>
            <Button size="xs" onClick={() => nav(`/profiles/new?kind=cloud&provider=${p.id}&model=${encodeURIComponent(m)}`)}>Create profile</Button>
          </div>
        ))}
        {!list.length && <p className="muted small">No match.</p>}
      </div>
    </Modal>
  );
}

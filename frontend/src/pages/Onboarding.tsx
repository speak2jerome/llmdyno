import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Boxes, Cloud, Cpu, FlaskConical, RefreshCw, ShieldCheck, Sparkles } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { Dyno } from "../dyno";
import { DepRow, JobPanel, NoteList, SystemCards } from "../components";
import { keys, useDeps, useSpecs } from "../queries";
import { Button, Card, Notice, Skeleton, useToast } from "../ui";

const STEPS = ["Welcome", "Your system", "Dependencies", "Get started"];

export default function Onboarding({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState(0);
  const specs = useSpecs();
  const deps = useDeps();
  const qc = useQueryClient();
  const nav = useNavigate();
  const toast = useToast();
  const [jobId, setJobId] = useState<string | null>(null);
  const [rescanning, setRescanning] = useState(false);
  const finish = async (to?: string) => {
    await api.patch("/settings", { onboarded: true }).catch(() => undefined);
    qc.invalidateQueries({ queryKey: keys.settings });
    onClose();
    if (to) nav(to);
  };
  const rescan = async () => {
    setRescanning(true);
    try {
      const [s, d] = await Promise.all([api.get("/system/specs?refresh=true"), api.get("/system/deps?refresh=true")]);
      qc.setQueryData(keys.specs, s);
      qc.setQueryData(keys.deps, d);
    } finally {
      setRescanning(false);
    }
  };
  const required = (deps.data || []).filter((d: any) => d.level === "required");
  const missingRequired = required.filter((d: any) => !d.ok);
  const archOk = specs.data?.os?.arch_supported !== false;
  return (
    <div className="onboard" role="dialog" aria-modal="true" aria-label="Set up LLMDyno">
      <div className="onboard-inner">
        <div className="row between mb-16">
          <div className="brand" style={{ padding: 0 }}>
            <Dyno size={36} />
            <div><div className="brand-name">LLM<span className="dyno-word">Dyno</span></div><small>First-run setup</small></div>
          </div>
          <Button variant="ghost" onClick={() => finish()}>Skip setup</Button>
        </div>
        <div className="stepper">
          {STEPS.map((s, i) => (
            <button key={s} className={`step ${i === step ? "on" : i < step ? "done" : ""}`} onClick={() => setStep(i)} disabled={i > step + 1}>
              <span className="n">{i + 1}</span>{s}
            </button>
          ))}
        </div>

        {step === 0 && (
          <div className="col" style={{ gap: 18 }}>
            <div className="row" style={{ gap: 20, alignItems: "center" }}>
              <Dyno state="running" size={112} />
              <h1 style={{ fontSize: 30 }}>Put your LLM on the dyno</h1>
            </div>
            <p className="text-2" style={{ fontSize: 15, maxWidth: 720 }}>
              LLMDyno runs real agent harnesses against hidden-test benchmarks, with local GGUF models on your GPU or any
              cloud API, and compares correctness, code quality, speed and cost on one dashboard.
            </p>
            <div className="grid grid-3">
              {[
                { i: <Cpu size={18} />, t: "Hardware-aware", d: "Every profile gets a VRAM projection with warnings about out-of-memory, spill into system RAM and CPU offload before you run it." },
                { i: <ShieldCheck size={18} />, t: "Sandboxed and fair", d: "Agents run in offline Docker sandboxes behind a proxy that holds your API keys, measures every token and enforces budgets." },
                { i: <FlaskConical size={18} />, t: "Hidden tests + judges", d: "Graders run hidden tests after the agent finishes; LLM judges you choose review the code blind." },
              ].map((x) => (
                <Card key={x.t}>
                  <div className="col">
                    <div className="row" style={{ gap: 8, color: "var(--accent-text)" }}>{x.i}<b style={{ color: "var(--text)" }}>{x.t}</b></div>
                    <p className="text-2 small">{x.d}</p>
                  </div>
                </Card>
              ))}
            </div>
            <div><Button variant="primary" icon={<ArrowRight size={15} />} onClick={() => setStep(1)}>Scan my system</Button></div>
          </div>
        )}

        {step === 1 && (
          <div className="col" style={{ gap: 16 }}>
            <div className="row between">
              <div>
                <h2 style={{ fontSize: 20 }}>Your system</h2>
                <p className="text-2 mt-8" style={{ marginTop: 4 }}>Detected hardware decides which models fit and which llama.cpp build to install.</p>
              </div>
              <Button icon={<RefreshCw size={14} />} loading={rescanning} onClick={rescan}>Scan again</Button>
            </div>
            {specs.isLoading ? <Skeleton h={140} /> : <SystemCards specs={specs.data} />}
            {specs.data && <NoteList notes={specs.data.summary.notes} />}
            {!archOk && <Notice tone="danger" title="Unsupported architecture">LLMDyno currently supports x86-64 (Windows and Linux). ARM support is planned.</Notice>}
            <div className="row">
              <Button icon={<ArrowLeft size={15} />} onClick={() => setStep(0)}>Back</Button>
              <Button variant="primary" icon={<ArrowRight size={15} />} onClick={() => setStep(2)} disabled={!archOk}>Check dependencies</Button>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="col" style={{ gap: 16 }}>
            <div className="row between">
              <div>
                <h2 style={{ fontSize: 20 }}>Install what's recommended</h2>
                <p className="text-2" style={{ marginTop: 4 }}>Required items must be in place before a benchmark can start. Each action shows its progress here.</p>
              </div>
              <Button icon={<RefreshCw size={14} />} loading={rescanning} onClick={rescan}>Re-check</Button>
            </div>
            <Card pad={false}>
              <div style={{ padding: "4px 18px" }}>
                {deps.isLoading ? <Skeleton h={200} /> : (deps.data || []).map((d: any) => (
                  <DepRow key={d.id} dep={d} onJob={setJobId} onChanged={() => qc.invalidateQueries({ queryKey: keys.deps })} />
                ))}
              </div>
            </Card>
            {jobId && <JobPanel jobId={jobId} onClose={() => { setJobId(null); rescan(); }} />}
            {missingRequired.length > 0 && <Notice tone="warning">{missingRequired.length} required item(s) still missing: {missingRequired.map((d: any) => d.name).join(", ")}. You can continue and finish later on the Setup page.</Notice>}
            <div className="row">
              <Button icon={<ArrowLeft size={15} />} onClick={() => setStep(1)}>Back</Button>
              <Button variant="primary" icon={<ArrowRight size={15} />} onClick={() => setStep(3)}>Continue</Button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="col" style={{ gap: 16 }}>
            <h2 style={{ fontSize: 20 }}>What do you want to benchmark first?</h2>
            <div className="grid grid-3">
              <Card onClick={() => finish("/models")}>
                <div className="col"><Boxes size={22} className="info" /><b>Local models</b>
                  <p className="text-2 small">Pull GGUF models from Hugging Face (or import ones you have) and see what fits your GPU.</p></div>
              </Card>
              <Card onClick={() => finish("/providers")}>
                <div className="col"><Cloud size={22} className="info" /><b>Cloud APIs</b>
                  <p className="text-2 small">Add OpenAI, Anthropic, Gemini, DeepSeek, Kimi, GLM, Qwen, Mistral, OpenRouter and more, with spend caps.</p></div>
              </Card>
              <Card onClick={async () => {
                try {
                  await api.post("/sample");
                } catch (e: any) {
                  if (e.status !== 409) toast.err("Could not load the sample", e);
                }
                qc.invalidateQueries();
                finish("/results");
              }}>
                <div className="col"><Sparkles size={22} className="info" /><b>Explore sample results</b>
                  <p className="text-2 small">Load the bundled round-1 study (15 profiles × 5 tasks on an RTX 5080) to see the dashboard right away.</p></div>
              </Card>
            </div>
            <div className="row"><Button icon={<ArrowLeft size={15} />} onClick={() => setStep(2)}>Back</Button><Button variant="primary" onClick={() => finish("/")}>Finish</Button></div>
          </div>
        )}
      </div>
    </div>
  );
}

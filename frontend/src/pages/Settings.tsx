import { useQueryClient } from "@tanstack/react-query";
import { KeyRound, Monitor, Moon, Save, Sparkles, Sun, Trash2, Wand2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { keys, useSample, useSettings } from "../queries";
import { useTheme } from "../theme";
import { Dyno, type DynoState } from "../dyno";
import { Badge, Button, Card, Field, Input, KV, Notice, NumInput, PageHead, Segmented, Skeleton, useConfirm, useToast } from "../ui";

export default function Settings({ onOnboard }: { onOnboard: () => void }) {
  const settings = useSettings();
  const sample = useSample();
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const { pref, setPref } = useTheme();
  const [form, setForm] = useState<any>(null);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (settings.data && !form) setForm(settings.data);
  }, [settings.data, form]);
  if (!form) return <div className="page"><Skeleton h={400} /></div>;
  const s = settings.data;
  const changed = ["models_dir", "runs_dir", "electricity_usd_per_kwh", "default_vram_margin_mib", "cloud_concurrency", "llama_port"].some((k) => form[k] !== s[k]);
  const save = async () => {
    setBusy(true);
    try {
      await api.patch("/settings", Object.fromEntries(["models_dir", "runs_dir", "electricity_usd_per_kwh", "default_vram_margin_mib", "cloud_concurrency", "llama_port"].map((k) => [k, form[k]])));
      qc.invalidateQueries({ queryKey: keys.settings });
      qc.invalidateQueries({ queryKey: keys.deps });
      toast.ok("Settings saved");
    } catch (e) {
      toast.err("Could not save settings", e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="page">
      <PageHead title="Settings" actions={<>
        <Button icon={<Wand2 size={14} />} onClick={onOnboard}>Run setup wizard</Button>
        <Button variant="primary" icon={<Save size={14} />} disabled={!changed} loading={busy} onClick={save}>Save</Button>
      </>} />
      <div className="grid grid-2" style={{ alignItems: "start" }}>
        <div className="col" style={{ gap: 16 }}>
          <Card title="Folders" sub="Changing a folder does not move existing files.">
            <div className="col" style={{ gap: 14 }}>
              <Field label="Models folder" hint="Where downloads go. Put it on a disk with plenty of space."><Input className="mono" value={form.models_dir} onChange={(e) => setForm({ ...form, models_dir: e.target.value })} /></Field>
              <Field label="Runs folder" hint="Workspaces, transcripts and logs of every run (~5-60 MB each)."><Input className="mono" value={form.runs_dir} onChange={(e) => setForm({ ...form, runs_dir: e.target.value })} /></Field>
              <KV items={[["Data folder", <code>{s.data_dir}</code>], ["Database", <code>{s.data_dir}/llmdyno.db</code>]]} />
            </div>
          </Card>
          <Card title="Runs">
            <div className="form-grid">
              <Field label="Electricity price" tip="Local runs are costed by measured GPU energy at this price."><NumInput value={form.electricity_usd_per_kwh} onChange={(v) => setForm({ ...form, electricity_usd_per_kwh: v ?? 0 })} min={0} max={5} suffix="USD/kWh" /></Field>
              <Field label="Cloud runs in parallel (default)"><NumInput value={form.cloud_concurrency} onChange={(v) => setForm({ ...form, cloud_concurrency: Math.round(v || 1) })} min={1} max={16} /></Field>
              <Field label="VRAM safety margin for exact checks"><NumInput value={form.default_vram_margin_mib} onChange={(v) => setForm({ ...form, default_vram_margin_mib: Math.round(v ?? 1024) })} min={0} max={8192} suffix="MiB" /></Field>
              <Field label="llama-server port"><NumInput value={form.llama_port} onChange={(v) => setForm({ ...form, llama_port: Math.round(v || 18180) })} min={1024} max={65535} /></Field>
            </div>
          </Card>
        </div>
        <div className="col" style={{ gap: 16 }}>
          <Card title="Appearance">
            <Segmented value={pref} onChange={setPref} options={[{ value: "light", label: <span className="row" style={{ gap: 6 }}><Sun size={13} />Light</span> }, { value: "dark", label: <span className="row" style={{ gap: 6 }}><Moon size={13} />Dark</span> }, { value: "system", label: <span className="row" style={{ gap: 6 }}><Monitor size={13} />System</span> }]} />
          </Card>
          <Card title={<span className="row"><KeyRound size={15} /> Hugging Face token</span>} sub="Needed for gated repositories. Stored encrypted like provider keys.">
            <div className="row">
              <Input type="password" autoComplete="off" aria-label="Hugging Face token" value={token} onChange={(e) => setToken(e.target.value)} placeholder={s.hf_token_set ? "A token is saved; paste to replace" : "hf_…"} />
              <Button disabled={!token.trim()} onClick={async () => { await api.put("/settings/hf-token", { token: token.trim() }).catch((e) => toast.err("Could not save", e)); setToken(""); qc.invalidateQueries({ queryKey: keys.settings }); toast.ok("Token saved"); }}>Save</Button>
              {s.hf_token_set && <Button variant="danger" iconOnly icon={<Trash2 size={14} />} aria-label="Remove token" onClick={async () => { await api.del("/settings/hf-token"); qc.invalidateQueries({ queryKey: keys.settings }); toast.ok("Token removed"); }} />}
            </div>
            {s.hf_token_set && <Badge tone="ok" className="mt-12">token saved</Badge>}
          </Card>
          <Card title={<span className="row"><Sparkles size={15} /> Sample results</span>} sub="The bundled round-1 study: 15 profiles × 5 tasks on an RTX 5080, Pi harness, two judges.">
            {sample.data?.loaded ? (
              <div className="row"><Badge tone="ok">loaded</Badge><Button variant="danger" size="sm" onClick={async () => {
                if (!(await confirm({ title: "Remove the sample results?", body: "Only the bundled sample plan and its profiles are removed.", confirm: "Remove sample", danger: true })).ok) return;
                await api.del("/sample");
                qc.invalidateQueries();
                toast.ok("Sample removed");
              }}>Remove</Button></div>
            ) : <Button onClick={async () => { try { await api.post("/sample"); qc.invalidateQueries(); toast.ok("Sample loaded", "Open Results to explore it."); } catch (e) { toast.err("Could not load", e); } }}>Load sample results</Button>}
          </Card>
          <Notice>LLMDyno runs entirely on this machine. Nothing is uploaded except the model requests you configure; agent sandboxes have no internet access.</Notice>
        </div>
      </div>
      <AboutDyno />
    </div>
  );
}

const DYNO_STATES: { state: DynoState; label: string; when: string }[] = [
  { state: "idle", label: "Idle", when: "Nothing running. Hover it." },
  { state: "running", label: "Running", when: "A benchmark plan is running: sprinting, booster lit." },
  { state: "warmup", label: "Warm-up", when: "A quick profile test: jogging, booster cold." },
  { state: "judging", label: "Judging", when: "LLM judges are reviewing the code." },
  { state: "celebrate", label: "Finished", when: "A plan just completed." },
  { state: "panic", label: "Panic stop", when: "Everything was stopped: frozen red, then reset." },
];

/** Sprint for a moment, then panic: shows the freeze and the reset. */
function PanicDemo() {
  const [st, setSt] = useState<DynoState>("running");
  useEffect(() => {
    const t = setInterval(() => setSt((x) => (x === "running" ? "panic" : "running")), 3200);
    return () => clearInterval(t);
  }, []);
  return <Dyno state={st} size={96} />;
}

function AboutDyno() {
  const [replay, setReplay] = useState(0);
  useEffect(() => {
    if (location.hash === "#about") setTimeout(() => document.getElementById("about")?.scrollIntoView({ behavior: "smooth" }), 50);
  }, []);
  return (
    <Card className="mt-16" id="about" title="About LLMDyno" sub="The mascot reflects what the app is doing; the browser tab icon and title follow it too."
      actions={<Button size="sm" variant="ghost" onClick={() => setReplay((r) => r + 1)}>Replay animations</Button>}>
      <div className="grid dyno-gallery">
        {DYNO_STATES.map((d) => (
          <div key={d.state + replay} className="col" style={{ alignItems: "center", textAlign: "center", gap: 8 }}>
            {d.state === "panic" ? <PanicDemo /> : <Dyno state={d.state} size={96} />}
            <b className="small">{d.label}</b>
            <span className="tiny muted">{d.when}</span>
          </div>
        ))}
      </div>
      <div className="row wrap small muted mt-16" style={{ gap: 16 }}>
        <span className="mono">LLMDyno {__APP_VERSION__}</span>
        <span>MIT licensed</span>
        <a href="https://github.com/speak2jerome/llmdyno" target="_blank" rel="noreferrer">Source on GitHub</a>
        <span>Pixel font: Press Start 2P (OFL)</span>
      </div>
    </Card>
  );
}

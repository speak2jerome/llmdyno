// Panic stop: one always-visible control that halts every run, judge, test and download, removes every sandbox and
// proxy container (cutting agents off from paid APIs) and kills llama-server. It always asks first.
import { useQueryClient } from "@tanstack/react-query";
import { OctagonX } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "./api";
import { Button, Modal, Notice, Spinner, useToast } from "./ui";

type Active = {
  jobs: { id: string; kind: string; title: string }[]; plans: { id: string; name: string }[];
  runs_running: number; runs_queued: number; containers: { name: string; role: string }[]; llama_server: boolean; idle: boolean;
};

export function PanicButton() {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState<Active | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const qc = useQueryClient();
  const show = () => {
    setActive(null);
    setOpen(true);
    api.get<Active>("/system/active").then(setActive).catch(() => setActive(null));
  };
  useEffect(() => {
    // Ctrl+Shift+X opens the dialog from anywhere; the stop itself still needs a click
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "x") {
        e.preventDefault();
        show();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const stop = async () => {
    setBusy(true);
    window.dispatchEvent(new Event("llmdyno:panic"));      // the mascot freezes and turns red right away
    try {
      const r = await api.post<any>("/system/panic");
      setOpen(false);
      qc.invalidateQueries();
      const parts = [
        r.runs_cancelled && `${r.runs_cancelled} run(s)`, r.jobs_cancelled && `${r.jobs_cancelled} job(s)`,
        r.containers_killed + r.proxies_killed > 0 && `${r.containers_killed + r.proxies_killed} container(s)`,
        (r.llama_server_stopped || r.stray_llama_servers_killed > 0) && "llama-server",
      ].filter(Boolean);
      toast.ok("Everything stopped", parts.length ? `Stopped ${parts.join(", ")} in ${r.seconds}s.` : `Nothing was running (checked in ${r.seconds}s).`);
    } catch (e) {
      toast.err("Panic stop failed", e);
    } finally {
      setBusy(false);
    }
  };
  const others = (active?.jobs || []).filter((j) => j.kind !== "plan");
  const items = active ? [
    active.plans.length > 0 && `${active.plans.length} running plan${active.plans.length === 1 ? "" : "s"}: ${active.plans.map((p) => p.name).join(", ")}`,
    active.runs_running > 0 && `${active.runs_running} run${active.runs_running === 1 ? "" : "s"} in progress`,
    active.runs_queued > 0 && `${active.runs_queued} queued run${active.runs_queued === 1 ? "" : "s"} of ${active.plans.length === 1 ? "that plan" : "those plans"}`,
    others.length > 0 && `${others.length === 1 ? "1" : others.length}${active.plans.length ? " other" : ""} background job${others.length === 1 ? "" : "s"}: ${others.map((j) => j.title).slice(0, 4).join(", ")}`,
    active.containers.length > 0 && `${active.containers.length} container${active.containers.length === 1 ? "" : "s"} (${[...new Set(active.containers.map((c) => c.role))].join(", ")})`,
    active.llama_server && "the llama-server process holding the GPU",
  ].filter(Boolean) as string[] : [];
  return (
    <>
      <button className="btn danger panic-btn" onClick={show} title="Stop every run, job, container and model server (Ctrl+Shift+X)" aria-label="Panic stop: stop everything">
        <OctagonX size={15} /> Stop everything
      </button>
      <Modal open={open} onClose={() => !busy && setOpen(false)} title="Stop everything now?"
        sub="For runaway loops, a frozen machine or climbing API spend."
        footer={<>
          <Button onClick={() => setOpen(false)} disabled={busy}>Cancel</Button>
          <Button variant="danger-solid" icon={<OctagonX size={15} />} loading={busy} onClick={stop} autoFocus>Stop everything</Button>
        </>}>
        <div className="col" style={{ gap: 12 }}>
          {!active ? <div className="row muted small"><Spinner size={13} /> Checking what is running…</div> : active.idle && !active.containers.length ? (
            <Notice tone="ok" title="Nothing is running right now">You can still run the stop to clean up anything a crash left behind.</Notice>
          ) : (
            <div>
              <div className="small muted" style={{ marginBottom: 6 }}>This stops:</div>
              <ul className="panic-list">{items.map((t) => <li key={t}>{t}</li>)}</ul>
            </div>
          )}
          <Notice tone="warning">
            Running runs are marked <b>cancelled</b> and their partial work is kept on disk. Paused plans and finished results are not
            touched. Downloads pause and can be resumed. Requests already sent to a provider may still be billed.
          </Notice>
        </div>
      </Modal>
    </>
  );
}

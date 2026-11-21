// Import external benchmarks: SWE-bench (official datasets, official harness) and Aider polyglot.
import { useQueryClient } from "@tanstack/react-query";
import { Download, ExternalLink, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { JobPanel } from "../components";
import { keys, useImports, useJob } from "../queries";
import { Badge, Button, Checkbox, Field, Modal, Notice, Skeleton, Tabs, useConfirm, useToast } from "../ui";

type Kind = "swebench" | "polyglot";

export function ImportModal({ initial = "swebench", onClose }: { initial?: Kind; onClose: () => void }) {
  const [tab, setTab] = useState<Kind>(initial);
  const cat = useImports();
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const [jobId, setJobId] = useState<string | null>(null);
  const { job } = useJob(jobId);
  const running = !!job && ["queued", "running"].includes(job.status);
  const [dataset, setDataset] = useState("verified_mini");
  const [limitText, setLimitText] = useState("");
  const limit = limitText ? Math.max(1, Math.min(2000, Number(limitText))) : null;
  const [langs, setLangs] = useState<string[]>(["cpp", "go", "java", "javascript", "python", "rust"]);
  const c = cat.data;
  const start = async (path: string, body: unknown) => {
    try {
      const r = await api.post(path, body);
      setJobId(r.job_id);
    } catch (e) {
      toast.err("Could not start", e);
    }
  };
  const remove = async (kind: Kind, n: number) => {
    const label = kind === "swebench" ? "SWE-bench" : "Aider polyglot";
    if (!(await confirm({ title: `Remove ${n} imported ${label} benchmarks?`, danger: true, confirm: "Remove",
      body: "Their suites go too. Results of past runs are kept, and you can import the tasks again." })).ok) return;
    try {
      const r = await api.del(`/imports/${kind}`);
      qc.invalidateQueries({ queryKey: keys.benchmarks });
      qc.invalidateQueries({ queryKey: keys.suites });
      qc.invalidateQueries({ queryKey: keys.imports });
      toast.ok(`Removed ${r.removed} benchmarks`);
    } catch (e) {
      toast.err("Could not remove", e);
    }
  };
  const ds = c?.swebench.datasets.find((d: any) => d.id === dataset);
  const nImport = limit ? Math.min(limit, ds?.size || limit) : ds?.size;
  const arm = c?.runtime_platform === "linux/arm64";
  const footer = tab === "swebench"
    ? <><Button onClick={onClose}>Close</Button>
        <Button variant="primary" icon={<Download size={14} />} loading={running} disabled={!c}
          onClick={() => start("/imports/swebench", { dataset, limit: limit || 0 })}>Import {nImport ?? ""} task{nImport === 1 ? "" : "s"}</Button></>
    : <><Button onClick={onClose}>Close</Button>
        <Button variant="primary" icon={<Download size={14} />} loading={running} disabled={!c || !langs.length}
          onClick={() => start("/imports/polyglot", { languages: langs })}>Import exercises</Button></>;
  return (
    <Modal open onClose={onClose} size="wide" title="Import a public benchmark"
      sub="Tasks become benchmarks you can put in suites and plans, graded the same way as on the public leaderboards." footer={footer}>
      <Tabs value={tab} onChange={setTab} tabs={[
        { value: "swebench", label: "SWE-bench", count: c?.swebench.imported || undefined },
        { value: "polyglot", label: "Aider polyglot", count: c?.polyglot.imported || undefined },
      ]} />
      {!c ? <Skeleton h={220} /> : tab === "swebench" ? (
        <div className="col" style={{ gap: 14 }}>
          <p className="small text-2">
            Real GitHub issues from popular Python projects. The agent works inside each task's official Docker image, and
            its patch is graded by the official SWE-bench harness: a task is resolved only if every FAIL_TO_PASS and
            PASS_TO_PASS test passes. <a href={c.swebench.homepage} target="_blank" rel="noreferrer">swebench.com <ExternalLink size={11} /></a>
          </p>
          <Field label="Dataset">
            <div className="col" style={{ gap: 6 }}>
              {c.swebench.datasets.map((d: any) => (
                <label key={d.id} className={`choice ${dataset === d.id ? "on" : ""}`}>
                  <input type="radio" name="swe-ds" checked={dataset === d.id} onChange={() => setDataset(d.id)} />
                  <span><b>{d.name}</b> <span className="muted small">· {d.size} tasks</span>
                    {d.id === "verified_mini" && <Badge tone="ok" className="ml-6">good first run</Badge>}
                    <div className="tiny muted">{d.about}</div></span>
                </label>
              ))}
            </div>
          </Field>
          <Field label="How many" hint="Leave empty for the whole dataset. Tasks are taken in dataset order.">
            <div className="input-group">
              <input className="input" inputMode="numeric" aria-label="Number of tasks to import" value={limitText}
                placeholder={`all ${ds?.size ?? ""}`} onChange={(e) => setLimitText(e.target.value.replace(/\D/g, "").slice(0, 4))} />
              <span className="addon">tasks</span>
            </div>
          </Field>
          {c.swebench.harness.installed
            ? <Notice tone="ok">Official harness: swebench {c.swebench.harness.version}, in its own environment.</Notice>
            : <Notice tone="warning" title="Install the SWE-bench harness to grade these tasks"
                action={<Button size="sm" onClick={() => start("/imports/swebench/harness", {})}>Install harness</Button>}>
                Installs swebench {c.swebench.harness_version} from PyPI (about 250 MB) into a separate virtual environment, so its
                dependencies never touch LLMDyno's.
              </Notice>}
          <Notice title="Disk and time">
            Each task pulls its Docker image the first time it runs (1-5 GB; images of the same project share layers).
            Budget 10-40 minutes per task and harness on a local model.
            {arm && <> This machine is ARM64: the images are x86-64 only and run under emulation (Rosetta on Apple Silicon,
              QEMU on Linux), roughly 2-5x slower. Turn on emulation in Docker first.</>}
          </Notice>
          {c.swebench.imported > 0 && (
            <div className="row between small">
              <span className="muted">{c.swebench.imported} SWE-bench tasks imported.</span>
              <Button size="sm" variant="ghost" icon={<Trash2 size={13} />} onClick={() => remove("swebench", c.swebench.imported)}>Remove imported</Button>
            </div>
          )}
        </div>
      ) : (
        <div className="col" style={{ gap: 14 }}>
          <p className="small text-2">
            225 of Exercism's hardest exercises in six languages, from Aider's polyglot benchmark. An exercise is solved when every
            test passes, with all tests enabled. <a href={c.polyglot.repo} target="_blank" rel="noreferrer">polyglot-benchmark <ExternalLink size={11} /></a>
          </p>
          <Field label="Languages">
            <div className="row wrap" style={{ gap: 14 }}>
              {Object.entries(c.polyglot.languages).map(([id, name]: any) => (
                <Checkbox key={id} checked={langs.includes(id)} onChange={(v) => setLangs((x) => v ? [...x, id] : x.filter((y) => y !== id))}>{name}</Checkbox>
              ))}
            </div>
          </Field>
          {c.polyglot.image_info
            ? <Notice tone="ok">Toolchain image {c.polyglot.image} is built.</Notice>
            : <Notice tone="warning" title="The exercises need the polyglot toolchain image"
                action={c.polyglot.context_ready && <Button size="sm" onClick={() => start("/imports/polyglot/image", {})}>Build image</Button>}>
                {c.polyglot.context_ready
                  ? "About 4 GB: Go, Rust, JDK 21 with Gradle, CMake and jest, with the exercises' dependencies cached for offline use."
                  : "Import first: the image is built from the exercises' own build files. Then build it here or on the Setup page."}
              </Notice>}
          <Notice title="How this compares with Aider's leaderboard">
            Aider gives the model two tries with the test output in between. LLMDyno agents run the tests themselves as often as
            they like within the time limit, so solved rates are close to, but not the same as, Aider's published numbers.
          </Notice>
          {c.polyglot.imported > 0 && (
            <div className="row between small">
              <span className="muted">{c.polyglot.imported} polyglot exercises imported.</span>
              <Button size="sm" variant="ghost" icon={<Trash2 size={13} />} onClick={() => remove("polyglot", c.polyglot.imported)}>Remove imported</Button>
            </div>
          )}
        </div>
      )}
      {jobId && <div className="mt-16"><JobPanel jobId={jobId} compact /></div>}
      {job?.status === "done" && job.result?.imported != null && (
        <Notice tone="ok" title={`Imported ${job.result.imported} benchmarks`}
          action={<Link to="/benchmarks" onClick={onClose}>View them</Link>}>
          {job.result.suite_id ? "A suite with all of them is ready for a plan." : "Suites per language are ready for a plan."}
          {job.result.errors?.length ? ` ${job.result.errors.length} skipped: ${job.result.errors[0]}` : ""}
        </Notice>
      )}
    </Modal>
  );
}

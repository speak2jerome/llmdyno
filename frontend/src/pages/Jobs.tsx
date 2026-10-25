import { Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { JobPanel } from "../components";
import { fmtAgo, fmtDur } from "../format";
import { forgetFinishedJobs, useJobs } from "../queries";
import { Button, Card, Chip, Empty, PageHead, Progress, StatusBadge, Table, useToast } from "../ui";

const KINDS = ["all", "plan", "download", "build", "install", "judge", "smoke", "validate"];

export default function Jobs() {
  const jobs = useJobs();
  const toast = useToast();
  const [kind, setKind] = useState("all");
  const [sel, setSel] = useState<string | null>(null);
  const list = jobs.filter((j) => kind === "all" || j.kind === kind);
  return (
    <div className="page">
      <PageHead title="Activity" sub="Every background job: plans, downloads, image builds, installs, judging, profile tests and grader validation."
        actions={<Button icon={<Trash2 size={14} />} onClick={async () => {
          try {
            const r = await api.del("/jobs");
            forgetFinishedJobs();
            toast.ok(`Cleared ${r.removed} finished job(s)`);
          } catch (e) {
            toast.err("Could not clear", e);
          }
        }}>Clear finished</Button>} />
      <div className="row wrap mb-16">{KINDS.map((k) => <Chip key={k} on={kind === k} onClick={() => setKind(k)}>{k === "all" ? "All" : k}</Chip>)}</div>
      {sel && <div className="mb-16"><JobPanel jobId={sel} onClose={() => setSel(null)} /></div>}
      <Card pad={false}>
        {list.length ? (
          <Table rowKey={(j: any) => j.id} rows={list} onRow={(j: any) => setSel(j.id)} cols={[
            { key: "title", label: "Job", render: (j: any) => <div><b className="small">{j.title}</b><div className="tiny muted">{j.kind} · {j.id}</div></div> },
            { key: "status", label: "Status", render: (j: any) => <StatusBadge status={j.status} /> },
            { key: "progress", label: "Progress", render: (j: any) => ["queued", "running"].includes(j.status) ? <div style={{ minWidth: 140 }}><Progress value={j.progress} indeterminate={!j.progress} /><div className="tiny muted ellipsis mt-8" style={{ marginTop: 3, maxWidth: 260 }}>{j.detail}</div></div> : <span className="tiny muted ellipsis" style={{ maxWidth: 280, display: "inline-block" }} title={j.detail}>{j.detail}</span> },
            { key: "dur", label: "Duration", num: true, render: (j: any) => j.started_at ? fmtDur((j.ended_at || Date.now() / 1000) - j.started_at) : "–" },
            { key: "created", label: "Created", num: true, render: (j: any) => <span className="small muted">{fmtAgo(j.created_at)}</span> },
          ]} />
        ) : <Empty title="No jobs">Background work shows up here with live logs.</Empty>}
      </Card>
    </div>
  );
}

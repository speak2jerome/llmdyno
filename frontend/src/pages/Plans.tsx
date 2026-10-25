import { useQueryClient } from "@tanstack/react-query";
import { PlayCircle, Plus } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { fmtAgo, fmtDur, fmtUsd } from "../format";
import { keys, usePlans } from "../queries";
import { Badge, Button, Card, Empty, PageHead, Progress, Skeleton, StatusBadge, Table } from "../ui";
import { useTopic } from "../ws";

export default function Plans() {
  const plans = usePlans();
  const nav = useNavigate();
  const qc = useQueryClient();
  useTopic("plans", () => qc.invalidateQueries({ queryKey: keys.plans }));
  const list = plans.data || [];
  return (
    <div className="page">
      <PageHead title="Runs" sub="Benchmark plans and their progress. Open one to watch agents live."
        actions={<Button variant="primary" icon={<Plus size={15} />} onClick={() => nav("/plans/new")}>New plan</Button>} />
      {plans.isLoading ? <Skeleton h={200} /> : list.length ? (
        <Card pad={false}>
          <Table rowKey={(p: any) => p.id} rows={list} onRow={(p: any) => nav(`/plans/${p.id}`)} initialSort={{ key: "created", dir: -1 }} cols={[
            { key: "name", label: "Plan", sort: (p) => p.name, render: (p: any) => <div><b>{p.name}</b>{p.sample && <Badge tone="accent" className="mt-8"> sample</Badge>}<div className="tiny muted">{p.profile_ids.length} profiles · {p.harness_ids.length} harnesses · {p.benchmark_ids.length} benchmarks · {p.iterations}×</div></div> },
            { key: "status", label: "Status", sort: (p) => p.status, render: (p: any) => <StatusBadge status={p.status} /> },
            { key: "progress", label: "Progress", render: (p: any) => {
              const done = (p.counts.done || 0) + (p.counts.failed || 0) + (p.counts.cancelled || 0) + (p.counts.skipped || 0);
              return <div style={{ minWidth: 160 }}><div className="row between tiny"><span>{done}/{p.n_runs}</span>{p.counts.failed ? <span className="danger">{p.counts.failed} failed</span> : null}</div><Progress value={done / Math.max(1, p.n_runs)} tone={p.counts.failed ? "warn" : "ok"} style={{ marginTop: 4 }} /></div>;
            } },
            { key: "dur", label: "Duration", num: true, sort: (p) => (p.ended_at || Date.now() / 1000) - (p.started_at || 0), render: (p: any) => p.started_at ? fmtDur((p.ended_at || Date.now() / 1000) - p.started_at) : "–" },
            { key: "spend", label: "Cloud spend", num: true, sort: (p) => p.spent_usd, render: (p: any) => fmtUsd(p.spent_usd) },
            { key: "created", label: "Created", num: true, sort: (p) => p.created_at, render: (p: any) => <span className="small muted">{fmtAgo(p.created_at)}</span> },
          ]} />
        </Card>
      ) : (
        <Card><Empty icon={<PlayCircle size={22} />} title="No plans yet" action={<Button variant="primary" onClick={() => nav("/plans/new")}>Create a plan</Button>}>
          Choose profiles, harnesses, benchmarks and iterations; LLMDyno checks memory, keys and budgets before anything starts.
        </Empty></Card>
      )}
    </div>
  );
}

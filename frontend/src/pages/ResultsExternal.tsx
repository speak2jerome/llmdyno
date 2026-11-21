// Results panels for public benchmarks: SWE-bench resolved / polyglot solved rates, and Artificial Analysis reference
// numbers (intelligence index, speed, price) next to what LLMDyno measured.
import { useQueryClient } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { fmtNum, fmtPct, fmtUsd } from "../format";
import { LogoName } from "../logos";
import { keys, useAA } from "../queries";
import { Badge, Card, Select, Table, useToast } from "../ui";

const median = (v: number[]) => {
  const s = v.filter((x) => x != null && !isNaN(x)).sort((a, b) => a - b);
  return s.length ? (s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2) : null;
};
const LANG: Record<string, string> = { cpp: "C++", go: "Go", java: "Java", javascript: "JS", python: "Python", rust: "Rust" };

/** Share of SWE-bench tasks resolved and polyglot exercises solved, per configuration. */
export function PublicScores({ configs, runs, name, logo, ckey }: { configs: any[]; runs: any[]; name: (c: any) => string; logo: (c: any) => string | null; ckey: (c: any) => string }) {
  const swe = runs.filter((r) => r.benchmark_id.startsWith("swe_"));
  const pg = runs.filter((r) => r.benchmark_id.startsWith("pg_"));
  if (!swe.length && !pg.length) return null;
  const langs = Array.from(new Set(pg.map((r) => r.benchmark_id.split("_")[1]))).sort();
  const rows = configs.map((c) => {
    const k = ckey(c);
    const s = swe.filter((r) => ckey(r) === k);
    const p = pg.filter((r) => ckey(r) === k);
    const per: Record<string, number | null> = {};
    for (const l of langs) {
      const x = p.filter((r) => r.benchmark_id.split("_")[1] === l);
      per[l] = x.length ? x.filter((r) => r.correctness >= 1).length / x.length : null;
    }
    return { c, k, swe_n: new Set(s.map((r) => r.benchmark_id)).size, swe: s.length ? s.filter((r) => r.correctness >= 1).length / s.length : null,
      pg_n: new Set(p.map((r) => r.benchmark_id)).size, pg: p.length ? p.filter((r) => r.correctness >= 1).length / p.length : null, per };
  }).filter((r) => r.swe != null || r.pg != null);
  return (
    <Card className="mt-16" title="Public benchmarks"
      sub="SWE-bench: share of tasks the official harness marks resolved. Aider polyglot: share of exercises with every test passing. Averaged over iterations.">
      <Table rowKey={(r: any) => r.k} rows={rows} initialSort={{ key: swe.length ? "swe" : "pg", dir: -1 }} cols={[
        { key: "cfg", label: "Configuration", sort: (r: any) => name(r.c), render: (r: any) => <LogoName id={logo(r.c)} size={18}><b className="small">{name(r.c)}</b></LogoName> },
        ...(swe.length ? [{ key: "swe", label: "SWE-bench resolved", num: true, sort: (r: any) => r.swe ?? -1,
          render: (r: any) => r.swe == null ? "–" : <span><b>{fmtPct(r.swe, 1)}</b> <span className="muted tiny">of {r.swe_n}</span></span> }] : []),
        ...(pg.length ? [{ key: "pg", label: "Polyglot solved", num: true, sort: (r: any) => r.pg ?? -1,
          render: (r: any) => r.pg == null ? "–" : <span><b>{fmtPct(r.pg, 1)}</b> <span className="muted tiny">of {r.pg_n}</span></span> }] : []),
        ...langs.map((l) => ({ key: `pg_${l}`, label: LANG[l] || l, num: true, sort: (r: any) => r.per[l] ?? -1, render: (r: any) => r.per[l] == null ? "–" : fmtPct(r.per[l]) })),
      ]} />
    </Card>
  );
}

/** Artificial Analysis numbers for each profile's model, beside LLMDyno's measurements. */
export function AAReference({ configs, runs, labels, ckey }: { configs: any[]; runs: any[]; labels: any; ckey: (c: any) => string }) {
  const aa = useAA();
  const qc = useQueryClient();
  const toast = useToast();
  const d = aa.data;
  if (!d) return null;
  const profIds: string[] = Array.from(new Set(configs.map((c) => c.profile_id)));
  const setOverride = async (pid: string, slug: string) => {
    try {
      await api.put("/references/aa/override", { profile_id: pid, slug: slug || null });
      qc.invalidateQueries({ queryKey: keys.aa });
    } catch (e) {
      toast.err("Could not save the match", e);
    }
  };
  const attribution = <a href={d.attribution.url} target="_blank" rel="noreferrer">{d.attribution.text} <ExternalLink size={11} /></a>;
  if (!d.has_key || !d.models) {
    return (
      <Card className="mt-16" title="Public reference" sub={<>Add a free Artificial Analysis API key in <Link to="/settings">Settings</Link> to show each model's public
        intelligence index, output speed and price next to your results.</>} />
    );
  }
  const opts = [{ value: "", label: "Automatic match" }, ...(d.model_list || []).map((m: any) => ({ value: m.slug, label: `${m.name}${m.creator ? ` (${m.creator})` : ""}` }))];
  const rows = profIds.map((pid) => {
    const mine = configs.filter((c) => c.profile_id === pid);
    const prs = runs.filter((r) => r.profile_id === pid);
    return { pid, label: labels.profiles[pid], match: d.matches[pid], tps: median(mine.map((c) => c.decode_tps)), ttft: median(prs.map((r) => r.ttft_median_s)),
      correct: median(mine.map((c) => c.correctness)), k: ckey(mine[0]) };
  });
  return (
    <Card className="mt-16" title="Public reference" sub={<>Measured here vs published by Artificial Analysis. Local speeds depend on your hardware and settings; AA
      measures providers' APIs. {d.intelligence_index_version ? `Intelligence Index ${d.intelligence_index_version}. ` : ""}{attribution}</>}>
      <Table rowKey={(r: any) => r.pid} rows={rows} cols={[
        { key: "p", label: "Profile", sort: (r: any) => r.label?.name, render: (r: any) => <b className="small" style={{ display: "inline-block", minWidth: 170 }}>{r.label?.name || r.pid}</b> },
        { key: "m", label: "Artificial Analysis model", render: (r: any) => (
          <div className="row" style={{ gap: 6, minWidth: 300 }}>
            {r.match?.model ? <a href={r.match.model.url} target="_blank" rel="noreferrer" className="small">{r.match.model.name}</a> : <span className="muted small">no match</span>}
            {r.match && !r.match.manual && <Badge title="automatic name match; pick another if it is wrong">{Math.round(r.match.score * 100)}%</Badge>}
            <span style={{ marginLeft: "auto", maxWidth: 150 }}><Select value={r.match?.manual ? r.match.model.slug : ""} onChange={(v) => setOverride(r.pid, v)} options={opts} aria-label="Choose the matching model" /></span>
          </div>) },
        { key: "ii", label: "Intelligence", num: true, sort: (r: any) => r.match?.model?.intelligence_index ?? -1, render: (r: any) => fmtNum(r.match?.model?.intelligence_index, 1) },
        { key: "c", label: "Correct here", num: true, sort: (r: any) => r.correct ?? -1, render: (r: any) => fmtPct(r.correct) },
        { key: "tps", label: "Output tok/s here", num: true, sort: (r: any) => r.tps ?? -1, render: (r: any) => fmtNum(r.tps, 1) },
        { key: "aatps", label: "AA tok/s", num: true, sort: (r: any) => r.match?.model?.output_tps ?? -1, render: (r: any) => fmtNum(r.match?.model?.output_tps, 1) },
        { key: "ttft", label: "TTFT here", num: true, sort: (r: any) => r.ttft ?? 99, render: (r: any) => r.ttft != null ? `${r.ttft.toFixed(2)} s` : "–" },
        { key: "aattft", label: "AA TTFT", num: true, sort: (r: any) => r.match?.model?.ttft_s ?? 99, render: (r: any) => r.match?.model?.ttft_s != null ? `${r.match.model.ttft_s.toFixed(2)} s` : "–" },
        { key: "price", label: "AA price (3:1)", num: true, sort: (r: any) => r.match?.model?.price_blended ?? 1e9,
          render: (r: any) => r.match?.model?.price_blended != null ? <span title="per million tokens: 3 parts input, 1 part output">{fmtUsd(r.match.model.price_blended)}</span> : "–" },
      ]} />
    </Card>
  );
}

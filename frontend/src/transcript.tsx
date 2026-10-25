// Harness-neutral transcript: built from the proxy's transcript.jsonl events (requests, streamed blocks, responses).
import { diffLines } from "diff";
import { AlertTriangle, ChevronRight, FileText, MessageSquare, Scissors, Sparkles, Terminal, Wrench } from "lucide-react";
import { memo, useEffect, useMemo, useRef, useState } from "react";
import { fmtDur, fmtTokens, fmtUsd } from "./format";
import { Badge, Code, Markdown } from "./ui";

export type TItem =
  | { k: "system"; key: string; text: string; tools: string[] }
  | { k: "user"; key: string; text: string; label?: string }
  | { k: "thinking"; key: string; text: string; live: boolean }
  | { k: "text"; key: string; text: string; live: boolean }
  | { k: "tool"; key: string; id?: string; name: string; args: string; live: boolean; result?: string; isError?: boolean }
  | { k: "divider"; key: string; text: string }
  | { k: "error"; key: string; text: string }
  | { k: "turn"; key: string; seq: number; usage: any; timings: any; ttft?: number; wall?: number; cost?: number; status?: number }
  | { k: "aux"; key: string; seq: number; prompt: string; reply: string };

export type TState = {
  items: TItem[];
  mainConv?: string;
  mainTools?: boolean;                  // the main conversation offers tools (an agent loop, not a side chat)
  forcedMain?: string;
  raw: any[];                           // every event so far, to rebuild when the main conversation changes
  seqConv: Record<number, string>;
  blockIdx: Record<string, number>;      // `${seq}:${index}` -> item index
  live: { seq?: number; start?: number; chars: number; tps?: number };
  lastUsage?: any;
  turns: number;
  toolCalls: number;
  cost: number;
  outTokens: number;
  inTokens: number;
};

export const emptyState = (): TState => ({ items: [], raw: [], seqConv: {}, blockIdx: {}, live: { chars: 0 }, turns: 0, toolCalls: 0, cost: 0, outTokens: 0, inTokens: 0 });

function textOf(blocks: any[]) {
  return (blocks || []).filter((b) => b.type === "text").map((b) => b.text).join("\n");
}

/** Pure reducer over transcript events (mutates a copy-on-write state for speed with thousands of deltas). */
export function applyEvents(prev: TState, evs: any[]): TState {
  const s: TState = { ...prev, items: prev.items.slice(), blockIdx: { ...prev.blockIdx }, seqConv: { ...prev.seqConv }, live: { ...prev.live } };
  s.raw = prev.raw;
  for (const ev of evs) s.raw.push(ev);
  if (!s.mainConv && s.forcedMain) {
    s.mainConv = s.forcedMain;
    s.mainTools = true;
  }
  const push = (it: TItem) => s.items.push(it);
  for (const ev of evs) {
    const seq = ev.seq;
    if (ev.ev === "request") {
      s.seqConv[seq] = ev.conv;
      const offersTools = !!ev.new_conv && (ev.tools || []).length > 0;
      if (!s.mainConv) {
        s.mainConv = ev.conv;
        s.mainTools = offersTools;
      } else if (offersTools && !s.mainTools && ev.conv !== s.mainConv) {
        // the agent's real conversation started after a side chat (OpenCode asks for a session title first):
        // rebuild everything with the tool-using conversation as the main one
        return applyEvents({ ...emptyState(), forcedMain: ev.conv }, s.raw);
      }
      if (ev.conv !== s.mainConv) {
        const prompt = (ev.new || []).filter((m: any) => m.role === "user").map((m: any) => textOf(m.blocks)).join("\n");
        if (ev.new_conv || prompt) push({ k: "aux", key: `aux${seq}`, seq, prompt, reply: "" });
        continue;
      }
      if (ev.new_conv && ev.system) push({ k: "system", key: `sys${seq}`, text: ev.system, tools: ev.tools || [] });
      if (ev.reset) push({ k: "divider", key: `div${seq}`, text: `Context compacted or rewritten · kept ${ev.kept} of the earlier messages` });
      for (const m of ev.new || []) {
        if (m.role === "assistant") continue;               // already shown from the streamed response
        for (const b of m.blocks || []) {
          if (b.type === "tool_result") {
            let idx = -1;
            for (let i = s.items.length - 1; i >= 0; i--) {
              const it = s.items[i];
              if (it.k === "tool" && it.result === undefined && (!b.id || !it.id || it.id === b.id)) {
                idx = i;
                if (!b.id || it.id === b.id) break;
              }
            }
            if (idx >= 0) {
              const it = s.items[idx] as any;
              s.items[idx] = { ...it, result: b.text ?? "", isError: !!b.is_error };
            } else push({ k: "tool", key: `res${seq}-${s.items.length}`, name: b.name || "tool result", args: "", live: false, result: b.text ?? "", isError: !!b.is_error });
          } else if (b.type === "text" && b.text?.trim() && m.role === "user") {
            push({ k: "user", key: `u${seq}-${s.items.length}`, text: b.text, label: ev.reset ? "Context summary" : undefined });
          }
        }
      }
    } else if (ev.ev === "block_start" || ev.ev === "block_meta" || ev.ev === "delta") {
      if (s.seqConv[seq] && s.seqConv[seq] !== s.mainConv) {
        if (ev.ev === "delta") {
          const i = s.items.findIndex((x) => x.k === "aux" && (x as any).seq === seq);
          if (i >= 0) s.items[i] = { ...(s.items[i] as any), reply: (s.items[i] as any).reply + (ev.text || "") };
        }
        continue;
      }
      const key = `${seq}:${ev.index}`;
      let idx = s.blockIdx[key];
      if (idx === undefined) {
        const type = ev.type || "text";
        const it: TItem = type === "tool_call" ? { k: "tool", key: `b${key}`, id: ev.id, name: ev.name || "tool", args: "", live: true }
          : { k: type === "thinking" ? "thinking" : "text", key: `b${key}`, text: "", live: true } as TItem;
        s.items.push(it);
        idx = s.items.length - 1;
        s.blockIdx[key] = idx;
        if (s.live.seq !== seq) s.live = { seq, start: ev.t, chars: 0 };
      }
      const it = s.items[idx] as any;
      if (ev.ev === "block_meta" && ev.name) s.items[idx] = { ...it, name: ev.name };
      if (ev.ev === "delta" && ev.text) {
        s.items[idx] = it.k === "tool" ? { ...it, args: it.args + ev.text } : { ...it, text: it.text + ev.text };
        s.live.chars += ev.text.length;
        if (s.live.start) s.live.tps = s.live.chars / 3.6 / Math.max(ev.t - s.live.start, 0.25);
      }
    } else if (ev.ev === "response") {
      if (s.seqConv[seq] && s.seqConv[seq] !== s.mainConv) {
        const i = s.items.findIndex((x) => x.k === "aux" && (x as any).seq === seq);
        if (i >= 0) s.items[i] = { ...(s.items[i] as any), reply: textOf(ev.blocks) || (s.items[i] as any).reply };
        continue;
      }
      // finalise streamed blocks with the authoritative content (or create them for non-streamed replies)
      const streamed = Object.keys(s.blockIdx).filter((k) => k.startsWith(`${seq}:`)).map((k) => s.blockIdx[k]).sort((a, b) => a - b);
      (ev.blocks || []).forEach((b: any, bi: number) => {
        const idx = streamed[bi];
        if (idx === undefined) {
          const it: TItem = b.type === "tool_call" ? { k: "tool", key: `f${seq}-${bi}`, id: b.id, name: b.name || "tool", args: b.args || "", live: false }
            : { k: b.type === "thinking" ? "thinking" : "text", key: `f${seq}-${bi}`, text: b.text || "", live: false } as TItem;
          if ((it as any).text !== "" || it.k === "tool") s.items.push(it);
          return;
        }
        const it = s.items[idx] as any;
        if (it.k === "tool" && b.type === "tool_call") s.items[idx] = { ...it, name: it.name === "tool" && b.name ? b.name : it.name, id: it.id || b.id, args: b.args || it.args };
        else if ((it.k === "text" || it.k === "thinking") && b.text && b.text.length >= it.text.length) s.items[idx] = { ...it, text: b.text };
      });
      for (const k of Object.keys(s.blockIdx)) {
        if (!k.startsWith(`${seq}:`)) continue;
        const idx = s.blockIdx[k];
        const it = s.items[idx] as any;
        s.items[idx] = { ...it, live: false };
      }
      if (ev.error) push({ k: "error", key: `err${seq}`, text: `HTTP ${ev.status}: ${ev.error}` });
      push({ k: "turn", key: `t${seq}`, seq, usage: ev.usage, timings: ev.timings, ttft: ev.ttft_s, wall: ev.wall_s, cost: ev.cost_usd, status: ev.status });
      s.turns += 1;
      s.toolCalls += (ev.blocks || []).filter((b: any) => b.type === "tool_call").length;
      s.cost += ev.cost_usd || 0;
      if (ev.usage) {
        s.lastUsage = ev.usage;
        s.outTokens += ev.usage.output || 0;
        s.inTokens += ev.usage.input || 0;
      } else if (ev.timings) {
        s.lastUsage = { input: (ev.timings.prompt_n || 0) + (ev.timings.cache_n || 0), cached: ev.timings.cache_n, output: ev.timings.predicted_n };
        s.outTokens += ev.timings.predicted_n || 0;
        s.inTokens += (ev.timings.prompt_n || 0) + (ev.timings.cache_n || 0);
      }
      if (s.live.seq === seq) s.live = { chars: 0, tps: ev.timings?.predicted_per_second || (ev.usage?.output && ev.wall_s ? ev.usage.output / Math.max(ev.wall_s - (ev.ttft_s || 0), 0.1) : s.live.tps) };
    } else if (ev.ev === "error") {
      push({ k: "error", key: `e${seq}-${s.items.length}`, text: ev.text });
    }
  }
  return s;
}

/* ------------------------------------------------------------------ sticky open state per item type */
const stickyKey = (t: string) => `llmdyno-open-${t}`;
function getSticky(t: string, dflt: boolean) {
  try {
    const v = localStorage.getItem(stickyKey(t));
    return v === null ? dflt : v === "1";
  } catch {
    return dflt;
  }
}
function setSticky(t: string, v: boolean) {
  try {
    localStorage.setItem(stickyKey(t), v ? "1" : "0");
  } catch {
    /* unavailable */
  }
}
/** Opening or closing an item makes later items of the same type start that way; earlier ones keep their state. */
function useSticky(type: string, dflt: boolean, live = false) {
  const [open, setOpen] = useState(() => live || getSticky(type, dflt));
  return [open, (v: boolean) => { setOpen(v); setSticky(type, v); }] as const;
}

function parseArgs(a: string) {
  try {
    return JSON.parse(a);
  } catch {
    return null;
  }
}

function toolView(name: string, raw: string) {
  const a = parseArgs(raw);
  const n = name.toLowerCase();
  if (a && typeof a === "object") {
    const path = a.path || a.filePath || a.file_path || a.filename || a.absolute_path || a.target_file;
    const cmd = a.command ?? a.cmd ?? a.script;
    const content = a.content ?? a.file_text ?? a.contents;
    const oldS = a.old_string ?? a.oldText ?? a.old_str ?? a.oldString;
    const newS = a.new_string ?? a.newText ?? a.new_str ?? a.newString;
    if (cmd !== undefined) return { kind: "shell", subject: Array.isArray(cmd) ? cmd.join(" ") : String(cmd), body: Array.isArray(cmd) ? cmd.join(" ") : String(cmd) };
    if (path && oldS !== undefined && newS !== undefined) return { kind: "diff", subject: path, old: String(oldS), new: String(newS) };
    if (path && Array.isArray(a.edits)) return { kind: "edits", subject: path, edits: a.edits };
    if (path && content !== undefined) return { kind: "write", subject: path, body: String(content), path };
    if (typeof a.input === "string" && a.input.includes("*** Begin Patch")) return { kind: "patch", subject: (a.input.match(/\*\*\* (?:Update|Add|Delete) File: (.+)/) || [])[1] || "patch", body: a.input };
    if (path) return { kind: "json", subject: path, body: JSON.stringify(a, null, 2) };
    const first = Object.values(a).find((v) => typeof v === "string") as string | undefined;
    return { kind: "json", subject: first ? first.slice(0, 120) : "", body: JSON.stringify(a, null, 2) };
  }
  if (raw.includes("*** Begin Patch")) return { kind: "patch", subject: "patch", body: raw };
  if (n.includes("shell") || n.includes("bash") || n.includes("exec")) return { kind: "shell", subject: raw.split("\n")[0], body: raw };
  return { kind: "raw", subject: raw.split("\n")[0].slice(0, 120), body: raw };
}

function DiffView({ oldS, newS }: { oldS: string; newS: string }) {
  const parts = useMemo(() => diffLines(oldS, newS), [oldS, newS]);
  return (
    <pre className="code" style={{ padding: "6px 0" }}>
      {parts.map((p, i) => p.value.replace(/\n$/, "").split("\n").map((line, j) => (
        <span key={`${i}-${j}`} className={`diff-line ${p.added ? "diff-add" : p.removed ? "diff-del" : ""}`}>{p.added ? "+ " : p.removed ? "- " : "  "}{line}</span>
      )))}
    </pre>
  );
}

function PatchView({ text }: { text: string }) {
  return (
    <pre className="code" style={{ padding: "6px 0" }}>
      {text.split("\n").map((line, i) => (
        <span key={i} className={`diff-line ${line.startsWith("+") ? "diff-add" : line.startsWith("-") ? "diff-del" : line.startsWith("@@") || line.startsWith("***") ? "diff-hunk" : ""}`}>{line || " "}</span>
      ))}
    </pre>
  );
}

const ToolCard = memo(function ToolCard({ it }: { it: Extract<TItem, { k: "tool" }> }) {
  const v = toolView(it.name, it.args);
  const [open, setOpen] = useSticky(`tool-${v.kind}`, false, false);
  const [full, setFull] = useState(false);
  const Ico = v.kind === "shell" ? Terminal : v.kind === "write" || v.kind === "diff" || v.kind === "edits" || v.kind === "patch" ? FileText : Wrench;
  const res = it.result ?? "";
  const shown = full ? res : res.slice(0, 5000);
  return (
    <div className="t-item">
      <div className="t-head" onClick={() => setOpen(!open)}>
        <ChevronRight size={14} className={`caret ${open ? "open" : ""}`} />
        <Ico size={13} />
        <span className="name">{it.name}</span>
        <span className="subject">{v.subject}</span>
        <span className="meta">
          {it.live && <Badge tone="info" dot live>writing</Badge>}
          {!it.live && it.result === undefined && <Badge tone="info" dot live>running</Badge>}
          {it.isError && <Badge tone="danger">error</Badge>}
          {it.result !== undefined && !it.isError && <span>{res.split("\n").length} lines out</span>}
        </span>
      </div>
      {open && (
        <div className="t-body col" style={{ gap: 8 }}>
          {v.kind === "shell" && <Code code={`$ ${v.body}`} lang="bash" wrap />}
          {v.kind === "write" && <Code code={v.body!} path={v.path} lineNumbers maxHeight={420} />}
          {v.kind === "diff" && <DiffView oldS={(v as any).old} newS={(v as any).new} />}
          {v.kind === "edits" && (v as any).edits.map((e: any, i: number) => <DiffView key={i} oldS={String(e.oldText ?? e.old_string ?? e.old_str ?? "")} newS={String(e.newText ?? e.new_string ?? e.new_str ?? "")} />)}
          {v.kind === "patch" && <PatchView text={v.body!} />}
          {(v.kind === "json" || v.kind === "raw") && it.args && <Code code={v.body!} lang={v.kind === "json" ? "json" : "plaintext"} wrap />}
          {it.result !== undefined && (
            <div>
              <div className="tiny muted mb-8" style={{ marginBottom: 4 }}>Result</div>
              <pre className="code wrap" style={{ maxHeight: 360, background: it.isError ? "var(--danger-soft)" : undefined }}>{shown || "(empty)"}</pre>
              {res.length > 5000 && !full && <button className="btn xs ghost mt-8" onClick={() => setFull(true)}>Show all {res.length.toLocaleString()} characters</button>}
            </div>
          )}
        </div>
      )}
    </div>
  );
});

const Thinking = memo(function Thinking({ it }: { it: Extract<TItem, { k: "thinking" }> }) {
  const [open, setOpen] = useSticky("thinking", false);
  const words = it.text.trim().split(/\s+/).length;
  return (
    <div className="t-item thinking">
      <div className="t-head" onClick={() => setOpen(!open)}>
        <ChevronRight size={14} className={`caret ${open ? "open" : ""}`} />
        <Sparkles size={13} />
        <span className="name">Thinking</span>
        {!open && <span className="subject" style={{ fontFamily: "var(--font)" }}>{it.text.slice(-160).replace(/\s+/g, " ")}</span>}
        <span className="meta">{it.live ? <Badge tone="info" dot live>thinking</Badge> : `${words} words`}</span>
      </div>
      {open && <div className="t-body"><div className={`small text-2 ${it.live ? "cursor-blink" : ""}`} style={{ whiteSpace: "pre-wrap" }}>{it.text}</div></div>}
    </div>
  );
});

function SystemItem({ it }: { it: Extract<TItem, { k: "system" }> }) {
  const [open, setOpen] = useSticky("system", false);
  return (
    <div className="t-item">
      <div className="t-head" onClick={() => setOpen(!open)}>
        <ChevronRight size={14} className={`caret ${open ? "open" : ""}`} /><Wrench size={13} />
        <span className="name">System prompt</span>
        <span className="subject" style={{ fontFamily: "var(--font)" }}>{fmtTokens(it.text.length / 3.6)} tokens · {it.tools.length} tools: {it.tools.join(", ")}</span>
      </div>
      {open && <div className="t-body"><pre className="code wrap" style={{ maxHeight: 420 }}>{it.text}</pre></div>}
    </div>
  );
}

function Aux({ it }: { it: Extract<TItem, { k: "aux" }> }) {
  const [open, setOpen] = useSticky("aux", false);
  return (
    <div className="t-item" style={{ opacity: 0.85 }}>
      <div className="t-head" onClick={() => setOpen(!open)}>
        <ChevronRight size={14} className={`caret ${open ? "open" : ""}`} /><MessageSquare size={13} />
        <span className="name">Side request</span>
        <span className="subject" style={{ fontFamily: "var(--font)" }}>{(it.reply || it.prompt).slice(0, 120)}</span>
        <span className="meta">title, summary or sub-agent call</span>
      </div>
      {open && <div className="t-body col"><pre className="code wrap small">{it.prompt}</pre>{it.reply && <Markdown text={it.reply} />}</div>}
    </div>
  );
}

function Turn({ it, ctx }: { it: Extract<TItem, { k: "turn" }>; ctx?: number }) {
  const u = it.usage || (it.timings ? { input: (it.timings.prompt_n || 0) + (it.timings.cache_n || 0), cached: it.timings.cache_n, output: it.timings.predicted_n } : null);
  const tps = it.timings?.predicted_per_second || (u?.output && it.wall ? u.output / Math.max(it.wall - (it.ttft || 0), 0.1) : null);
  return (
    <div className="tiny muted row wrap" style={{ gap: 12, padding: "0 4px" }}>
      <span>turn {it.seq}</span>
      {u && <span>{fmtTokens(u.input)} in{u.cached ? ` (${Math.round((u.cached / Math.max(u.input, 1)) * 100)}% cached)` : ""} · {fmtTokens(u.output)} out</span>}
      {u && ctx ? <span>context {Math.round(((u.input + (u.output || 0)) / ctx) * 100)}%</span> : null}
      {tps ? <span>{tps.toFixed(1)} tok/s</span> : null}
      {it.ttft ? <span>TTFT {it.ttft.toFixed(2)}s</span> : null}
      {it.wall ? <span>{fmtDur(it.wall)}</span> : null}
      {it.cost ? <span>{fmtUsd(it.cost)}</span> : null}
      {it.status && it.status >= 400 ? <Badge tone="danger">HTTP {it.status}</Badge> : null}
    </div>
  );
}

export function Transcript({ state, ctx, follow, filter }: { state: TState; ctx?: number; follow: boolean; filter: "all" | "messages" | "tools" }) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (follow) end.current?.scrollIntoView({ block: "end" });
  }, [state.items.length, state.live.chars, follow]);
  const items = state.items.filter((it) => filter === "all" || (filter === "tools" ? it.k === "tool" : ["user", "text", "thinking", "error", "divider"].includes(it.k)));
  if (!items.length) return <div className="empty"><div className="ico"><MessageSquare size={20} /></div><h3>No model traffic yet</h3><p>The transcript fills in as soon as the agent sends its first request.</p></div>;
  return (
    <div className="transcript">
      {items.map((it) => {
        switch (it.k) {
          case "system": return <SystemItem key={it.key} it={it} />;
          case "user": return <div key={it.key} className="t-item user"><div className="t-text"><div className="tiny muted mb-8" style={{ marginBottom: 4 }}>{it.label || "Prompt"}</div><Markdown text={it.text.length > 20000 ? it.text.slice(0, 20000) + "\n\n…" : it.text} /></div></div>;
          case "thinking": return <Thinking key={it.key} it={it} />;
          case "text": return it.text.trim() || it.live ? <div key={it.key} className="t-item"><div className={`t-text ${it.live ? "cursor-blink" : ""}`}><Markdown text={it.text} /></div></div> : null;
          case "tool": return <ToolCard key={it.key} it={it} />;
          case "divider": return <div key={it.key} className="t-divider"><Scissors size={12} /> {it.text}</div>;
          case "error": return <div key={it.key} className="t-item error"><div className="t-text row"><AlertTriangle size={14} className="danger" /><span className="small">{it.text}</span></div></div>;
          case "turn": return <Turn key={it.key} it={it} ctx={ctx} />;
          case "aux": return <Aux key={it.key} it={it} />;
          default: return null;
        }
      })}
      <div ref={end} />
    </div>
  );
}

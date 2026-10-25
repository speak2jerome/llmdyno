// The LLMDyno mascot: a pixel dinosaur with a rocket strapped to its back, on a treadmill.
// Sprites come from scripts/make_logo.py (dyno-sprite.ts); this file only picks layers and animates them.
//
// States: idle (blinks), running (sprints, booster lit), warmup (quick profile test: jogs, booster off),
// judging (sits on the podium, thinking), celebrate (a plan finished: hops in confetti) and panic (turns red,
// freezes mid-frame, then snaps back to the starting pose).
import { useEffect, useMemo, useRef, useState } from "react";
import { DYNO_LAYERS, DYNO_PALETTE, DYNO_TILE } from "./dyno-sprite";
import { useJobs } from "./queries";
import { hub } from "./ws";

export type DynoState = "idle" | "running" | "warmup" | "judging" | "celebrate" | "panic";

type Pose = { layers: [string, string?][]; dino?: string };
// [layer, animation class]
const POSES: Record<Exclude<DynoState, "panic">, Pose> = {
  idle: { layers: [["stars"], ["mill"], ["screen_off"], ["belt0"], ["body"], ["eye", "dy-eye"], ["arm_grip"], ["legs_stand"], ["rocket"]] },
  running: {
    layers: [["stars"], ["mill"], ["screen_on"], ["belt2", "dy-f3a"], ["belt1", "dy-f3b"], ["belt0", "dy-f3c"], ["body"], ["eye", "dy-eye"], ["arm_grip"],
      ["legs_a", "dy-f4a"], ["legs_p1", "dy-f4b"], ["legs_b", "dy-f4c"], ["legs_p2", "dy-f4d"], ["rocket"], ["flame_a", "dy-fl-a"], ["flame_b", "dy-fl-b"]],
  },
  warmup: {
    layers: [["stars"], ["mill"], ["screen_on"], ["belt2", "dy-f3a"], ["belt1", "dy-f3b"], ["belt0", "dy-f3c"], ["body"], ["eye", "dy-eye"], ["arm_grip"],
      ["legs_a", "dy-f4a"], ["legs_p1", "dy-f4b"], ["legs_b", "dy-f4c"], ["legs_p2", "dy-f4d"], ["rocket"], ["puff", "dy-puff"]],
  },
  judging: {
    layers: [["stars"], ["podium"], ["body"], ["eye", "dy-eye"], ["arm_rest"], ["legs_sit"], ["rocket"], ["bubble"], ["dot0", "dy-d0"], ["dot1", "dy-d1"], ["dot2", "dy-d2"]],
  },
  celebrate: {
    layers: [["stars"], ["mill"], ["screen_on"], ["belt0"], ["body"], ["eye"], ["arm_rest"], ["legs_stand"], ["rocket"],
      ["flame_a", "dy-fl-a"], ["flame_b", "dy-fl-b"], ["confetti_a", "dy-f2a"], ["confetti_b", "dy-f2b"]],
    dino: "dy-hop",
  },
};
// these layers move with the dinosaur when it hops
const DINO = new Set(["body", "eye", "arm_grip", "arm_rest", "legs_stand", "legs_a", "legs_p1", "legs_b", "legs_p2", "legs_sit", "rocket", "flame_a", "flame_b", "puff"]);

/** Panic palette: every colour mapped by brightness onto a red ramp, so the sprite stays readable. */
const RED_RAMP = ["#2a070b", "#5c0f16", "#991b1b", "#dc2626", "#f87171", "#fecaca"];
function toRed(hex: string) {
  const n = parseInt(hex.slice(1), 16);
  const lum = (0.3 * ((n >> 16) & 255) + 0.59 * ((n >> 8) & 255) + 0.11 * (n & 255)) / 255;
  return RED_RAMP[Math.min(RED_RAMP.length - 1, Math.floor(lum * RED_RAMP.length))];
}
const RED_PALETTE = Object.fromEntries(Object.entries(DYNO_PALETTE).map(([k, v]) => [k, toRed(v)]));

function layerRects(name: string, pal: Record<string, string>) {
  return (DYNO_LAYERS[name] || []).map(([x, y, w, c], i) => <rect key={i} x={x} y={y} width={w} height={1} fill={pal[c]} />);
}

function poseSvg(state: DynoState, red: boolean) {
  const pal = red ? RED_PALETTE : DYNO_PALETTE;
  const pose = POSES[state === "panic" ? "idle" : state];
  // one frame of each animation: the first of every alternating pair
  const names = pose.layers.map(([n]) => n).filter((n) => !/^(belt[12]|legs_(b|p1|p2)|flame_b|dot2|confetti_b)$/.test(n));
  const rects = names.flatMap((n) => (DYNO_LAYERS[n] || []).map(([x, y, w, c]) => `<rect x="${x}" y="${y}" width="${w}" height="1" fill="${pal[c]}"/>`));
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" shape-rendering="crispEdges"><path d="${DYNO_TILE}" fill="${pal.bg}"/>${rects.join("")}</svg>`;
}

/** A static picture of a state, as a data URL (used for the browser tab icon). */
export function dynoDataUrl(state: DynoState) {
  return "data:image/svg+xml," + encodeURIComponent(poseSvg(state, state === "panic"));
}

export function Dyno({ state = "idle", size = 40, title, className }: { state?: DynoState; size?: number; title?: string; className?: string }) {
  // panic: freeze whatever was on screen, then go back to the starting pose; stay red for a while
  const [shown, setShown] = useState<Exclude<DynoState, "panic">>(state === "panic" ? "idle" : state);
  const [frozen, setFrozen] = useState(false);
  const [red, setRed] = useState(state === "panic");
  const [hop, setHop] = useState(0);
  useEffect(() => {
    if (state !== "panic") {
      setFrozen(false);
      setRed(false);
      setShown(state);
      return;
    }
    setRed(true);
    setFrozen(true);
    const t = setTimeout(() => {
      setFrozen(false);
      setShown("idle");
    }, 1400);
    return () => clearTimeout(t);
  }, [state]);
  const pal = red ? RED_PALETTE : DYNO_PALETTE;
  const pose = POSES[shown];
  const layers = useMemo(() => pose.layers.map(([n, anim]) => ({ n, anim, rects: layerRects(n, pal) })), [pose, pal]);
  const back = layers.filter((l) => !DINO.has(l.n));
  const dino = layers.filter((l) => DINO.has(l.n));
  const label = title || { idle: "LLMDyno is idle", running: "Benchmark running", warmup: "Quick test running", judging: "Being judged", celebrate: "Plan finished", panic: "Stopped" }[state];
  return (
    <svg viewBox="0 0 48 48" width={size} height={size} shapeRendering="crispEdges" role="img" aria-label={label}
      className={["dyno", frozen && "dy-frozen", red && "dy-red", `dy-${shown}`, className].filter(Boolean).join(" ")}
      onMouseEnter={() => shown === "idle" && setHop((h) => h + 1)}>
      <title>{label}</title>
      <path d={DYNO_TILE} fill={pal.bg} />
      {back.filter((l) => !["confetti_a", "confetti_b", "bubble", "dot0", "dot1", "dot2"].includes(l.n)).map((l) => <g key={l.n} className={l.anim}>{l.rects}</g>)}
      <g key={hop} className={pose.dino || (hop ? "dy-hop-once" : undefined)}>
        {dino.map((l) => <g key={l.n} className={l.anim}>{l.rects}</g>)}
      </g>
      {back.filter((l) => ["confetti_a", "confetti_b", "bubble", "dot0", "dot1", "dot2"].includes(l.n)).map((l) => <g key={l.n} className={l.anim}>{l.rects}</g>)}
    </svg>
  );
}

/** The app-wide mascot state, derived from background jobs and panic events. */
export function useDynoState(): { state: DynoState; detail: string } {
  const jobs = useJobs();
  const [panicAt, setPanicAt] = useState(0);
  const [celebrateAt, setCelebrateAt] = useState(0);
  const [, tick] = useState(0);
  const seen = useRef<Record<string, string>>({});
  useEffect(() => {
    const onPanic = () => setPanicAt(Date.now());
    window.addEventListener("llmdyno:panic", onPanic);
    const off = hub.on("system", (m) => m.kind === "panic" && onPanic());
    return () => {
      window.removeEventListener("llmdyno:panic", onPanic);
      off();
    };
  }, []);
  useEffect(() => {
    // a plan job that we saw running and that is now done: celebrate
    for (const j of jobs) {
      const prev = seen.current[j.id];
      if (j.kind === "plan" && prev && ["queued", "running"].includes(prev) && j.status === "done") setCelebrateAt(Date.now());
      seen.current[j.id] = j.status;
    }
  }, [jobs]);
  const now = Date.now();
  const until = Math.max(panicAt + 7000, celebrateAt + 5000);
  useEffect(() => {
    if (until <= now) return;
    const t = setTimeout(() => tick((x) => x + 1), until - now + 20);
    return () => clearTimeout(t);
  }, [until, now]);
  const active = (k: string) => jobs.find((j) => j.kind === k && j.status === "running");
  if (now - panicAt < 7000) return { state: "panic", detail: "Everything stopped" };
  const plan = active("plan");
  if (plan) return { state: "running", detail: plan.detail ? `Running · ${plan.detail}` : "Running" };
  if (now - celebrateAt < 5000) return { state: "celebrate", detail: "Plan finished" };
  const judge = active("judge");
  if (judge) return { state: "judging", detail: judge.detail ? `Judging · ${judge.detail.split(" · ")[0]}` : "Judging" };
  if (active("smoke")) return { state: "warmup", detail: "Quick test" };
  return { state: "idle", detail: "" };
}

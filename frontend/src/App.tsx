import {
  Activity, BarChart3, Boxes, Cloud, Cpu, FlaskConical, Gavel, Home, Layers, ListChecks, Monitor, Moon, PlayCircle, Settings2,
  SlidersHorizontal, Sun, Wrench,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { api } from "./api";
import { JobsPopover } from "./components";
import { Dyno, dynoDataUrl, useDynoState } from "./dyno";
import { PanicButton } from "./panic";
import { cls, fmtMib } from "./format";
import Benchmarks, { BenchmarkEditor } from "./pages/Benchmarks";
import Harnesses from "./pages/Harnesses";
import HomePage from "./pages/Home";
import Jobs from "./pages/Jobs";
import Judging from "./pages/Judging";
import Models from "./pages/Models";
import Onboarding from "./pages/Onboarding";
import PlanDetail from "./pages/PlanDetail";
import PlanNew from "./pages/PlanNew";
import Plans from "./pages/Plans";
import ProfileEditor from "./pages/ProfileEditor";
import Profiles from "./pages/Profiles";
import Providers from "./pages/Providers";
import Results from "./pages/Results";
import RunDetail from "./pages/RunDetail";
import Settings from "./pages/Settings";
import Setup from "./pages/Setup";
import { useDeps, useJobs, useLiveInvalidation, useSettings, useSpecs } from "./queries";
import { useTheme } from "./theme";
import { useConnected } from "./ws";

function NavItem({ to, icon, label, badge, warn }: { to: string; icon: React.ReactNode; label: string; badge?: number; warn?: boolean }) {
  return (
    <NavLink to={to} end={to === "/"} className={({ isActive }) => cls("nav-link", isActive && "active")}>
      {icon}
      <span>{label}</span>
      {badge ? <span className="count">{badge}</span> : warn ? <span className="dot-warn" title="needs attention" /> : null}
    </NavLink>
  );
}

function GpuMeter() {
  const { data } = useSpecs();
  // one nvidia-smi query every 4 s while the tab is visible; the full system scan is far too slow for a live meter
  const live = useQuery({ queryKey: ["gpu-live"], queryFn: () => api.get<any[]>("/system/gpu"), refetchInterval: 4000, refetchIntervalInBackground: false });
  const g = data?.summary?.primary_gpu;
  if (!g) return null;
  const now = (live.data || []).find((x: any) => x.name === g.name) || (live.data || [])[0];
  const used = now?.vram_used_mib ?? g.vram_used_mib ?? 0;
  const total = now?.vram_total_mib ?? g.vram_total_mib ?? 1;
  const frac = used / (total || 1);
  return (
    <div className="card" style={{ padding: "10px 12px" }} title={now ? `VRAM in use now${now.util_pct != null ? ` · GPU ${now.util_pct}% busy` : ""}${now.power_w != null ? ` · ${Math.round(now.power_w)} W` : ""}` : "VRAM in use when the system was last scanned"}>
      <div className="row small" style={{ justifyContent: "space-between" }}>
        <span className="row" style={{ gap: 6 }}><Cpu size={13} /> <span className="ellipsis" style={{ maxWidth: 120 }}>{g.name.replace("NVIDIA GeForce ", "")}</span></span>
        <span className="muted tnum">{fmtMib(used)} / {fmtMib(total, 0)}</span>
      </div>
      <div className={cls("progress", frac > 0.9 ? "danger" : frac > 0.75 ? "warn" : "")} style={{ marginTop: 6 }}>
        <div style={{ width: `${frac * 100}%` }} />
      </div>
    </div>
  );
}

/** The release this UI was built from; flags a stale build when the server runs a different version. */
function VersionTag() {
  const health = useQuery({ queryKey: ["health"], queryFn: () => api.get<any>("/health"), staleTime: 60_000 });
  const server = health.data?.version;
  const stale = server && server !== __APP_VERSION__;
  return (
    <NavLink to="/settings#about" className={cls("version-tag", stale && "warn")}
      title={stale ? `The UI was built from ${__APP_VERSION__} but the server runs ${server}: rebuild the UI (npm run build in frontend/)` : `LLMDyno ${__APP_VERSION__}`}>
      v{__APP_VERSION__}{stale ? ` · server ${server}` : ""}
    </NavLink>
  );
}

function ThemeSwitch() {
  const { pref, setPref } = useTheme();
  const next = pref === "light" ? "dark" : pref === "dark" ? "system" : "light";
  const Ico = pref === "light" ? Sun : pref === "dark" ? Moon : Monitor;
  return (
    <button className="btn ghost sm" onClick={() => setPref(next)} title={`Theme: ${pref} (click for ${next})`} aria-label="Switch theme">
      <Ico size={14} /> {pref === "system" ? "System" : pref === "light" ? "Light" : "Dark"}
    </button>
  );
}

export default function App() {
  useLiveInvalidation();
  const settings = useSettings();
  const deps = useDeps();
  const jobs = useJobs();
  const connected = useConnected();
  const dyno = useDynoState();
  // the tab icon and title follow the mascot, so a running benchmark is visible from other tabs
  useEffect(() => {
    let link = document.querySelector<HTMLLinkElement>("link[rel=icon]");
    if (!link) {
      link = document.createElement("link");
      link.rel = "icon";
      document.head.appendChild(link);
    }
    link.type = "image/svg+xml";
    link.href = dyno.state === "idle" ? "/favicon.svg" : dynoDataUrl(dyno.state);
    document.title = dyno.detail ? `${dyno.detail} · LLMDyno` : "LLMDyno";
  }, [dyno.state, dyno.detail]);
  const loc = useLocation();
  const [showOnboarding, setShowOnboarding] = useState(false);
  useEffect(() => {
    if (settings.data && settings.data.onboarded === false) setShowOnboarding(true);
  }, [settings.data]);
  useEffect(() => {
    document.querySelector(".main")?.scrollTo({ top: 0 });
  }, [loc.pathname]);
  const active = jobs.filter((j) => ["queued", "running"].includes(j.status));
  const runningPlans = active.filter((j) => j.kind === "plan").length;
  const setupWarn = (deps.data || []).some((d: any) => d.level === "required" && !d.ok);
  return (
    <div className="app">
      <nav className="sidebar" aria-label="Main">
        <NavLink to="/" className="brand" aria-label="LLMDyno overview">
          <Dyno state={dyno.state} size={40} />
          <div style={{ minWidth: 0 }}>
            <div className="brand-name">LLM<span className="dyno-word">Dyno</span></div>
            <div className={cls("brand-status", dyno.state === "panic" ? "stopped" : dyno.state !== "idle" && "live")}>{dyno.detail || "coding-agent benchmarks"}</div>
          </div>
        </NavLink>
        <NavItem to="/" icon={<Home size={16} />} label="Overview" />
        <NavItem to="/setup" icon={<Wrench size={16} />} label="Setup" warn={setupWarn} />
        <div className="nav-section">Configure</div>
        <NavItem to="/models" icon={<Boxes size={16} />} label="Models" />
        <NavItem to="/providers" icon={<Cloud size={16} />} label="Cloud providers" />
        <NavItem to="/profiles" icon={<SlidersHorizontal size={16} />} label="LLM profiles" />
        <NavItem to="/harnesses" icon={<Layers size={16} />} label="Harnesses" />
        <NavItem to="/benchmarks" icon={<FlaskConical size={16} />} label="Benchmarks" />
        <div className="nav-section">Evaluate</div>
        <NavItem to="/plans" icon={<PlayCircle size={16} />} label="Runs" badge={runningPlans} />
        <NavItem to="/judging" icon={<Gavel size={16} />} label="Judging" />
        <NavItem to="/results" icon={<BarChart3 size={16} />} label="Results" />
        <div className="nav-section">System</div>
        <NavItem to="/jobs" icon={<ListChecks size={16} />} label="Activity" badge={active.length} />
        <NavItem to="/settings" icon={<Settings2 size={16} />} label="Settings" />
        <div className="sidebar-footer">
          <PanicButton />
          <GpuMeter />
          <div className="row between">
            <ThemeSwitch />
            <JobsPopover />
          </div>
          {!connected && <div className="badge warn" style={{ justifyContent: "center" }}><Activity size={12} /> Reconnecting…</div>}
          <VersionTag />
        </div>
      </nav>
      <main className="main">
        <Routes>
          <Route path="/" element={<HomePage onOnboard={() => setShowOnboarding(true)} />} />
          <Route path="/setup" element={<Setup />} />
          <Route path="/models" element={<Models />} />
          <Route path="/profiles" element={<Profiles />} />
          <Route path="/profiles/new" element={<ProfileEditor />} />
          <Route path="/profiles/:id" element={<ProfileEditor />} />
          <Route path="/providers" element={<Providers />} />
          <Route path="/harnesses" element={<Harnesses />} />
          <Route path="/benchmarks" element={<Benchmarks />} />
          <Route path="/benchmarks/new" element={<BenchmarkEditor />} />
          <Route path="/benchmarks/:id/edit" element={<BenchmarkEditor />} />
          <Route path="/plans" element={<Plans />} />
          <Route path="/plans/new" element={<PlanNew />} />
          <Route path="/plans/:id" element={<PlanDetail />} />
          <Route path="/runs/:id" element={<RunDetail />} />
          <Route path="/judging" element={<Judging />} />
          <Route path="/results" element={<Results />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/settings" element={<Settings onOnboard={() => setShowOnboarding(true)} />} />
          <Route path="*" element={<div className="page"><h1>Page not found</h1><p className="muted mt-8">That address does not exist. <NavLink to="/">Go to the overview</NavLink>.</p></div>} />
        </Routes>
      </main>
      {showOnboarding && <Onboarding onClose={() => setShowOnboarding(false)} />}
    </div>
  );
}

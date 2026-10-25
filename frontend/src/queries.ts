// Data hooks: react-query for fetching, WebSocket events for invalidation and live job state.
import { QueryClient, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "./api";
import { hub, useTopic } from "./ws";

export const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 10_000, refetchOnWindowFocus: false, retry: 1 } },
});

export const keys = {
  specs: ["specs"], deps: ["deps"], settings: ["settings"], models: ["models"], profiles: ["profiles"],
  providers: ["providers"], vendors: ["vendors"], harnesses: ["harnesses"], benchmarks: ["benchmarks"], suites: ["suites"],
  plans: ["plans"], jobs: ["jobs"], sample: ["sample"],
};

export const useSpecs = () => useQuery({ queryKey: keys.specs, queryFn: () => api.get("/system/specs"), staleTime: 30_000 });
export const useDeps = () => useQuery({ queryKey: keys.deps, queryFn: () => api.get<any[]>("/system/deps"), staleTime: 15_000 });
export const useSettings = () => useQuery({ queryKey: keys.settings, queryFn: () => api.get("/settings") });
export const useModels = () => useQuery({ queryKey: keys.models, queryFn: () => api.get<any[]>("/models") });
export const useProfiles = () => useQuery({ queryKey: keys.profiles, queryFn: () => api.get<any[]>("/profiles") });
export const useProviders = () => useQuery({ queryKey: keys.providers, queryFn: () => api.get<any[]>("/providers") });
export const useVendors = () => useQuery({ queryKey: keys.vendors, queryFn: () => api.get<any[]>("/vendors"), staleTime: Infinity });
export const useHarnesses = () => useQuery({ queryKey: keys.harnesses, queryFn: () => api.get<any[]>("/harnesses") });
export const useBenchmarks = () => useQuery({ queryKey: keys.benchmarks, queryFn: () => api.get<any[]>("/benchmarks") });
export const useSuites = () => useQuery({ queryKey: keys.suites, queryFn: () => api.get<any[]>("/suites") });
export const usePlans = () => useQuery({ queryKey: keys.plans, queryFn: () => api.get<any[]>("/plans") });
export const useSample = () => useQuery({ queryKey: keys.sample, queryFn: () => api.get("/sample") });

/** Invalidate lists when the server reports changes, so every page stays current without polling. */
export function useLiveInvalidation() {
  const qc = useQueryClient();
  useEffect(() => {
    const offs = [
      hub.on("models", () => qc.invalidateQueries({ queryKey: keys.models })),
      hub.on("profiles", () => qc.invalidateQueries({ queryKey: keys.profiles })),
      hub.on("plans", () => qc.invalidateQueries({ queryKey: keys.plans })),
      hub.on("reviews", () => qc.invalidateQueries({ queryKey: ["results"] })),
      hub.on("jobs", (m) => {
        const j = m.data;
        if (!j || !["done", "failed", "cancelled"].includes(j.status)) return;
        const byKind: Record<string, string[][]> = {
          download: [keys.models, keys.deps], install: [keys.deps, keys.specs], build: [keys.harnesses, keys.deps],
          plan: [keys.plans, ["results"]], judge: [["results"], ["reviews"]], smoke: [keys.profiles], validate: [keys.benchmarks],
        };
        for (const k of byKind[j.kind] || []) qc.invalidateQueries({ queryKey: k });
      }),
      // after a reconnect (or dropped events) refetch everything on screen; inactive queries refetch when shown
      hub.onResync(() => qc.invalidateQueries()),
    ];
    return () => offs.forEach((o) => o());
  }, [qc]);
}

export type Job = {
  id: string; kind: string; title: string; ref: string; status: string; progress: number; detail: string; result: any;
  created_at: number; started_at?: number; ended_at?: number; log_tail?: string;
};

let jobStore: Record<string, Job> = {};
const jobListeners = new Set<() => void>();
let jobsLoaded = false;
function emitJobs() {
  jobListeners.forEach((l) => l());
}
hub.on("jobs", (m) => {
  const d = m.data;
  if (!d?.id) return;
  jobStore = { ...jobStore, [d.id]: { ...(jobStore[d.id] || {}), ...d } };
  emitJobs();
});
hub.onResync(() => {
  jobsLoaded = false;
  loadJobs();
});
async function loadJobs() {
  if (jobsLoaded) return;
  jobsLoaded = true;
  try {
    const list = await api.get<Job[]>("/jobs?limit=80");
    for (const j of list) jobStore[j.id] = { ...(jobStore[j.id] || {}), ...j };
    emitJobs();
  } catch {
    jobsLoaded = false;
  }
}

export function useJobs() {
  const [, force] = useState(0);
  useEffect(() => {
    const l = () => force((x) => x + 1);
    jobListeners.add(l);
    loadJobs();
    return () => {
      jobListeners.delete(l);
    };
  }, []);
  return Object.values(jobStore).sort((a, b) => b.created_at - a.created_at);
}

export function forgetFinishedJobs() {
  jobStore = Object.fromEntries(Object.entries(jobStore).filter(([, j]) => ["queued", "running"].includes(j.status)));
  emitJobs();
}

export function useJob(id?: string | null) {
  const all = useJobs();
  const [log, setLog] = useState<string[]>([]);
  useEffect(() => {
    setLog([]);
    if (!id) return;
    api.get(`/jobs/${id}`).then((j) => {
      jobStore = { ...jobStore, [id]: { ...(jobStore[id] || {}), ...j } };
      emitJobs();
      setLog((j.log || "").split("\n").filter(Boolean).slice(-800));
    }).catch(() => undefined);
  }, [id]);
  useTopic(id ? `job:${id}` : null, (m) => {
    if (m.kind === "log") setLog((l) => [...l.slice(-1200), m.data]);
  });
  return { job: id ? all.find((j) => j.id === id) : undefined, log };
}

/** The newest job matching kind/ref, live. */
export function useLatestJob(kind: string, ref?: string) {
  const all = useJobs();
  return all.find((j) => j.kind === kind && (ref === undefined || j.ref === ref));
}

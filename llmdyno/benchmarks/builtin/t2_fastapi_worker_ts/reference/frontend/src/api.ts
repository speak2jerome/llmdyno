export type Operation = "wordcount" | "uppercase" | "reverse_words" | "summary";
export type JobStatus = "queued" | "running" | "done" | "failed" | "cancelled";

export interface Job {
  id: number;
  text: string;
  operation: Operation;
  status: JobStatus;
  result: unknown;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export async function createJob(text: string, operation: Operation): Promise<Job> {
  const r = await fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, operation }),
  });
  return (await r.json()) as Job;
}

export async function getJob(id: number): Promise<Job> {
  return (await (await fetch(`/api/jobs/${id}`)).json()) as Job;
}

export async function listJobs(status?: JobStatus): Promise<Job[]> {
  const q = status ? `?status=${status}` : "";
  return (await (await fetch(`/api/jobs${q}`)).json()) as Job[];
}

import { createJob, getJob, Operation } from "./api.js";

const form = document.querySelector<HTMLFormElement>("#job-form")!;
const out = document.querySelector<HTMLPreElement>("#result")!;

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = (document.querySelector<HTMLTextAreaElement>("#text")!).value;
  const op = (document.querySelector<HTMLSelectElement>("#operation")!).value as Operation;
  let job = await createJob(text, op);
  while (job.status === "queued" || job.status === "running") {
    await new Promise((r) => setTimeout(r, 1000));
    job = await getJob(job.id);
  }
  out.textContent = JSON.stringify(job.result ?? job.error);
});

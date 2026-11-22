/**
 * A coding agent built with the OpenAI Agents SDK for TypeScript, ready to benchmark with LLMDyno:
 *
 *     h = llmdyno.node_harness("openai_agents_agent.ts:run", source="examples/agents/ts/openai_agents_agent.ts")
 *     llmdyno.bench(profile, "suite_quick", harnesses=h.id)
 *
 * node_harness() installs the PACKAGES below. It talks Chat Completions to LLMDyno's proxy, so it works with local and
 * cloud models alike; tracing to OpenAI is off (the sandbox is offline, and LLMDyno records the transcript itself).
 */
import { spawnSync } from "node:child_process";
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";

import { Agent, OpenAIChatCompletionsModel, run as runAgent, setTracingDisabled, tool } from "@openai/agents";
import OpenAI from "openai";
import { z } from "zod";

export const PACKAGES = ["@openai/agents@0.22.0", "openai@7.62.0", "zod@4.6.7"];

interface Task {
  prompt: string;
  model: string;
  baseUrl: string;
  apiKey: string;
  workspace: string;
  maxTokens?: number;
}

const instructions = (workspace: string) => `You are a careful coding agent working in ${workspace}. Use the tools to `
  + "look around, write the code, and run the tests or the program to check it. When the task is done, reply with a "
  + "short summary.";

function workspaceTools(root: string) {
  return [
    tool({
      name: "list_files",
      description: "List the files under a folder of the workspace ('.' for all of it).",
      parameters: z.object({ path: z.string() }),
      execute: async ({ path }) => readdirSync(resolve(root, path), { recursive: true, withFileTypes: true })
        .filter((e) => e.isFile() && !/(^|[\\/])(\.git|node_modules)([\\/]|$)/.test(relative(root, e.parentPath)))
        .map((e) => relative(root, resolve(e.parentPath, e.name)).replaceAll("\\", "/"))
        .sort().join("\n").slice(0, 20000) || "(empty)",
    }),
    tool({
      name: "read_file",
      description: "Read a text file of the workspace.",
      parameters: z.object({ path: z.string() }),
      execute: async ({ path }) => readFileSync(resolve(root, path), "utf8").slice(0, 50000),
    }),
    tool({
      name: "write_file",
      description: "Create or overwrite a file of the workspace with this content.",
      parameters: z.object({ path: z.string(), content: z.string() }),
      execute: async ({ path, content }) => {
        const file = resolve(root, path);
        mkdirSync(dirname(file), { recursive: true });
        writeFileSync(file, content, "utf8");
        return `wrote ${path} (${content.length} characters)`;
      },
    }),
    tool({
      name: "run_command",
      description: "Run a shell command in the workspace (tests, scripts, ls, …) and return its output.",
      parameters: z.object({ command: z.string() }),
      execute: async ({ command }) => {
        const r = spawnSync(command, { shell: true, cwd: root, encoding: "utf8", timeout: 600_000, maxBuffer: 2 ** 26 });
        return `exit ${r.status ?? "killed"}\n${r.stdout ?? ""}${r.stderr ?? ""}`.slice(-20000);
      },
    }),
  ];
}

export async function run(task: Task): Promise<string> {
  setTracingDisabled(true);
  const client = new OpenAI({ baseURL: task.baseUrl, apiKey: task.apiKey, timeout: 900_000, maxRetries: 2 });
  const agent = new Agent({
    name: "coder",
    instructions: instructions(task.workspace),
    tools: workspaceTools(task.workspace),
    model: new OpenAIChatCompletionsModel(client, task.model),
    modelSettings: { maxTokens: task.maxTokens },
  });
  const result = await runAgent(agent, task.prompt, { maxTurns: 60 });
  return String(result.finalOutput ?? "");
}

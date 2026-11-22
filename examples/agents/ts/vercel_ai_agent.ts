/**
 * A coding agent built with the Vercel AI SDK, ready to benchmark with LLMDyno:
 *
 *     h = llmdyno.node_harness("vercel_ai_agent.ts:run", source="examples/agents/ts/vercel_ai_agent.ts")
 *     llmdyno.bench(profile, "suite_quick", harnesses=h.id)
 *
 * node_harness() installs the PACKAGES below. The agent talks Chat Completions to LLMDyno's proxy, so it works with
 * local and cloud models alike.
 */
import { spawnSync } from "node:child_process";
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";

import { createOpenAICompatible } from "@ai-sdk/openai-compatible";
import { generateText, stepCountIs, tool } from "ai";
import { z } from "zod";

export const PACKAGES = ["ai@7.0.179", "@ai-sdk/openai-compatible@3.0.94", "zod@4.6.7"];

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
  return {
    list_files: tool({
      description: "List the files under a folder of the workspace ('.' for all of it).",
      inputSchema: z.object({ path: z.string() }),
      execute: async ({ path }) => readdirSync(resolve(root, path), { recursive: true, withFileTypes: true })
        .filter((e) => e.isFile() && !/(^|[\\/])(\.git|node_modules)([\\/]|$)/.test(relative(root, e.parentPath)))
        .map((e) => relative(root, resolve(e.parentPath, e.name)).replaceAll("\\", "/"))
        .sort().join("\n").slice(0, 20000) || "(empty)",
    }),
    read_file: tool({
      description: "Read a text file of the workspace.",
      inputSchema: z.object({ path: z.string() }),
      execute: async ({ path }) => readFileSync(resolve(root, path), "utf8").slice(0, 50000),
    }),
    write_file: tool({
      description: "Create or overwrite a file of the workspace with this content.",
      inputSchema: z.object({ path: z.string(), content: z.string() }),
      execute: async ({ path, content }) => {
        const file = resolve(root, path);
        mkdirSync(dirname(file), { recursive: true });
        writeFileSync(file, content, "utf8");
        return `wrote ${path} (${content.length} characters)`;
      },
    }),
    run_command: tool({
      description: "Run a shell command in the workspace (tests, scripts, ls, …) and return its output.",
      inputSchema: z.object({ command: z.string() }),
      execute: async ({ command }) => {
        const r = spawnSync(command, { shell: true, cwd: root, encoding: "utf8", timeout: 600_000, maxBuffer: 2 ** 26 });
        return `exit ${r.status ?? "killed"}\n${r.stdout ?? ""}${r.stderr ?? ""}`.slice(-20000);
      },
    }),
  };
}

export async function run(task: Task): Promise<string> {
  const provider = createOpenAICompatible({ name: "llmdyno", baseURL: task.baseUrl, apiKey: task.apiKey });
  const result = await generateText({
    model: provider(task.model),
    system: instructions(task.workspace),
    prompt: task.prompt,
    tools: workspaceTools(task.workspace),
    stopWhen: stepCountIs(60),
    maxOutputTokens: task.maxTokens,
  });
  return result.text;
}

/**
 * A coding agent built with LangGraph.js (LangChain), ready to benchmark with LLMDyno:
 *
 *     h = llmdyno.node_harness("langgraph_agent.ts:run", source="examples/agents/ts/langgraph_agent.ts")
 *     llmdyno.bench(profile, "suite_quick", harnesses=h.id)
 *
 * node_harness() installs the PACKAGES below. ChatOpenAI talks Chat Completions to LLMDyno's proxy, so it works with
 * local and cloud models alike.
 */
import { spawnSync } from "node:child_process";
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";

import { tool } from "@langchain/core/tools";
import { createReactAgent } from "@langchain/langgraph/prebuilt";
import { ChatOpenAI } from "@langchain/openai";
import { z } from "zod";

export const PACKAGES = ["@langchain/langgraph@1.7.5", "@langchain/openai@1.8.5", "@langchain/core@1.5.0", "zod@4.6.7"];

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
    tool(async ({ path }) => readdirSync(resolve(root, path), { recursive: true, withFileTypes: true })
      .filter((e) => e.isFile() && !/(^|[\\/])(\.git|node_modules)([\\/]|$)/.test(relative(root, e.parentPath)))
      .map((e) => relative(root, resolve(e.parentPath, e.name)).replaceAll("\\", "/"))
      .sort().join("\n").slice(0, 20000) || "(empty)", {
      name: "list_files",
      description: "List the files under a folder of the workspace ('.' for all of it).",
      schema: z.object({ path: z.string() }),
    }),
    tool(async ({ path }) => readFileSync(resolve(root, path), "utf8").slice(0, 50000), {
      name: "read_file",
      description: "Read a text file of the workspace.",
      schema: z.object({ path: z.string() }),
    }),
    tool(async ({ path, content }) => {
      const file = resolve(root, path);
      mkdirSync(dirname(file), { recursive: true });
      writeFileSync(file, content, "utf8");
      return `wrote ${path} (${content.length} characters)`;
    }, {
      name: "write_file",
      description: "Create or overwrite a file of the workspace with this content.",
      schema: z.object({ path: z.string(), content: z.string() }),
    }),
    tool(async ({ command }) => {
      const r = spawnSync(command, { shell: true, cwd: root, encoding: "utf8", timeout: 600_000, maxBuffer: 2 ** 26 });
      return `exit ${r.status ?? "killed"}\n${r.stdout ?? ""}${r.stderr ?? ""}`.slice(-20000);
    }, {
      name: "run_command",
      description: "Run a shell command in the workspace (tests, scripts, ls, …) and return its output.",
      schema: z.object({ command: z.string() }),
    }),
  ];
}

export async function run(task: Task): Promise<string> {
  const llm = new ChatOpenAI({
    model: task.model,
    apiKey: task.apiKey,
    configuration: { baseURL: task.baseUrl },
    maxTokens: task.maxTokens,
    timeout: 900_000,
    maxRetries: 2,
  });
  const agent = createReactAgent({ llm, tools: workspaceTools(task.workspace), prompt: instructions(task.workspace) });
  const state = await agent.invoke({ messages: [{ role: "user", content: task.prompt }] }, { recursionLimit: 120 });
  const last = state.messages.at(-1);
  return typeof last?.content === "string" ? last.content : JSON.stringify(last?.content ?? "");
}

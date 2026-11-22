#!/usr/bin/env node
/**
 * `npx llmdyno`: start LLMDyno (a Python app) from Node. With no arguments it runs `llmdyno serve --open`; any
 * arguments go to the Python command line as they are (`npx llmdyno doctor`, `npx llmdyno serve --port 9000`).
 *
 * It uses, in this order: a Python that already has LLMDyno installed, uv (`uvx`), or pipx, pinning the LLMDyno
 * version to this package's. LLMDYNO_PYTHON names a Python to try first. LLMDYNO_LAUNCHER_DRY_RUN=1 prints the
 * command instead of running it.
 */
import { spawn, spawnSync } from "node:child_process";
import { VERSION } from "./version.ts";

interface Runner {
  label: string;
  cmd: string;
  args: string[];
  installed?: string;
}

const WINDOWS = process.platform === "win32";

function output(cmd: string, args: string[]): string | undefined {
  try {
    const r = spawnSync(cmd, args, { encoding: "utf8", timeout: 30_000, windowsHide: true });
    return r.status === 0 ? r.stdout.trim() : undefined;
  } catch {
    return undefined;
  }
}

function pythons(): Array<[string, string[]]> {
  const list: Array<[string, string[]]> = [];
  const chosen = process.env.LLMDYNO_PYTHON;
  if (chosen) list.push([chosen, []]);
  if (WINDOWS) list.push(["py", ["-3"]], ["python", []], ["python3", []]);
  else list.push(["python3", []], ["python", []]);
  return list;
}

function findRunner(): Runner | undefined {
  for (const [cmd, pre] of pythons()) {
    const version = output(cmd, [...pre, "-c", "import llmdyno; print(llmdyno.__version__)"]);
    if (version && /^\d+\.\d+/.test(version)) {
      return { label: `${[cmd, ...pre].join(" ")} -m llmdyno (LLMDyno ${version})`, cmd, args: [...pre, "-m", "llmdyno"], installed: version };
    }
  }
  if (output("uvx", ["--version"]) !== undefined) {
    return { label: `uvx llmdyno==${VERSION}`, cmd: "uvx", args: ["--from", `llmdyno==${VERSION}`, "llmdyno"] };
  }
  if (output("pipx", ["--version"]) !== undefined) {
    return { label: `pipx run llmdyno==${VERSION}`, cmd: "pipx", args: ["run", "--spec", `llmdyno==${VERSION}`, "llmdyno"] };
  }
  return undefined;
}

const HELP = `LLMDyno benchmarks local and cloud LLMs as coding agents. It is a Python app (3.11+) that runs agents
in Docker, and \`npx llmdyno\` starts it through one of these, none of which is installed here:

  uv (recommended)   https://docs.astral.sh/uv/getting-started/installation/
  pipx               https://pipx.pypa.io/stable/installation/
  pip                pip install llmdyno

Install one, then run \`npx llmdyno\` again. Docker is needed to run benchmarks: https://docs.docker.com/get-docker/
Docs: https://speak2jerome.github.io/llmdyno/JAVASCRIPT/`;

function main(): void {
  const args = process.argv.slice(2);
  const forwarded = args.length ? args : ["serve", "--open"];
  const runner = findRunner();
  if (!runner) {
    console.error(HELP);
    process.exit(1);
  }
  if (process.env.LLMDYNO_LAUNCHER_DRY_RUN) {
    console.log(JSON.stringify({ runner: runner.label, command: [runner.cmd, ...runner.args, ...forwarded] }));
    return;
  }
  if (runner.installed && runner.installed.split(".").slice(0, 2).join(".") !== VERSION.split(".").slice(0, 2).join(".")) {
    console.error(`note: using the installed LLMDyno ${runner.installed}; this launcher is ${VERSION} `
      + `(pip install -U "llmdyno==${VERSION}" to match)`);
  }
  const child = spawn(runner.cmd, [...runner.args, ...forwarded], { stdio: "inherit", windowsHide: false });
  // Ctrl+C reaches the Python process too; wait for it to shut down cleanly instead of exiting first.
  for (const signal of ["SIGINT", "SIGTERM"] as const) process.on(signal, () => { /* the child handles it */ });
  child.on("error", (e) => {
    console.error(`could not start ${runner.label}: ${e.message}`);
    process.exit(1);
  });
  child.on("exit", (code, signal) => process.exit(code ?? (signal ? 130 : 1)));
}

main();

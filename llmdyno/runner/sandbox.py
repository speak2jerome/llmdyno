"""Docker plumbing for runs: the internal network, per-run proxy containers, agent stages and graders."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

from .. import config
from ..benchmarks.registry import COMMON_DIR
from ..harnesses.images import QUALITY, SANDBOX

NET = "llmdyno-internal"
PROXY_DIR = Path(__file__).resolve().parent.parent / "proxy"
QUALITY_DIR = Path(__file__).resolve().parent.parent / "quality"
IS_WIN = os.name == "nt"
NOWIN = subprocess.CREATE_NO_WINDOW if IS_WIN else 0


def sh(args, timeout=120, **kw):
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                          creationflags=NOWIN, **kw)


def host_path(p):
    """Docker Desktop on Windows accepts C:/... paths; keep forward slashes for consistency."""
    return str(Path(p).resolve()).replace("\\", "/")


def ensure_network():
    if sh(["docker", "network", "inspect", NET]).returncode != 0:
        r = sh(["docker", "network", "create", "--internal", NET])
        if r.returncode != 0 and "already exists" not in r.stderr:
            raise RuntimeError(f"could not create docker network {NET}: {r.stderr.strip()}")


def bridge_gateway():
    r = sh(["docker", "network", "inspect", "bridge", "-f", "{{(index .IPAM.Config 0).Gateway}}"])
    return r.stdout.strip() or "172.17.0.1"


def llama_bind_host():
    """Address llama-server listens on so that containers can reach it: loopback works with Docker Desktop's
    host.docker.internal; on Linux the bridge gateway is used (never 0.0.0.0, to keep it off the LAN)."""
    return "127.0.0.1" if IS_WIN else bridge_gateway()


def kill(name):
    sh(["docker", "rm", "-f", name], timeout=60)


def start_proxy(name, logs_dir, upstream, api_style, key=None, prices=None, ledgers=None, extra_headers=None,
                compat_local=False):
    """Start the logging proxy for one run. Returns the alias agents use on the internal network."""
    kill(name)
    logs_dir = Path(logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)
    ledger_dir = config.DATA / "ledgers"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    env = {"UPSTREAM": upstream, "API_STYLE": api_style, "PROXY_LOG": "/logs/proxy.jsonl",
           "TRANSCRIPT": "/logs/transcript.jsonl",
           "LEDGERS": json.dumps([{"name": lg["name"], "budget": lg["budget"]} for lg in ledgers or []]),
           "LEDGER_DIR": "/budget", "LEDGER_WRITER": name,
           "PROXY_IDLE_TIMEOUT": str(int(config.get("proxy_idle_timeout_s") or 900)),
           "EXTRA_HEADERS": json.dumps(extra_headers or {}), "COMPAT_LOCAL": "1" if compat_local else "0"}
    for k, v in (prices or {}).items():
        env[f"PRICE_{k.upper()}"] = str(v or 0)
    envf = tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8")
    try:
        for k, v in env.items():
            envf.write(f"{k}={v}\n")
        if key:
            envf.write(f"UPSTREAM_API_KEY={key}\n")
        envf.close()
        args = ["docker", "run", "-d", "--name", name, "--memory", "512m", "--env-file", envf.name,
                "-v", f"{host_path(logs_dir)}:/logs", "-v", f"{host_path(PROXY_DIR)}:/app:ro",
                "-v", f"{host_path(ledger_dir)}:/budget", "--label", "org.llmdyno.role=proxy"]
        if not IS_WIN:
            args += ["--add-host", "host.docker.internal:host-gateway"]
        args += [SANDBOX, "python", "/app/llm_proxy.py"]
        r = sh(args)
        if r.returncode != 0:
            raise RuntimeError(f"proxy failed to start: {r.stderr.strip()[-400:]}")
    finally:
        Path(envf.name).unlink(missing_ok=True)       # the key only lives in the container's environment
    r = sh(["docker", "network", "connect", "--alias", name, NET, name])
    if r.returncode != 0:
        kill(name)
        raise RuntimeError(f"could not attach proxy to {NET}: {r.stderr.strip()}")
    for _ in range(40):
        st = sh(["docker", "inspect", "-f", "{{.State.Running}}", name]).stdout.strip()
        if st != "true":
            logs = sh(["docker", "logs", name]).stdout[-600:]
            raise RuntimeError(f"proxy exited: {logs}")
        if "proxy :" in sh(["docker", "logs", name]).stdout:
            return name
        time.sleep(0.25)
    return name


def run_stage(name, image, run_dir, stage, env, timeout_s, cpus, memory_gb, cancel_event=None):
    """Run one harness stage. Returns {exit_code, timed_out, cancelled, wall_s}."""
    kill(name)
    run_dir = Path(run_dir)
    args = ["docker", "run", "--rm", "--name", name, "--network", NET, "--memory", f"{memory_gb}g",
            "--cpus", str(cpus), "--pids-limit", "4096", "--label", "org.llmdyno.role=agent",
            "-e", "HOME=/home/agent", "-w", "/workspace",
            "-v", f"{host_path(run_dir / 'workspace')}:/workspace", "-v", f"{host_path(run_dir / 'home')}:/home/agent",
            "-v", f"{host_path(run_dir / 'bench')}:/bench:ro"]
    if not IS_WIN and hasattr(os, "getuid"):
        args += ["--user", f"{os.getuid()}:{os.getgid()}"]
    for k, v in env.items():
        args += ["-e", f"{k}={v}"]
    args += [image, "bash", f"/bench/stage{stage}.sh"]
    out = open(run_dir / f"stdout_stage{stage}.log", "wb")
    err = open(run_dir / f"stderr_stage{stage}.log", "wb")
    t0 = time.time()
    timed_out = cancelled = False
    proc = subprocess.Popen(args, stdout=out, stderr=err, creationflags=NOWIN)
    try:
        while proc.poll() is None:
            if time.time() - t0 > timeout_s:
                timed_out = True
                break
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break
            time.sleep(0.5)
        if timed_out or cancelled:
            sh(["docker", "kill", name], timeout=60)
            try:
                proc.wait(60)
            except subprocess.TimeoutExpired:
                proc.kill()
    finally:
        out.close()
        err.close()
    return {"exit_code": proc.returncode, "timed_out": timed_out, "cancelled": cancelled,
            "wall_s": round(time.time() - t0, 1), "t_start": t0, "t_end": time.time()}


def grade(bench, workspace, stage, timeout_s=None):
    """Grade a workspace in a fresh offline container; hidden tests are only ever mounted here."""
    g = bench["grader"]
    timeout_s = timeout_s or g.get("timeout_s", 600)
    tdir = Path(bench["dir"])
    if g["type"] == "spec":
        cmd = "python /grader_common/spec_grade.py"
    else:
        cmd = f"python /task/{g['path']}"
    args = ["docker", "run", "--rm", "--network", "none", "--memory", "8g", "--label", "org.llmdyno.role=grader",
            "-v", f"{host_path(workspace)}:/work_ro:ro", "-v", f"{host_path(tdir)}:/task:ro",
            "-v", f"{host_path(COMMON_DIR)}:/grader_common:ro", "-e", f"STAGE={stage}", "-e", "WORK=/work",
            "-e", "TASK_DIR=/task", "-e", f"SPEC={g.get('path', 'grader/spec.json')}", SANDBOX, "bash", "-c",
            f"cp -a /work_ro /work && cd /work && timeout {timeout_s} {cmd}"]
    t0 = time.time()
    try:
        p = sh(args, timeout=timeout_s + 180)
    except subprocess.TimeoutExpired:
        return {"grader_error": "grader timed out", "correctness": 0.0, "instruction_following": 0.0,
                "tests_total": 0, "tests_passed": 0}
    for line in reversed(p.stdout.strip().splitlines()):
        if line.startswith("{"):
            try:
                d = json.loads(line)
                d["grade_s"] = round(time.time() - t0, 1)
                return d
            except ValueError:
                break
    return {"grader_error": (p.stderr or p.stdout)[-1500:], "correctness": 0.0, "instruction_following": 0.0,
            "tests_total": 0, "tests_passed": 0}


def analyze_quality(bench, workspace):
    """Static analysis of the files the agent wrote (llmdyno-quality image)."""
    tdir = Path(bench["dir"])
    mounts = ["-v", f"{host_path(workspace)}:/work:ro", "-v", f"{host_path(QUALITY_DIR)}:/q:ro"]
    if bench.get("workspace") and (tdir / bench["workspace"]).exists():
        mounts += ["-v", f"{host_path(tdir / bench['workspace'])}:/template:ro"]
    if (tdir / "stage_files").exists():
        mounts += ["-v", f"{host_path(tdir / 'stage_files')}:/stage_files:ro"]
    p = sh(["docker", "run", "--rm", "--network", "none", "--memory", "6g", *mounts, QUALITY, "python", "/q/analyze.py",
            "--task", bench["id"]], timeout=900)
    for line in reversed(p.stdout.strip().splitlines()):
        if line.startswith("{"):
            d = json.loads(line)
            return {**d["summary"], "files": d["files"]}
    return {"error": (p.stderr or p.stdout)[-800:]}


def run_probes(bench, workspace):
    if not bench.get("probes"):
        return None
    pdir = Path(bench["dir"]) / bench["probes"]
    if not pdir.exists():
        return None
    p = sh(["docker", "run", "--rm", "--network", "none", "--memory", "6g", "-v", f"{host_path(workspace)}:/work_ro:ro",
            "-v", f"{host_path(pdir)}:/probes:ro", "-e", "WORK=/work", QUALITY, "bash", "-c",
            "cp -a /work_ro /work && cd /work && PYTHONPATH=/work timeout 700 python -m pytest -q -p no:cacheprovider "
            "--timeout=400 --junitxml=/tmp/p.xml /probes >/dev/null 2>&1; cat /tmp/p.xml"], timeout=900)
    import xml.etree.ElementTree as ET
    res = {}
    out = p.stdout
    try:
        for tc in ET.fromstring(out[out.find("<"):]).iter("testcase"):
            res[tc.get("name")] = not any(ch.tag in ("failure", "error", "skipped") for ch in tc)
    except ET.ParseError:
        return {"error": (p.stderr or out)[-500:]}
    return {"passed": sum(res.values()), "total": len(res),
            "rate": round(sum(res.values()) / len(res), 4) if res else None, "tests": res}


def prepare_workspace(bench, ws):
    """Copy the benchmark's starting files and decompress any packed data."""
    import gzip
    tdir = Path(bench["dir"])
    if bench.get("workspace") and (tdir / bench["workspace"]).exists():
        shutil.copytree(tdir / bench["workspace"], ws, dirs_exist_ok=True)
    else:
        ws.mkdir(parents=True, exist_ok=True)
    for rel in bench.get("decompress") or []:
        src = ws / rel
        if src.exists() and src.suffix == ".gz":
            with gzip.open(src, "rb") as fi, open(src.with_suffix(""), "wb") as fo:
                shutil.copyfileobj(fi, fo)
            src.unlink()


def llama_health(port):
    try:
        return httpx.get(f"http://127.0.0.1:{port}/health", timeout=3).json().get("status") == "ok"
    except (httpx.HTTPError, ValueError):
        return False


def cleanup_stale():
    """Remove proxy/agent containers left behind by a crash (no-op when Docker is missing or stopped)."""
    try:
        r = sh(["docker", "ps", "-aq", "--filter", "label=org.llmdyno.role"], timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return 0
    ids = [x for x in r.stdout.split() if re.fullmatch(r"[0-9a-f]+", x)]
    if ids:
        sh(["docker", "rm", "-f", *ids], timeout=120)
    return len(ids)

"""Plans: preflight checks, the run matrix, and the executor job.

Local profiles own the GPU one at a time (one llama-server load per profile, all its runs back to back); cloud runs
go through a thread pool at the same time. Every run gets its own proxy, so logs and transcripts never mix."""
import json
import shutil
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import __version__, config, db, events, jobs, memory, profiles, secrets
from ..benchmarks import registry as benches
from ..harnesses import catalog, images
from ..inference import llamacpp
from ..providers import registry as providers
from ..system import specs as sysspecs
from . import metrics, sandbox

GPU_LOCK = threading.Lock()
LOCAL_MODEL_NAME = "local-model"
_active = {}            # run id -> {"cancel": AnyEvent, "own": Event, "containers": set()}
_alock = threading.Lock()


class AnyEvent:
    """Set when either the run's own cancel event or its plan's cancel event is set."""

    def __init__(self, *evs):
        self.evs = [e for e in evs if e is not None]

    def is_set(self):
        return any(e.is_set() for e in self.evs)


# ------------------------------------------------------------------ resolution
def load_profile(pid):
    with db.Session() as s:
        p = s.get(db.Profile, pid)
        if not p:
            raise KeyError(f"profile {pid} not found")
        m = s.get(db.Model, p.model_id) if p.model_id else None
        prov = s.get(db.Provider, p.provider_id) if p.provider_id else None
        return db.row(p), (db.row(m) if m else None), (db.row(prov) if prov else None)


def custom_harnesses():
    return images.custom_manifests()


def endpoint(profile, model, provider, harness):
    """(upstream URL, api style, model name the harness uses, key) or raises ValueError when incompatible."""
    if profile["kind"] == "local":
        style = catalog.choose_api(harness, ["openai-chat", "openai-responses"], "openai-chat")
        if not style:
            raise ValueError(f"{harness.name} needs {', '.join(harness.apis)}, which llama-server does not offer")
        return f"http://host.docker.internal:{config.get('llama_port')}", style, LOCAL_MODEL_NAME, None
    if not provider:
        raise ValueError("the profile's provider was deleted")
    vendor = providers.BY_ID.get(provider["vendor"], providers.BY_ID["custom"])
    styles = dict(vendor.get("styles") or {})
    if provider["vendor"] == "custom":
        styles = {provider["api_style"]: provider["base_url"]}
    else:
        styles[provider["api_style"]] = styles.get(provider["api_style"]) or provider["base_url"]
    style = catalog.choose_api(harness, list(styles), profile["params"].get("api_style") or provider["api_style"])
    if not style:
        raise ValueError(f"{harness.name} speaks {', '.join(harness.apis)}; {provider['name']} offers "
                         f"{', '.join(styles)}")
    url = styles[style] or provider["base_url"]
    key = secrets.get(providers.secret_name(provider["id"]))
    return url, style, profile["remote_model"], key


def run_ctx(profile, harness_style, model_name, proxy_alias, session_id):
    p = profile["params"]
    local = profile["kind"] == "local"
    reasoning = None if local else p.get("reasoning_effort")
    return catalog.RunCtx(model=model_name, base_url=f"http://{proxy_alias}:8081", api_style=harness_style,
                          ctx=int(p.get("ctx") or 65536), max_tokens=int(p.get("max_output_tokens") or 16384),
                          reasoning=reasoning, temperature=(p.get("sampling") or {}).get("temperature") if local
                          else p.get("temperature"), local=local, session_id=session_id, display_name=profile["name"])


# ------------------------------------------------------------------ preflight
def estimate_tokens(bench):
    """Median prompt/output tokens of finished runs on this benchmark, else the reference numbers."""
    with db.Session() as s:
        rows = s.query(db.Run).filter(db.Run.benchmark_id == bench["id"], db.Run.status == "done").all()
    pt = [r.metrics.get("total_prompt_tokens") for r in rows if (r.metrics or {}).get("total_prompt_tokens")]
    ot = [r.metrics.get("generated_tokens") for r in rows if (r.metrics or {}).get("generated_tokens")]
    ref = bench.get("reference_tokens") or {"prompt": 200000, "output": 12000, "cache_hit": 0.8}
    return {"prompt": statistics.median(pt) if len(pt) >= 3 else ref["prompt"],
            "output": statistics.median(ot) if len(ot) >= 3 else ref["output"], "cache_hit": ref.get("cache_hit", 0.8),
            "source": "your runs" if len(pt) >= 3 else "reference runs"}


def preflight(plan_spec):
    """Validate a plan before it starts. Returns blocking problems, warnings and time/cost estimates."""
    items, block = [], []
    spec_info = sysspecs.detect()
    bench_ids = benches.expand(plan_spec["benchmark_ids"])
    bl = []
    for bid in bench_ids:
        try:
            bl.append(benches.get(bid))
        except KeyError:
            block.append({"level": "danger", "text": f"Unknown benchmark {bid}"})
    iters = int(plan_spec.get("iterations") or 1)
    harness_list = []
    for hid in plan_spec["harness_ids"]:
        try:
            harness_list.append(catalog.get(hid, custom_harnesses()))
        except KeyError:
            block.append({"level": "danger", "text": f"Unknown harness {hid}"})
    if not spec_info["docker"].get("running"):
        block.append({"level": "danger", "text": "Docker is not running: start Docker Desktop / the Docker service."})
    if not images.image_exists(images.SANDBOX):
        block.append({"level": "danger", "text": "The sandbox base image is missing: build it on the Setup page."})
    if plan_spec.get("options", {}).get("quality", True) and not images.image_exists(images.QUALITY):
        items.append({"level": "warning", "text": "The quality-analysis image is missing; code-quality scores will be "
                      "skipped unless you build it on the Setup page."})
    for h in harness_list:
        if not images.image_exists(h.image()):
            block.append({"level": "danger", "text": f"{h.name} image is not built: build it on the Harnesses page.",
                          "harness": h.id})
    est_minutes, est_cost = 0.0, 0.0
    per_profile = []
    for pid in plan_spec["profile_ids"]:
        try:
            prof, model, prov = load_profile(pid)
        except KeyError as e:
            block.append({"level": "danger", "text": str(e)})
            continue
        row = {"profile_id": pid, "name": prof["name"], "kind": prof["kind"], "warnings": [], "minutes": 0, "cost": 0}
        ok_harnesses = []
        for h in harness_list:
            try:
                endpoint(prof, model, prov, h)
                ok_harnesses.append(h)
            except ValueError as e:
                items.append({"level": "warning", "text": f"{prof['name']} × {h.name} is skipped: {e}", "profile_id": pid})
        if harness_list and not ok_harnesses:
            block.append({"level": "danger", "text": f"{prof['name']} works with none of the selected harnesses", "profile_id": pid})
        n_h = len(ok_harnesses)
        if prof["kind"] == "local":
            if not llamacpp.installed()["installed"]:
                block.append({"level": "danger", "text": "llama.cpp is not installed (Setup page)."})
            if not model or model["status"] != "ready":
                block.append({"level": "danger", "text": f"{prof['name']}: model file is not downloaded."})
            else:
                chk = memory.check(model["meta"], prof["params"], spec_info, fit=prof.get("fit", {}).get("raw"),
                                   os_name="nt" if sysspecs.IS_WIN else "posix", benchmarks=bl)
                row["memory"] = {"verdict": chk["verdict"], "headroom_mib": chk["headroom_mib"],
                                 "gpu_total": chk["memory"]["gpu_total"]}
                for w in chk["warnings"]:
                    row["warnings"].append(w)
                    if w["level"] == "danger":
                        items.append({**w, "text": f"{prof['name']}: {w['text']}", "profile_id": pid, "ack": True})
                tps = (prof.get("smoke") or {}).get("decode_tps") or chk.get("decode_tps_estimate") or 40
                factor = min(max(60 / max(tps, 1), 0.5), 8)
            for b in bl:
                row["minutes"] += (b.get("expected_minutes") or {}).get("local", 5) * factor * iters * n_h if model else 0
        else:
            key_ok = bool(prov) and (prov["vendor"] == "custom" or secrets.has(providers.secret_name(prov["id"])))
            if not key_ok:
                block.append({"level": "danger", "text": f"{prof['name']}: no API key for {prov['name'] if prov else 'its provider'}."})
            price = prof.get("pricing") or {}
            if prov and prov["vendor"] != "custom" and not price.get("input") and not price.get("output"):
                items.append({"level": "warning", "text": f"{prof['name']}: no prices set, so spend cannot be tracked or "
                              "capped. Add prices on the profile (or look them up).", "profile_id": pid})
            for b in bl:
                tok = estimate_tokens(b)
                cost = (tok["prompt"] * (1 - tok["cache_hit"]) * (price.get("input") or 0) + tok["prompt"] * tok["cache_hit"]
                        * (price.get("cached") or price.get("input") or 0) + tok["output"] * (price.get("output") or 0)) / 1e6
                row["cost"] += cost * iters * n_h
                row["minutes"] += (b.get("expected_minutes") or {}).get("cloud", 3) * iters * n_h
            if prov:
                remaining = (prov["budget_usd"] or 0) - (prov["spent_usd"] or 0)
                if prov["vendor"] != "custom" and row["cost"] > remaining:
                    items.append({"level": "warning", "text": f"{prof['name']}: estimated ${row['cost']:.2f} exceeds the "
                                  f"${remaining:.2f} left in the {prov['name']} budget; runs stop when it is used up."})
        ctx = int(prof["params"].get("ctx") or 0)
        for b in bl:
            if ctx and b.get("min_context") and ctx < b["min_context"]:
                items.append({"level": "warning", "text": f"{prof['name']}: {ctx // 1024}k context is below what "
                              f"'{b['title']}' needed in reference runs (~{b['min_context'] // 1000}k)."})
        row["harness_ids"] = [h.id for h in ok_harnesses]
        per_profile.append(row)
        est_cost += row["cost"]
    local_min = sum(r["minutes"] for r in per_profile if r["kind"] == "local")
    cloud_min = sum(r["minutes"] for r in per_profile if r["kind"] != "local")
    conc = int(plan_spec.get("options", {}).get("cloud_concurrency") or config.get("cloud_concurrency"))
    est_minutes = max(local_min, cloud_min / max(conc, 1))
    budget = plan_spec.get("options", {}).get("budget_usd")
    if budget and est_cost > budget:
        items.append({"level": "warning", "text": f"Estimated cloud spend ${est_cost:.2f} is above this plan's "
                      f"${budget:.2f} cap: later cloud runs will be blocked."})
    n_runs = sum(len(r["harness_ids"]) for r in per_profile) * len(bl) * iters
    if n_runs == 0:
        block.append({"level": "danger", "text": "Select at least one profile, harness and benchmark."})
    if n_runs > 400:
        items.append({"level": "warning", "text": f"{n_runs} runs is a very large plan; consider fewer iterations first."})
    free = min((d["free_bytes"] for d in spec_info["disks"]), default=0)
    if free and free < n_runs * 60 * 2**20:
        items.append({"level": "warning", "text": f"Only {free / 2**30:.1f} GB free for run folders "
                      f"(about {n_runs * 60 / 1024:.1f} GB may be needed)."})
    return {"ok": not block, "blocking": block, "warnings": items, "profiles": per_profile, "n_runs": n_runs,
            "estimate": {"minutes": round(est_minutes, 1), "local_minutes": round(local_min, 1),
                         "cloud_minutes": round(cloud_min, 1), "cost_usd": round(est_cost, 3)},
            "benchmarks": [{"id": b["id"], "title": b["title"]} for b in bl]}


def create_plan(spec):
    pid = db.new_id("plan")
    bench_ids = benches.expand(spec["benchmark_ids"])
    iters = int(spec.get("iterations") or 1)
    with db.Session() as s:
        plan = db.Plan(id=pid, name=spec.get("name") or f"Plan {time.strftime('%b %d %H:%M')}",
                       profile_ids=spec["profile_ids"], harness_ids=spec["harness_ids"], benchmark_ids=bench_ids,
                       iterations=iters, options=spec.get("options") or {}, status="queued",
                       preflight=spec.get("preflight") or {})
        s.add(plan)
        pairs = {r["profile_id"]: r["harness_ids"] for r in (spec.get("preflight") or {}).get("profiles", [])}
        for prof in spec["profile_ids"]:
            for h in pairs.get(prof, spec["harness_ids"]):
                for b in bench_ids:
                    for i in range(1, iters + 1):
                        s.add(db.Run(id=db.new_id("run"), plan_id=pid, profile_id=prof, harness_id=h, benchmark_id=b,
                                     iteration=i, status="queued"))
        s.commit()
    return pid


# ------------------------------------------------------------------ execution
def _publish_run(run_id):
    with db.Session() as s:
        r = s.get(db.Run, run_id)
        if not r:
            return
        d = run_summary(r)
    events.publish(f"plan:{d['plan_id']}", "run", d)
    events.publish(f"run:{run_id}", "status", d)


def run_summary(r):
    m = r.metrics or {}
    return {"id": r.id, "plan_id": r.plan_id, "profile_id": r.profile_id, "harness_id": r.harness_id,
            "benchmark_id": r.benchmark_id, "iteration": r.iteration, "status": r.status, "stage": r.stage,
            "started_at": r.started_at, "ended_at": r.ended_at, "correctness": r.correctness,
            "instruction_following": r.instruction_following, "wall_s": r.wall_s, "cost_usd": r.cost_usd,
            "error": r.error, "tests_passed": m.get("tests_passed"), "tests_total": m.get("tests_total"),
            "decode_tps": m.get("decode_tps"), "peak_context_tokens": m.get("peak_context_tokens"),
            "generated_tokens": m.get("generated_tokens"), "spill_detected": m.get("spill_detected"),
            "quality_done": bool(r.quality)}


def _set_run(run_id, **f):
    with db.Session() as s:
        r = s.get(db.Run, run_id)
        for k, v in f.items():
            setattr(r, k, v)
        s.commit()
    _publish_run(run_id)


def _set_plan(plan_id, **f):
    with db.Session() as s:
        p = s.get(db.Plan, plan_id)
        for k, v in f.items():
            setattr(p, k, v)
        s.commit()
        d = db.row(p)
    events.publish(f"plan:{plan_id}", "plan", d)
    events.publish("plans", "update", d)


def plan_status(plan_id):
    with db.Session() as s:
        return s.get(db.Plan, plan_id).status


class Tail(threading.Thread):
    """Streams a run's transcript and proxy log lines to WebSocket subscribers while it runs."""

    def __init__(self, run_id, run_dir):
        super().__init__(daemon=True, name=f"tail-{run_id}")
        self.run_id, self.run_dir = run_id, Path(run_dir)
        self.stop_ev = threading.Event()

    def run(self):
        offs = {"transcript.jsonl": 0, "proxy.jsonl": 0}
        idx = {"transcript.jsonl": 0, "proxy.jsonl": 0}
        while not self.stop_ev.is_set():
            self._pump(offs, idx)
            self.stop_ev.wait(0.1)
        self._pump(offs, idx)

    def _pump(self, offs, idx):
        for name in offs:
            p = self.run_dir / name
            try:
                if not p.exists() or p.stat().st_size <= offs[name]:
                    continue
                with open(p, "rb") as f:
                    f.seek(offs[name])
                    chunk = f.read()
                cut = chunk.rfind(b"\n")
                if cut < 0:
                    continue
                offs[name] += cut + 1
                for line in chunk[:cut].splitlines():
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        idx[name] += 1
                        continue
                    kind = "transcript" if name == "transcript.jsonl" else "proxy"
                    events.publish(f"run:{self.run_id}", kind, {"i": idx[name], "ev": ev})
                    idx[name] += 1
            except OSError:
                pass


def write_stage_script(run_dir, stage, prompt, command):
    b = run_dir / "bench"
    b.mkdir(parents=True, exist_ok=True)
    (b / f"prompt_stage{stage}.md").write_text(prompt, encoding="utf-8")
    script = ("#!/bin/bash\n# generated by LLMDyno\nset -o pipefail\nmkdir -p \"$HOME\"\n"
              f"export PROMPT=\"$(cat /bench/prompt_stage{stage}.md)\"\n{command} < /dev/null\n")
    (b / f"stage{stage}.sh").write_bytes(script.encode("utf-8"))


def execute_run(run_id, plan, prof, model, prov, gpu_sampler=None, cancel_event=None, log=print):
    """One profile × harness × benchmark × iteration, start to finish."""
    with db.Session() as s:
        r = s.get(db.Run, run_id)
        harness_id, bench_id = r.harness_id, r.benchmark_id
    harness = catalog.get(harness_id, custom_harnesses())
    bench = benches.get(bench_id)
    run_dir = config.path("runs_dir") / plan["id"] / run_id
    shutil.rmtree(run_dir, ignore_errors=True)
    for sub in ("workspace", "home", "bench"):
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    snapshot = {"profile": {k: prof[k] for k in ("id", "name", "kind", "params", "pricing", "remote_model")},
                "model": model and {k: model[k] for k in ("id", "repo", "name", "quant", "size_bytes")},
                "provider": prov and {k: prov[k] for k in ("id", "vendor", "name", "base_url", "api_style")},
                "harness": harness.info(), "benchmark": {k: bench.get(k) for k in ("id", "title", "version", "category")},
                "llmdyno_version": __version__}
    _set_run(run_id, status="running", started_at=time.time(), dir=str(run_dir), snapshot=snapshot, error="",
             stage="setup")
    upstream, style, model_name, key = endpoint(prof, model, prov, harness)
    proxy = f"dyno-proxy-{run_id[-10:]}"
    tail = Tail(run_id, run_dir)
    tail.start()
    own = threading.Event()
    with _alock:
        _active[run_id] = {"cancel": AnyEvent(own, cancel_event), "own": own, "containers": {proxy}}
    stages_out, stage_grades = [], []
    try:
        sandbox.prepare_workspace(bench, run_dir / "workspace")
        ledgers = []
        if prov and prov["vendor"] != "custom":
            ledgers.append({"name": f"provider_{prov['id']}", "budget": prov["budget_usd"]})
            if plan["options"].get("budget_usd"):
                ledgers.append({"name": f"plan_{plan['id']}", "budget": plan["options"]["budget_usd"]})
        sandbox.start_proxy(proxy, run_dir, upstream, style, key=key, compat_local=prof["kind"] == "local",
                            prices=prof.get("pricing") if prof["kind"] != "local" else None,
                            ledgers=ledgers,
                            extra_headers={"HTTP-Referer": "https://github.com/speak2jerome/llmdyno", "X-Title": "LLMDyno"}
                            if prov and prov["vendor"] == "openrouter" else None)
        rc = run_ctx(prof, style, model_name, proxy, session_id=f"bench-{run_id[-8:]}")
        for rel, content in harness.files(rc).items():
            f = run_dir / "home" / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(content, encoding="utf-8")
        prompts = benches.prompt_texts(bench)
        n = len(bench["stages"])
        cpus = min(8, max(2, (sysspecs.detect()["cpu"]["threads"] or 4) // 2))
        for i, st in enumerate(bench["stages"], 1):
            if st.get("add_files"):
                shutil.copytree(Path(bench["dir"]) / st["add_files"], run_dir / "workspace", dirs_exist_ok=True)
            write_stage_script(run_dir, i, prompts[i - 1], harness.command(rc, i, n))
            _set_run(run_id, stage=f"stage {i}/{n}")
            log(f"  {run_id} stage {i}/{n}")
            mult = float(plan["options"].get("timeout_multiplier") or 1.0)
            name = f"dyno-agent-{run_id[-10:]}-s{i}"
            _active[run_id]["containers"].add(name)
            res = sandbox.run_stage(name, harness.image(), run_dir, i, harness.env(rc), st["timeout_s"] * mult, cpus,
                                    int(plan["options"].get("memory_gb") or 12), _active[run_id]["cancel"])
            res["proxy"] = metrics.proxy_metrics(run_dir / "proxy.jsonl", res["t_start"], res["t_end"])
            if gpu_sampler:
                res["gpu"] = metrics.gpu_metrics(run_dir.parent / f"gpu_{prof['id']}.jsonl", res["t_start"], res["t_end"],
                                                 gpu_sampler.baseline_shared)
            stages_out.append(res)
            if res["cancelled"]:
                raise jobs.Cancelled()
            if bench.get("grade_each_stage") and i < n:
                _set_run(run_id, stage=f"grading stage {i}")
                g = sandbox.grade(bench, run_dir / "workspace", i)
                stage_grades.append({"stage": i, **{k: g.get(k) for k in ("correctness", "tests_passed", "tests_total",
                                                                         "instruction_following")}})
        _set_run(run_id, status="grading", stage="grading")
        final = sandbox.grade(bench, run_dir / "workspace", n)
        if bench.get("grade_each_stage"):
            stage_grades.append({"stage": n, **{k: final.get(k) for k in ("correctness", "tests_passed", "tests_total",
                                                                         "instruction_following")}})
        result = summarize(prof, bench, stages_out, final, stage_grades, run_dir)
        q = {}
        if plan["options"].get("quality", True) and images.image_exists(images.QUALITY):
            _set_run(run_id, stage="quality analysis")
            try:
                q = {"static": sandbox.analyze_quality(bench, run_dir / "workspace"),
                     "probes": sandbox.run_probes(bench, run_dir / "workspace")}
            except Exception as e:  # noqa: BLE001 - quality is optional
                q = {"error": str(e)[:500]}
        (run_dir / "result.json").write_text(json.dumps({**result, "quality": q}, indent=2, default=str), encoding="utf-8")
        _set_run(run_id, status="done", ended_at=time.time(), stage="", correctness=result["correctness"],
                 instruction_following=result["instruction_following"], wall_s=result["wall_s"],
                 cost_usd=result["cost_usd"], metrics=result, quality=q)
        log(f"  {run_id} done: correctness={result['correctness']} IF={result['instruction_following']} "
            f"wall={result['wall_s']}s")
    except jobs.Cancelled:
        _set_run(run_id, status="cancelled", ended_at=time.time(), stage="")
        raise
    except Exception as e:  # noqa: BLE001
        if _active[run_id]["cancel"].is_set():    # killed mid-step (panic stop removes containers under us)
            _set_run(run_id, status="cancelled", ended_at=time.time(), stage="")
            raise jobs.Cancelled() from e
        _set_run(run_id, status="failed", ended_at=time.time(), stage="", error=f"{type(e).__name__}: {e}"[:2000])
        log(f"  {run_id} failed: {e}")
    finally:
        for c in list(_active.get(run_id, {}).get("containers", ())):
            sandbox.kill(c)
        with _alock:
            _active.pop(run_id, None)
        tail.stop_ev.set()
        tail.join(5)


def summarize(prof, bench, stages, final, stage_grades, run_dir):
    facts = metrics.transcript_facts(run_dir / "transcript.jsonl")
    pm = metrics.proxy_metrics(run_dir / "proxy.jsonl")

    def tot(key, src):
        vals = [s.get(src, {}).get(key) for s in stages if s.get(src, {}).get(key) is not None]
        return sum(vals) if vals else None
    common = {"no_install_attempts": not facts["install_attempts"],
              "finished_within_time": not any(s["timed_out"] for s in stages),
              "final_summary_given": len(facts["final_text"]) >= 20}
    n_task = final.get("checks_total") or 0
    if_task = final.get("instruction_following") or 0.0
    if_all = (if_task * n_task + sum(common.values())) / (n_task + len(common))
    energy = tot("gpu_energy_wh", "gpu")
    local = prof["kind"] == "local"
    cost = round(energy / 1000 * float(config.get("electricity_usd_per_kwh")), 5) if local and energy is not None else pm["cost_usd"]
    gpus = [s.get("gpu") or {} for s in stages]
    ctx = int(prof["params"].get("ctx") or 0)
    return {
        "correctness": final.get("correctness", 0.0), "instruction_following": round(if_all, 4),
        "tests_passed": final.get("tests_passed"), "tests_total": final.get("tests_total"),
        "task_checks": final.get("checks"), "common_checks": common, "grader_error": final.get("grader_error"),
        "tests": final.get("tests"), "grade_extra": {k: v for k, v in final.items() if k not in (
            "tests", "checks", "correctness", "instruction_following", "tests_total", "tests_passed", "checks_total",
            "checks_passed", "grader_error", "grade_s")} or None,
        "stage_grades": stage_grades or None, "wall_s": round(sum(s["wall_s"] for s in stages), 1),
        "timed_out": any(s["timed_out"] for s in stages), "exit_codes": [s["exit_code"] for s in stages],
        "turns": facts["turns"], "tool_calls": facts["tool_calls"], "n_tool_calls": facts["n_tool_calls"],
        "tool_errors": facts["tool_errors"], "install_attempts": facts["install_attempts"][:10],
        "final_text": facts["final_text"][:1500], "errors": facts["errors"],
        **{k: pm.get(k) for k in ("requests", "http_errors", "budget_blocked", "length_truncations", "total_prompt_tokens",
                                  "prefill_tokens", "cached_prompt_tokens", "cache_write_tokens", "generated_tokens",
                                  "reasoning_tokens", "reasoning_chars", "cache_hit_ratio", "peak_context_tokens",
                                  "decode_tps", "prefill_tps", "ttft_median_s", "model_time_s")},
        "context_utilization": round(pm["peak_context_tokens"] / ctx, 3) if pm.get("peak_context_tokens") and ctx else None,
        "gpu_energy_wh": energy, "gpu_peak_vram_mib": max((g.get("gpu_peak_vram_mib") or 0) for g in gpus) or None,
        "gpu_vram_total_mib": max((g.get("gpu_vram_total_mib") or 0) for g in gpus) or None,
        "gpu_spill_mib": max((g.get("gpu_spill_mib") or 0) for g in gpus) or None,
        "spill_detected": any(g.get("spill_detected") for g in gpus),
        "cost_usd": cost, "cost_basis": "GPU energy" if local else "provider tokens",
        "stages": [{k: v for k, v in s.items() if k not in ("t_start", "t_end")} for s in stages],
    }


def execute_plan(ctx):
    """Job: run every queued run of a plan."""
    plan_id = ctx.params["plan_id"]
    with db.Session() as s:
        plan = db.row(s.get(db.Plan, plan_id))
        queued = [db.row(r) for r in s.query(db.Run).filter(db.Run.plan_id == plan_id, db.Run.status == "queued")
                  .order_by(db.Run.profile_id, db.Run.benchmark_id, db.Run.iteration).all()]
    sandbox.ensure_network()
    _set_plan(plan_id, status="running", started_at=plan.get("started_at") or time.time(), ended_at=None)
    with db.Session() as s:     # count the whole plan, so a resumed plan reads 1/4 rather than 0/3
        already = s.query(db.Run).filter(db.Run.plan_id == plan_id, db.Run.status.in_(["done", "failed", "skipped"])).count()
    total = already + len(queued)
    done_count = [already]
    ctx.progress(already / max(total, 1), f"{already}/{total} runs")
    cancel_ev = ctx.cancel_event

    def finished_one():
        done_count[0] += 1
        ctx.progress(done_count[0] / max(total, 1), f"{done_count[0]}/{total} runs")

    profs = {}
    for pid in plan["profile_ids"]:
        try:
            profs[pid] = load_profile(pid)
        except KeyError:
            for r in queued:
                if r["profile_id"] == pid:
                    _set_run(r["id"], status="skipped", error="profile was deleted")
    local_runs = [r for r in queued if r["profile_id"] in profs and profs[r["profile_id"]][0]["kind"] == "local"]
    cloud_runs = [r for r in queued if r["profile_id"] in profs and profs[r["profile_id"]][0]["kind"] != "local"]

    def should_stop():
        return cancel_ev.is_set() or plan_status(plan_id) in ("paused", "cancelled")

    def cloud_worker(r):
        if should_stop():
            return
        prof, model, prov = profs[r["profile_id"]]
        try:
            execute_run(r["id"], plan, prof, model, prov, cancel_event=cancel_ev, log=ctx.log)
        except jobs.Cancelled:
            pass
        finished_one()

    conc = int(plan["options"].get("cloud_concurrency") or config.get("cloud_concurrency"))
    pool = ThreadPoolExecutor(max_workers=max(1, conc), thread_name_prefix="cloud-run")
    futures = [pool.submit(cloud_worker, r) for r in cloud_runs]

    by_profile = {}
    for r in local_runs:
        by_profile.setdefault(r["profile_id"], []).append(r)
    for pid, runs in by_profile.items():
        if should_stop():
            break
        prof, model, prov = profs[pid]
        ctx.log(f"Local profile {prof['name']}: waiting for the GPU")
        with GPU_LOCK:
            run_root = config.path("runs_dir") / plan_id
            run_root.mkdir(parents=True, exist_ok=True)
            sampler = metrics.GpuSampler(run_root / f"gpu_{pid}.jsonl",
                                         on_sample=lambda rec: events.publish(f"plan:{plan_id}", "gpu", rec)).start()
            try:
                paths = [str(Path(model["local_dir"]) / f) for f in model["files"]]
                # free VRAM changes with whatever else is open (browsers, games, overlays): re-check right before loading
                live = memory.check(model["meta"], prof["params"], sysspecs.detect(force=True),
                                    os_name="nt" if sysspecs.IS_WIN else "posix")
                if live["verdict"] in ("spill", "oom") and not plan["options"].get("allow_spill"):
                    raise RuntimeError(
                        f"not enough free VRAM right now: this profile needs about {live['memory']['gpu_total'] / 1024:.1f} GB "
                        f"but only {(live['gpu'] or {}).get('free_mib', 0) / 1024:.1f} GB is free. Close GPU-heavy apps "
                        "(browsers, games, overlays) or lower the context, then retry these runs; or enable 'allow spill' "
                        "on the plan to run anyway (results will be flagged).")
                if live["verdict"] == "tight":
                    ctx.log(f"Warning: only {live['headroom_mib']} MiB VRAM headroom for {prof['name']}")
                ctx.log(f"Loading {model['name']} (ctx {prof['params']['ctx']:,})")
                for r in runs:
                    _set_run(r["id"], stage="loading model")
                load_s = llamacpp.server.start(paths[0], profiles.launch_params(prof["params"]), run_root / f"server_{pid}.log",
                                               host=sandbox.llama_bind_host(), ctx=ctx)
                rep = llamacpp.server.load_report()
                ctx.log(f"Loaded in {load_s}s: {json.dumps(rep)[:400]}")
                for r in runs:
                    if r["status"] == "queued":
                        _set_run(r["id"], stage="")
                for r in runs:
                    if should_stop():
                        break
                    try:
                        execute_run(r["id"], plan, prof, model, prov, gpu_sampler=sampler, cancel_event=cancel_ev, log=ctx.log)
                    except jobs.Cancelled:
                        break
                    finished_one()
            except jobs.Cancelled:
                pass
            except Exception as e:  # noqa: BLE001 - one bad profile must not stop the plan
                ctx.log(f"Profile {prof['name']} failed: {e}")
                for r in runs:
                    with db.Session() as s:
                        st = s.get(db.Run, r["id"]).status
                    if st == "queued":
                        _set_run(r["id"], status="failed", error=f"model server: {e}"[:2000], stage="")
            finally:
                llamacpp.server.stop()
                sampler.stop()
    pool.shutdown(wait=True)
    for f in futures:
        if f.exception():
            ctx.log(f"cloud worker error: {f.exception()}")
    status = plan_status(plan_id)
    if cancel_ev.is_set() or status == "cancelled":
        with db.Session() as s:
            for r in s.query(db.Run).filter(db.Run.plan_id == plan_id, db.Run.status.in_(["queued", "running", "grading"])):
                r.status, r.stage = "cancelled", ""
            s.commit()
        _set_plan(plan_id, status="cancelled", ended_at=time.time())
        ctx.result = {"runs": total, "finished": done_count[0]}
        raise jobs.Cancelled()          # the activity list should say cancelled, not done
    with db.Session() as s:
        left = s.query(db.Run).filter(db.Run.plan_id == plan_id, db.Run.status == "queued").count()
        failed = s.query(db.Run).filter(db.Run.plan_id == plan_id, db.Run.status == "failed").count()
    if status == "paused" and left:
        _set_plan(plan_id, status="paused")
        ctx.cancel_status = "paused"
        raise jobs.Cancelled()
    _set_plan(plan_id, status="done", ended_at=time.time())
    ctx.result = {"runs": total, "failed": failed}
    if plan["options"].get("auto_judge") and plan["options"].get("judge"):
        from ..judge import judge as judge_mod
        judge_mod.start(plan_id, plan["options"]["judge"])


def start_plan(plan_id):
    with db.Session() as s:
        p = s.get(db.Plan, plan_id)
        p.status = "queued"
        s.commit()
        name = p.name
    return jobs.submit("plan", f"Run plan: {name}", execute_plan, {"plan_id": plan_id}, ref=plan_id)


def cancel_run(run_id):
    with _alock:
        a = _active.get(run_id)
    if a:
        a["own"].set()
        for c in list(a["containers"]):
            if c.startswith("dyno-agent"):
                sandbox.kill(c)
        return True
    with db.Session() as s:
        r = s.get(db.Run, run_id)
        if r and r.status == "queued":
            r.status = "cancelled"
            s.commit()
            _publish_run(run_id)
            return True
    return False

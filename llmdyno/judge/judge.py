"""Blind LLM code review with judges you choose.

Each judge sees the task and the files the agent wrote, behind a random id: no model, harness or profile names.
Review order is shuffled. Several judges can review the same runs; agreement and self-preference are reported."""
import difflib
import hashlib
import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import config, db, events, jobs, llm, profiles
from ..benchmarks import registry as benches
from ..inference import llamacpp
from ..runner import executor

MAX_FILE_LINES = 450
MAX_TOTAL_CHARS = 90_000
SKIP_DIRS = {"__pycache__", ".pytest_cache", "node_modules", ".git", "dist", "output", "data", "instance", ".venv",
             ".ruff_cache", ".mypy_cache", "htmlcov"}
DEFAULT_RUBRIC = [
    {"key": "readability", "label": "Readability", "description": "clear names, easy to follow, comments only where they help"},
    {"key": "structure", "label": "Structure", "description": "sensible modules/functions, separation of concerns, cohesion"},
    {"key": "idiomatic", "label": "Idiomatic", "description": "idiomatic use of the language and frameworks involved"},
    {"key": "robustness", "label": "Robustness", "description": "input validation, error handling, failure modes and edge cases (credit care beyond the spec)"},
    {"key": "security", "label": "Security", "description": "injection safety, output escaping, secrets, unsafe calls"},
    {"key": "tests", "label": "Tests", "description": "meaningful tests of the agent's own code, including edge cases (null if none were asked for and none exist)"},
    {"key": "simplicity", "label": "Simplicity", "description": "no duplication, dead code, needless abstraction or boilerplate"},
    {"key": "completeness", "label": "Completeness", "description": "implements everything asked; useful extras beyond the spec raise this score"},
]
DEFAULT_GUIDANCE = ("Length is neutral. Do not reward or penalize the amount of code by itself: a long solution that "
                    "handles more edge cases or adds genuinely useful features is good; penalize only code that adds no "
                    "value. Correctness against hidden tests is measured separately, so focus on engineering quality.")


def rubric_text(rubric, guidance):
    dims = "\n".join(f"- {d['key']}: {d.get('description', '')}" for d in rubric)
    keys = ", ".join(f'"{d["key"]}": n' for d in rubric)
    return (f"Score each dimension from 1 (poor) to 10 (excellent):\n{dims}\n\n{guidance}\n\nReply with JSON only:\n"
            f'{{"scores": {{{keys}}}, "overall": n, "extras_beyond_spec": ["..."], '
            f'"top_issues": ["file:line - issue", "..."], "summary": "two sentences"}}')


def task_spec(bench):
    parts = [f"## Step {i}\n{t}" for i, t in enumerate(benches.prompt_texts(bench), 1)]
    if bench.get("workspace"):
        issue = Path(bench["dir"]) / bench["workspace"] / "ISSUE.md"
        if issue.exists():
            parts.append("## Contents of ISSUE.md given to the agent\n" + issue.read_text(encoding="utf-8"))
    return "\n\n".join(parts)


def authored_files(run, bench):
    """{rel: {"status": new|modified, "test": bool}} from the quality analysis, else by comparing with the template."""
    files = ((run.get("quality") or {}).get("static") or {}).get("files")
    if files:
        return files
    ws = Path(run["dir"]) / "workspace"
    tmpl = Path(bench["dir"]) / bench["workspace"] if bench.get("workspace") else None
    out = {}
    for p in sorted(ws.rglob("*")):
        if not p.is_file() or set(p.relative_to(ws).parts) & SKIP_DIRS or p.stat().st_size > 400_000:
            continue
        rel = p.relative_to(ws).as_posix()
        orig = tmpl / rel if tmpl else None
        if orig is not None and orig.exists():
            if orig.read_bytes() == p.read_bytes():
                continue
            out[rel] = {"status": "modified"}
        else:
            out[rel] = {"status": "new"}
        out[rel]["test"] = rel.startswith("tests/") or Path(rel).name.startswith("test_")
    return out


def workspace_text(run, bench, files):
    ws = Path(run["dir"]) / "workspace"
    tmpl = Path(bench["dir"]) / bench["workspace"] if bench.get("workspace") else None
    chunks, total = [], 0
    for rel, info in sorted(files.items(), key=lambda kv: (kv[1].get("test", False), kv[0])):
        p = ws / rel
        if not p.exists():
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        tag = info.get("status")
        orig = tmpl / rel if tmpl else None
        if tag == "modified" and orig is not None and orig.exists():
            diff = list(difflib.unified_diff(orig.read_text(encoding="utf-8", errors="replace").splitlines(), lines,
                                             f"a/{rel} (before)", f"b/{rel} (after agent)", n=3, lineterm=""))
            block = f"### {rel} (modified by the agent; diff only)\n```diff\n" + "\n".join(diff) + "\n```"
        else:
            body = "\n".join(f"{i + 1:4d}  {line}" for i, line in enumerate(lines[:MAX_FILE_LINES]))
            if len(lines) > MAX_FILE_LINES:
                body += f"\n... ({len(lines) - MAX_FILE_LINES} more lines not shown)"
            block = f"### {rel} ({tag}, {len(lines)} lines)\n```\n{body}\n```"
        if total + len(block) > MAX_TOTAL_CHARS:
            chunks.append(f"### {rel} ({tag}, {len(lines)} lines) - omitted for length")
            continue
        chunks.append(block)
        total += len(block)
    return "\n\n".join(chunks) or "(the agent wrote no files)"


def static_summary(run):
    s = (run.get("quality") or {}).get("static") or {}
    if not s or "sloc_total" not in s:
        return ""
    keys = ("sloc_total", "ruff_per_100_sloc", "cc_avg", "max_nesting", "duplication", "own_test_functions",
            "own_tests_pass", "own_test_coverage", "bandit")
    return "# Static analysis (for context; do not just restate it)\n" + json.dumps({k: s.get(k) for k in keys})


# GGUF architecture prefix -> the vendor that trained it, so a local Qwen and Qwen's API count as one family
ARCH_VENDOR = [("gpt-oss", "openai"), ("qwen", "qwen"), ("gemma", "google"), ("llama", "meta"), ("mistral", "mistral"),
               ("ministral", "mistral"), ("devstral", "mistral"), ("deepseek", "deepseek"), ("glm", "zai"),
               ("chatglm", "zai"), ("minimax", "minimax"), ("kimi", "moonshot"), ("phi", "microsoft"),
               ("granite", "ibm"), ("nemotron", "nvidia"), ("ernie", "baidu"), ("olmo", "ai2"), ("smollm", "huggingface"),
               ("exaone", "lg"), ("command", "cohere"), ("cohere", "cohere"), ("grok", "xai")]


def family_of(prof, model=None, prov=None):
    """Model family for the self-preference check: the vendor behind the model, for local and cloud alike."""
    if prof["kind"] == "local":
        arch = (((model or {}).get("meta") or {}).get("arch") or "").lower()
        name = ((model or {}).get("name") or (model or {}).get("repo") or "").lower()
        for key, vendor in ARCH_VENDOR:          # the model name wins: Kimi ships as deepseek2, Devstral as llama
            if key in name:
                return vendor
        for key, vendor in ARCH_VENDOR:
            if arch.startswith(key):
                return vendor
        return arch or "local"
    vendor = (prov or {}).get("vendor")
    if vendor in ("openrouter", "groq", "together", "fireworks", "cerebras", "custom", None):
        rm = (prof.get("remote_model") or "").lower()       # hosts serve other vendors' models: use the model id
        for key, v in [*ARCH_VENDOR, ("gpt", "openai"), ("o3", "openai"), ("o4", "openai"), ("claude", "anthropic"),
                       ("gemini", "google")]:
            if key in rm:
                return v
    return vendor or "cloud"


def build_prompt(run, bench, blind_id, cfg):
    files = authored_files(run, bench)
    parts = [f"You are a senior engineer doing a blind review of solution #{blind_id} to the task below.",
             f"# Task given to the coding agent\n{task_spec(bench)}",
             f"# Files written or modified by the agent\n{workspace_text(run, bench, files)}"]
    if cfg.get("include_static"):
        parts.append(static_summary(run))
    parts.append(f"# How to review\n{rubric_text(cfg.get('rubric') or DEFAULT_RUBRIC, cfg.get('guidance') or DEFAULT_GUIDANCE)}")
    return "\n\n".join(p for p in parts if p)


def run_judge(ctx):
    cfg = ctx.params
    with db.Session() as s:
        q = s.query(db.Run).filter(db.Run.status == "done")
        if cfg.get("run_ids"):
            q = q.filter(db.Run.id.in_(cfg["run_ids"]))
        elif cfg.get("plan_ids"):
            q = q.filter(db.Run.plan_id.in_(cfg["plan_ids"]))
        runs = [db.row(r) for r in q.all()]
        existing = {(rv.run_id, rv.judge_id) for rv in s.query(db.Review).all()}
    judges = []
    for jp in cfg["judge_profile_ids"]:
        prof, model, prov = executor.load_profile(jp)
        judges.append((prof, model, prov))
    spent = {"usd": 0.0}
    budget = float(cfg.get("budget_usd") or 0)
    total = sum(1 for prof, _, _ in judges for r in runs if not (cfg.get("skip_reviewed", True) and (r["id"], prof["id"]) in existing))
    done = [0]
    stop = threading.Event()

    def review(prof, prov, run):
        if stop.is_set() or ctx.cancelled:
            return
        bench = benches.get(run["benchmark_id"])
        blind = hashlib.sha256(f"{run['id']}:{prof['id']}".encode()).hexdigest()[:8]
        prompt = build_prompt(run, bench, blind, cfg)
        res, err = None, ""
        for attempt in (1, 2):
            try:
                res = llm.complete(prof, prov, prompt, max_tokens=int(cfg.get("max_output_tokens") or 12000), json_mode=True)
                data = llm.parse_json(res["text"])
                break
            except Exception as e:  # noqa: BLE001 - retried once, then logged
                err = str(e)
                data = None
                ctx.log(f"#{blind} attempt {attempt} failed: {err[:200]}")
                if "429" in err or "rejected" in err:
                    stop.set()
                    break
        cost = (res or {}).get("cost_usd", 0) or 0
        spent["usd"] += cost
        if data is not None:
            scores = data.get("scores") or {}
            overall = data.get("overall")
            if not isinstance(overall, (int, float)):
                vals = [v for v in scores.values() if isinstance(v, (int, float))]
                overall = round(sum(vals) / len(vals), 1) if vals else None
            with db.Session() as s:
                s.query(db.Review).filter(db.Review.run_id == run["id"], db.Review.judge_id == prof["id"]).delete()
                s.add(db.Review(id=db.new_id("rev"), run_id=run["id"], judge_id=prof["id"], judge_name=prof["name"],
                                judge_job_id=ctx.id, overall=overall, scores=scores, summary=str(data.get("summary", ""))[:2000],
                                issues=[str(x)[:400] for x in (data.get("top_issues") or [])][:12],
                                extras=[str(x)[:300] for x in (data.get("extras_beyond_spec") or [])][:12], cost_usd=cost))
                s.commit()
            events.publish("reviews", "created", {"run_id": run["id"], "judge_id": prof["id"], "overall": overall})
            ctx.log(f"#{blind} scored {overall} · {((res or {}).get('usage') or {}).get('output', '?')} output tokens · "
                    f"{(res or {}).get('latency_s', '?')}s · ${cost:.4f}")
        done[0] += 1
        ctx.progress(done[0] / max(total, 1), f"{done[0]}/{total} reviews · ${spent['usd']:.3f}")
        if budget and spent["usd"] >= budget:
            ctx.log(f"judge budget ${budget:.2f} reached; stopping")
            stop.set()

    for prof, model, prov in judges:
        if stop.is_set():
            break
        todo = [r for r in runs if not (cfg.get("skip_reviewed", True) and (r["id"], prof["id"]) in existing)]
        random.Random(f"{prof['id']}:{len(todo)}").shuffle(todo)        # order carries no information about models
        ctx.log(f"Judge {prof['name']}: {len(todo)} runs to review")
        if prof["kind"] == "local":
            with executor.GPU_LOCK:
                paths = [str(Path(model["local_dir"]) / f) for f in model["files"]]
                llamacpp.server.start(paths[0], profiles.launch_params(prof["params"]),
                                      config.path("runs_dir") / "_judge" / f"server_{prof['id']}.log", ctx=ctx)
                try:
                    for r in todo:
                        review(prof, prov, r)
                        if stop.is_set():
                            break
                finally:
                    llamacpp.server.stop()
        else:
            with ThreadPoolExecutor(max_workers=int(cfg.get("concurrency") or 4)) as pool:
                list(pool.map(lambda r, p=prof, v=prov: review(p, v, r), todo))
    ctx.result = {"reviews": done[0], "spent_usd": round(spent["usd"], 4), "stopped_early": stop.is_set()}
    ctx.check()


def start(plan_id_or_ids, cfg):
    params = dict(cfg)
    if isinstance(plan_id_or_ids, str):
        params["plan_ids"] = [plan_id_or_ids]
    names = []
    for jp in params["judge_profile_ids"]:
        with db.Session() as s:
            p = s.get(db.Profile, jp)
            names.append(p.name if p else jp)
    return jobs.submit("judge", f"Judge with {', '.join(names)}", run_judge, params, ref=",".join(params.get("plan_ids") or []))


def judge_families():
    """profile id -> family, for the self-preference statistic."""
    out = {}
    with db.Session() as s:
        for p in s.query(db.Profile).all():
            m = s.get(db.Model, p.model_id) if p.model_id else None
            v = s.get(db.Provider, p.provider_id) if p.provider_id else None
            out[p.id] = family_of(db.row(p), db.row(m) if m else None, db.row(v) if v else None)
    return out


def now():
    return time.time()

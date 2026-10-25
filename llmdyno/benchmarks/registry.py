"""Benchmarks (built-in and user-created), suites, validation and zip import/export."""
import io
import json
import re
import shutil
import zipfile
from pathlib import Path

from .. import config, db

BUILTIN_DIR = Path(__file__).resolve().parent / "builtin"
COMMON_DIR = Path(__file__).resolve().parent / "common"
BUILTIN_SUITES = [
    {"id": "suite_round1", "name": "Round 1: five tasks", "builtin": True,
     "description": "The five tasks from LLMDyno's first study: two web apps, a long iterative build, data/ML and bug fixing.",
     "benchmark_ids": ["t1_flask_site", "t2_fastapi_worker_ts", "t3_long_iterative", "t4_data_ml", "t5_bugfix_semver"]},
    {"id": "suite_smoke", "name": "Smoke test", "builtin": True,
     "description": "One two-minute task to check that a profile and harness work end to end.",
     "benchmark_ids": ["t0_smoke_cli"]},
    {"id": "suite_quick", "name": "Quick three", "builtin": True,
     "description": "Fast coverage: the smoke task, the Flask site and the bug fixes (about 5 minutes per profile locally).",
     "benchmark_ids": ["t0_smoke_cli", "t1_flask_site", "t5_bugfix_semver"]},
    {"id": "suite_web", "name": "Web apps", "builtin": True, "description": "Both web-application tasks.",
     "benchmark_ids": ["t1_flask_site", "t2_fastapi_worker_ts"]},
]
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]{2,60}$")


def user_dir():
    return config.DATA / "benchmarks"


def _load(folder, builtin):
    try:
        b = json.loads((folder / "benchmark.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    b["builtin"] = builtin
    b["dir"] = str(folder)
    b["n_stages"] = len(b.get("stages", []))
    b["has_reference"] = bool(b.get("reference")) and (folder / b["reference"]).exists()
    b["has_probes"] = bool(b.get("probes")) and (folder / b["probes"]).exists()
    return b


def all_benchmarks():
    out = []
    for root, builtin in ((BUILTIN_DIR, True), (user_dir(), False)):
        if not root.exists():
            continue
        for d in sorted(root.iterdir()):
            if d.is_dir() and (d / "benchmark.json").exists():
                b = _load(d, builtin)
                if b:
                    out.append(b)
    return out


def get(bid):
    for b in all_benchmarks():
        if b["id"] == bid:
            return b
    raise KeyError(bid)


def prompt_texts(b):
    d = Path(b["dir"])
    return [(d / s["prompt"]).read_text(encoding="utf-8") for s in b["stages"]]


def file_tree(b, sub, limit=400):
    root = Path(b["dir"]) / sub if sub else None
    if not root or not root.exists():
        return []
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            out.append({"path": str(p.relative_to(root)).replace("\\", "/"), "size": p.stat().st_size})
            if len(out) >= limit:
                break
    return out


def detail(bid):
    b = get(bid)
    return {**b, "prompts": prompt_texts(b), "workspace_files": file_tree(b, b.get("workspace")),
            "grader_files": file_tree(b, "grader"), "reference_files": file_tree(b, b.get("reference")),
            "stage_files": file_tree(b, "stage_files")}


# ------------------------------------------------------------------ suites
def suites():
    with db.Session() as s:
        custom = [db.row(x) for x in s.query(db.Suite).order_by(db.Suite.created_at).all()]
    return BUILTIN_SUITES + custom


def expand(ids):
    """Benchmark ids from a mix of benchmark ids and suite ids, order preserved, duplicates removed."""
    out, by_suite = [], {s["id"]: s for s in suites()}
    for i in ids:
        for b in (by_suite[i]["benchmark_ids"] if i in by_suite else [i]):
            if b not in out:
                out.append(b)
    return out


# ------------------------------------------------------------------ custom benchmarks
def _safe_rel(path):
    p = Path(path)
    if p.is_absolute() or ".." in p.parts or not str(path).strip():
        raise ValueError(f"invalid file path: {path}")
    return p


CHECK_FIELDS = {"file_exists": ("path",), "file_contains": ("path", "text"), "glob": ("pattern",),
                "command": ("cmd",), "test_count": ("path",)}


def check_errors(checks):
    """A check with an empty path or pattern would pass on any workspace, so it is rejected up front."""
    errs = []
    for i, c in enumerate(checks, 1):
        label = c.get("name") or f"check {i}"
        need = CHECK_FIELDS.get(c.get("type"))
        if need is None:
            errs.append(f"{label}: unknown type {c.get('type')!r}")
            continue
        missing = [f for f in need if not str(c.get(f) or "").strip() or str(c.get(f)).strip() in (".", "./", "*", "**")]
        if missing:
            errs.append(f"{label}: {', '.join(missing)} is required")
    return errs


def save_custom(spec, overwrite=False):
    """Create or replace a user benchmark from the UI form.

    spec: id, title, summary, description, category, difficulty, languages, tags, stages [{prompt, timeout_s}],
    workspace_files {path: text}, hidden_tests {path: text}, checks [...], reference_files {path: text},
    min_context, expected_minutes."""
    bid = spec.get("id", "")
    errs = []
    if not ID_RE.match(bid):
        errs.append("id must be 3-61 lowercase letters, digits or underscores")
    if any(b["id"] == bid and b["builtin"] for b in all_benchmarks()):
        errs.append("id is used by a built-in benchmark")
    if not spec.get("title"):
        errs.append("title is required")
    stages = spec.get("stages") or []
    if not stages or not all((s.get("prompt") or "").strip() for s in stages):
        errs.append("at least one stage with a prompt is required")
    if not spec.get("hidden_tests") and not spec.get("checks"):
        errs.append("add hidden tests or at least one check, otherwise nothing can be graded")
    errs += check_errors(spec.get("checks") or [])
    if errs:
        raise ValueError("; ".join(errs))
    d = user_dir() / bid
    if d.exists() and not overwrite:
        raise FileExistsError(f"a benchmark with id {bid} already exists")
    tmp = d.with_name(d.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "prompts").mkdir(parents=True)
    st = []
    for i, s in enumerate(stages, 1):
        (tmp / "prompts" / f"stage{i}.md").write_text(s["prompt"], encoding="utf-8")
        st.append({"prompt": f"prompts/stage{i}.md", "timeout_s": int(s.get("timeout_s") or 1200)})
    for key, sub in (("workspace_files", "workspace"), ("hidden_tests", "grader/tests"), ("reference_files", "reference")):
        for path, text in (spec.get(key) or {}).items():
            f = tmp / sub / _safe_rel(path)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8")
    (tmp / "grader").mkdir(exist_ok=True)
    (tmp / "grader" / "spec.json").write_text(json.dumps(
        {"tests": "grader/tests" if spec.get("hidden_tests") else None, "checks": spec.get("checks") or []}, indent=2),
        encoding="utf-8")
    meta = {"id": bid, "version": int(spec.get("version") or 1), "title": spec["title"], "summary": spec.get("summary", ""),
            "description": spec.get("description", ""), "category": spec.get("category") or "Custom",
            "difficulty": spec.get("difficulty") or "medium", "languages": spec.get("languages") or [],
            "tags": spec.get("tags") or [], "stages": st, "grade_each_stage": bool(spec.get("grade_each_stage")),
            "grader": {"type": "spec", "path": "grader/spec.json", "timeout_s": int(spec.get("grader_timeout_s") or 600)},
            "min_context": int(spec.get("min_context") or 32000),
            "expected_minutes": spec.get("expected_minutes") or {"local": 5, "cloud": 3},
            "workspace": "workspace" if spec.get("workspace_files") else None, "decompress": [],
            "reference": "reference" if spec.get("reference_files") else None, "probes": None,
            "quality": {"language": spec.get("quality_language") or "python"}, "origin": "custom"}
    (tmp / "benchmark.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    shutil.rmtree(d, ignore_errors=True)
    tmp.rename(d)
    return get(bid)


def custom_spec(bid):
    """The editable form of a user benchmark (inverse of save_custom)."""
    b = get(bid)
    if b["builtin"]:
        raise PermissionError("built-in benchmarks are read-only; duplicate it to edit")
    d = Path(b["dir"])

    def read(sub):
        if not (d / sub).exists():
            return {}
        return {str(p.relative_to(d / sub)).replace("\\", "/"): p.read_text(encoding="utf-8", errors="replace")
                for p in sorted((d / sub).rglob("*")) if p.is_file()}
    spec = json.loads((d / "grader" / "spec.json").read_text(encoding="utf-8"))
    return {**{k: b.get(k) for k in ("id", "title", "summary", "description", "category", "difficulty", "languages",
                                     "tags", "min_context", "expected_minutes", "grade_each_stage", "version")},
            "stages": [{"prompt": t, "timeout_s": s["timeout_s"]} for t, s in zip(prompt_texts(b), b["stages"])],
            "workspace_files": read("workspace"), "hidden_tests": read("grader/tests"),
            "reference_files": read("reference"), "checks": spec.get("checks", [])}


def duplicate(bid, new_id):
    b = get(bid)
    src = Path(b["dir"])
    dst = user_dir() / new_id
    if not ID_RE.match(new_id) or dst.exists() or any(x["id"] == new_id for x in all_benchmarks()):
        raise ValueError("choose a new, unused id (3-61 lowercase letters, digits or underscores)")
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
    meta = json.loads((dst / "benchmark.json").read_text(encoding="utf-8"))
    meta.update({"id": new_id, "title": meta["title"] + " (copy)", "origin": f"copy of {bid}"})
    (dst / "benchmark.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return get(new_id)


def delete_custom(bid):
    b = get(bid)
    if b["builtin"]:
        raise PermissionError("built-in benchmarks cannot be deleted")
    shutil.rmtree(b["dir"])


def export_zip(bid):
    b = get(bid)
    buf = io.BytesIO()
    root = Path(b["dir"])
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(root.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                z.write(p, f"{bid}/{p.relative_to(root).as_posix()}")
    return buf.getvalue()


def import_zip(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        metas = [n for n in names if n.count("/") == 1 and n.endswith("/benchmark.json")]
        if len(metas) != 1:
            raise ValueError("the zip must contain exactly one <id>/benchmark.json")
        top = metas[0].split("/")[0]
        meta = json.loads(z.read(metas[0]))
        bid = meta.get("id")
        if bid != top or not ID_RE.match(bid or ""):
            raise ValueError("benchmark.json id must match the folder name and be a valid id")
        if any(b["id"] == bid for b in all_benchmarks()):
            raise FileExistsError(f"benchmark {bid} already exists; delete or rename it first")
        if meta.get("grader", {}).get("type") not in ("spec", "script"):
            raise ValueError("unsupported grader type")
        dst = user_dir() / bid
        for n in names:
            if n.endswith("/"):
                continue
            rel = _safe_rel(n)
            if rel.parts[0] != top:
                raise ValueError("all files must live under the benchmark folder")
            out = dst / Path(*rel.parts[1:])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(z.read(n))
    meta["origin"] = "imported"
    (dst / "benchmark.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return get(bid)

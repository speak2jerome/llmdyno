"""Aider polyglot benchmark: 225 hard Exercism exercises in C++, Go, Java, JavaScript, Python and Rust.

The importer downloads github.com/Aider-AI/polyglot-benchmark, turns every exercise into an LLMDyno benchmark (the
stub and test files as the starting workspace, the original tests kept aside for grading, the Exercism example as the
reference solution) and prepares the build context for the llmdyno-polyglot toolchain image. Tests run exactly as
in the Aider benchmark: every test enabled (Java @Disabled and JavaScript xtest removed, Rust --include-ignored,
C++ EXERCISM_RUN_ALL_TESTS). An exercise is solved when all of its tests pass.

Aider's leaderboard gives the model two tries with the test output in between; LLMDyno agents run the tests
themselves as often as they like within the time limit, so scores are close to but not the same as Aider's."""
import io
import json
import re
import shutil
import tarfile
import time
from pathlib import Path

import httpx

from .. import config, db
from ..harnesses import images
from . import registry

REPO = "Aider-AI/polyglot-benchmark"
TARBALL = f"https://codeload.github.com/{REPO}/tar.gz/refs/heads/main"
HOMEPAGE = "https://aider.chat/docs/leaderboards/"
IMAGE = "llmdyno-polyglot:1"
LANGS = {"cpp": "C++", "go": "Go", "java": "Java", "javascript": "JavaScript", "python": "Python", "rust": "Rust"}
TEST_CMD = {"cpp": "`cmake` and `make` in build/", "go": "`go test ./...`", "java": "`./gradlew test --offline`",
            "javascript": "`jest`", "python": "`pytest`", "rust": "`cargo test -- --include-ignored`"}
# .approaches and .articles are Exercism's community write-ups of solutions: hints the agent must not see
SKIP_PARTS = {".meta", ".docs", ".approaches", ".articles", "node_modules", "build", "target", ".gradle", "__pycache__"}
CMAKE_NAME_LINE = "get_filename_component(exercise ${CMAKE_CURRENT_SOURCE_DIR} NAME)"

PROMPT = """{instructions}

## Your task

Use the instructions above to modify the supplied files: {solution}.
Don't change the names of existing functions or classes, as they may be referenced from other code like unit tests.
Only use the standard library: there is no network access, so don't try to install packages.

The tests are in {tests}. Run them with `polyglot-test` from the workspace (it runs {cmd} with every test
enabled) and keep going until they all pass. Don't modify the test files.
"""


def import_dir():
    return config.DATA / "imports" / "polyglot"


def bench_id(lang, slug):
    return "pg_" + re.sub(r"[^a-z0-9]+", "_", f"{lang}_{slug}".lower()).strip("_")[:58]


def enable_all_tests(lang, text):
    if lang == "java":
        return re.sub(r'^\s*@Disabled\([^)]*\)\s*\n', "", text, flags=re.M)
    if lang == "javascript":
        return re.sub(r"\bxtest\(", "test(", re.sub(r"\bxit\(", "it(", text))
    return text


def _read(p):
    return p.read_text(encoding="utf-8", errors="replace")


def exercise_to_benchmark(lang, ex_dir):
    """(benchmark.json dict, {relative path: bytes}) for one exercise folder. Pure apart from reading ex_dir."""
    ex_dir = Path(ex_dir)
    slug = ex_dir.name
    cfg = json.loads(_read(ex_dir / ".meta" / "config.json"))
    files = cfg.get("files") or {}
    solution, test_files, example = files.get("solution") or [], files.get("test") or [], files.get("example") or []
    # "editor" files are read-only test data (Go's cases_test.go): restored before grading like the tests
    protected = test_files + [e for e in files.get("editor") or [] if e not in test_files]
    if not solution or not test_files:
        raise ValueError(f"{lang}/{slug}: config.json lists no solution or test files")
    docs = ex_dir / ".docs"
    parts = [_read(docs / n) for n in ("introduction.md", "instructions.md", "instructions.append.md") if (docs / n).exists()]
    instructions = "\n\n".join(x.strip() for x in parts) or f"# {slug}"
    out = {}
    for f in sorted(ex_dir.rglob("*")):
        rel = f.relative_to(ex_dir)
        if not f.is_file() or SKIP_PARTS & set(rel.parts):
            continue
        rel_s = rel.as_posix()
        data = f.read_bytes()
        if rel_s in protected:
            if rel_s in test_files:
                data = enable_all_tests(lang, data.decode("utf-8", "replace")).encode("utf-8")
            out[f"grader/tests/{rel_s}"] = data
        if lang == "cpp" and rel_s == "CMakeLists.txt":
            # Exercism derives the test file name from the folder name, which is /workspace or /work here
            data = data.decode("utf-8", "replace").replace(
                CMAKE_NAME_LINE, f'set(exercise "{slug}")  # LLMDyno: fixed, the folder is not named after it').encode()
        out[f"workspace/{rel_s}"] = data
    if not all(f"workspace/{t}" in out for t in test_files):
        raise ValueError(f"{lang}/{slug}: a listed test file is missing")
    # the Exercism example is the reference: map it onto the solution paths
    ref = {}
    if len(example) == 1 and len(solution) == 1:
        ref[solution[0]] = example[0]
    else:
        # same file name (Java), else the only example with the same extension (C++ .cpp/.h, Rust src/lib.rs)
        by_name = {Path(e).name: e for e in example}
        for sol in solution:
            suffix = Path(sol).suffix
            same_ext = [e for e in example if Path(e).suffix == suffix]
            if Path(sol).name in by_name:
                ref[sol] = by_name[Path(sol).name]
            elif len(same_ext) == 1 and sum(Path(x).suffix == suffix for x in solution) == 1:
                ref[sol] = same_ext[0]
    if lang == "rust" and (ex_dir / ".meta" / "Cargo-example.toml").exists():
        ref["Cargo.toml"] = ".meta/Cargo-example.toml"      # the reference needs crates the stub's manifest lacks
    for sol, ex in ref.items():
        if (ex_dir / ex).exists():
            out[f"reference/{sol}"] = (ex_dir / ex).read_bytes()
    title = (cfg.get("blurb") or "").strip()
    bench = {
        "id": bench_id(lang, slug), "version": 1, "title": f"Polyglot {LANGS[lang]}: {slug}",
        "summary": title[:160] or f"Exercism {LANGS[lang]} exercise",
        "description": (f"Exercism {LANGS[lang]} exercise from Aider's polyglot benchmark. "
                        + (f"{title} " if title else "") + f"The agent edits {', '.join(solution)}; the original tests "
                        f"({', '.join(test_files)}) run with every test enabled, and it is solved only if all pass."),
        "category": "Aider polyglot", "difficulty": "hard", "languages": [LANGS[lang]],
        "tags": ["polyglot", lang, "exercism"], "stages": [{"prompt": "prompts/stage1.md", "timeout_s": 900}],
        "grade_each_stage": False, "grader": {"type": "polyglot", "path": "grader/spec.json", "timeout_s": 600},
        "min_context": 32000, "expected_minutes": {"local": 6, "cloud": 3}, "workspace": "workspace",
        "decompress": [], "reference": "reference" if ref else None, "probes": None, "quality": None,
        "env": {"type": "polyglot", "image": IMAGE, "workspace": "bind", "grader_in_env": True, "local_image": True},
        "origin": "Aider polyglot", "source": {"name": "Aider polyglot benchmark", "url": HOMEPAGE,
                                               "repo": f"https://github.com/{REPO}", "license": "MIT (Exercism)",
                                               "exercise": f"{lang}/{slug}"},
        "reference_tokens": {"prompt": 60000, "output": 6000, "cache_hit": 0.85},
    }
    spec = {"language": lang, "test_files": protected, "solution_files": solution, "timeout_s": 480}
    prompt = PROMPT.format(instructions=instructions, solution=", ".join(solution), tests=", ".join(test_files),
                           cmd=TEST_CMD[lang])
    out["benchmark.json"] = json.dumps(bench, indent=2).encode()
    out["grader/spec.json"] = json.dumps(spec, indent=2).encode()
    out["prompts/stage1.md"] = prompt.encode()
    return bench, out


def _safe_extract(data, dest):
    dest = Path(dest).resolve()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        for m in tf.getmembers():
            target = (dest / m.name).resolve()
            if not target.is_relative_to(dest) or m.issym() or m.islnk() or m.isdev():
                continue
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif m.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with tf.extractfile(m) as fi, open(target, "wb") as fo:
                    shutil.copyfileobj(fi, fo)


def exercises(src_root):
    for lang in LANGS:
        base = Path(src_root) / lang / "exercises" / "practice"
        if base.exists():
            for d in sorted(base.iterdir()):
                if (d / ".meta" / "config.json").exists():
                    yield lang, d


def write_warm_context(src_root, ctx_dir):
    """Distinct Gradle / npm / Cargo setups for the toolchain image to pre-fetch."""
    ctx_dir = Path(ctx_dir)
    shutil.rmtree(ctx_dir / "warm", ignore_errors=True)
    seen_gradle, seen_cargo, pkg = {}, {}, None
    for lang, d in exercises(src_root):
        if lang == "java" and (d / "build.gradle").exists():
            key = _read(d / "build.gradle") + (_read(d / "gradle/wrapper/gradle-wrapper.properties")
                                               if (d / "gradle/wrapper/gradle-wrapper.properties").exists() else "")
            if key not in seen_gradle:
                tgt = ctx_dir / "warm" / "java" / f"g{len(seen_gradle)}"
                shutil.copytree(d, tgt, ignore=shutil.ignore_patterns(".docs", "build", ".gradle"))
                bench, files = exercise_to_benchmark(lang, d)
                for k, v in files.items():           # put the reference in place so the warm-up compiles and tests
                    if k.startswith("reference/"):
                        (tgt / k[len("reference/"):]).parent.mkdir(parents=True, exist_ok=True)
                        (tgt / k[len("reference/"):]).write_bytes(v)
                seen_gradle[key] = tgt
        elif lang == "rust":
            for manifest in (d / "Cargo.toml", d / ".meta" / "Cargo-example.toml"):
                if not manifest.exists():
                    continue
                toml = _read(manifest)
                deps = re.search(r"^\[(dev-)?dependencies\]\s*\n\s*[A-Za-z]", toml, flags=re.M)
                if deps and toml not in seen_cargo:
                    tgt = ctx_dir / "warm" / "rust" / f"c{len(seen_cargo)}"
                    (tgt / "src").mkdir(parents=True, exist_ok=True)
                    (tgt / "Cargo.toml").write_text(toml, encoding="utf-8")
                    (tgt / "src" / "lib.rs").write_text("", encoding="utf-8")
                    seen_cargo[toml] = tgt
        elif lang == "javascript" and pkg is None and (d / "package.json").exists():
            pkg = d / "package.json"
    (ctx_dir / "warm" / "javascript").mkdir(parents=True, exist_ok=True)
    (ctx_dir / "warm" / "rust").mkdir(parents=True, exist_ok=True)
    (ctx_dir / "warm" / "java").mkdir(parents=True, exist_ok=True)
    if pkg:
        shutil.copyfile(pkg, ctx_dir / "warm" / "javascript" / "package.json")
    else:
        (ctx_dir / "warm" / "javascript" / "package.json").write_text('{"name": "none", "private": true}')
    shutil.copyfile(images.DOCKER_DIR / "polyglot-test.sh", ctx_dir / "polyglot-test.sh")
    return {"gradle_setups": len(seen_gradle), "cargo_setups": len(seen_cargo), "package_json": bool(pkg)}


def import_job(ctx):
    """Job: download the polyglot repo and import its exercises (all, or the chosen languages)."""
    langs = [x for x in (ctx.params.get("languages") or list(LANGS)) if x in LANGS]
    root = import_dir()
    ctx.log(f"downloading {TARBALL}")
    with httpx.Client(timeout=120, follow_redirects=True, headers={"User-Agent": "LLMDyno"}) as c:
        r = c.get(TARBALL)
        r.raise_for_status()
        data = r.content
    ctx.log(f"{len(data) / 2**20:.1f} MB downloaded")
    shutil.rmtree(root / "src", ignore_errors=True)
    _safe_extract(data, root / "src")
    tops = [d for d in (root / "src").iterdir() if d.is_dir()]
    src_root = tops[0] if len(tops) == 1 else root / "src"
    ctx.progress(0.2, "converting exercises")
    made, errors, by_lang = [], [], {}
    todo = [(lang, d) for lang, d in exercises(src_root) if lang in langs]
    for i, (lang, d) in enumerate(todo):
        ctx.check()
        try:
            bench, files = exercise_to_benchmark(lang, d)
        except (ValueError, KeyError, OSError) as e:
            errors.append(str(e))
            continue
        dest = registry.user_dir() / bench["id"]
        shutil.rmtree(dest, ignore_errors=True)
        for rel, blob in files.items():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            (dest / rel).write_bytes(blob)
        made.append(bench["id"])
        by_lang.setdefault(lang, []).append(bench["id"])
        ctx.progress(0.2 + 0.7 * (i + 1) / len(todo), f"{i + 1}/{len(todo)} exercises")
    warm = write_warm_context(src_root, root / "context")
    with db.Session() as s:
        suites = [("suite_polyglot_all", f"Aider polyglot ({len(made)})", made)]
        suites += [(f"suite_polyglot_{lang}", f"Aider polyglot: {LANGS[lang]} ({len(ids)})", ids)
                   for lang, ids in by_lang.items()]
        for sid, name, ids in suites:
            sx = s.get(db.Suite, sid) or db.Suite(id=sid, created_at=time.time())
            sx.name, sx.benchmark_ids = name, ids
            sx.description = ("Hard Exercism exercises from Aider's polyglot benchmark; solved means every test "
                              "passes. Needs the polyglot toolchain image (Setup page).")
            s.merge(sx)
        s.commit()
    ctx.result = {"imported": len(made), "by_language": {k: len(v) for k, v in by_lang.items()},
                  "errors": errors[:20], "warm": warm}
    ctx.log(f"imported {len(made)} exercises" + (f", {len(errors)} skipped" if errors else ""))


def context_ready():
    return (import_dir() / "context" / "warm").exists()


def build_image(ctx):
    """Job: build llmdyno-polyglot:1 (Go, Rust, JDK + Gradle, CMake, jest; about 4 GB)."""
    if not context_ready():
        raise RuntimeError("import the polyglot benchmark first: the image is built from its exercises' build files")
    if not images.image_exists(images.SANDBOX):
        ctx.log("sandbox base missing: building it first")
        images.build_sandbox(ctx)
    images._stream_build(ctx, ["docker", "build", "-t", IMAGE, "--build-arg", f"BASE={images.SANDBOX}",
                               "-f", str(images.DOCKER_DIR / "polyglot.Dockerfile")], import_dir() / "context")
    ctx.result = images.image_exists(IMAGE) or {}

"""Static code-quality analysis of what an agent wrote in one workspace.

Runs inside the llmdyno-quality image (offline):
  python /q/analyze.py --work /work --template /template [--stage-files /stage_files] --task <id>
Only files the agent created or changed are measured (compared with the task's starting files).
Prints one JSON object.
"""
import argparse
import ast
import difflib
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tokenize
from pathlib import Path

SKIP_DIRS = {"__pycache__", ".pytest_cache", "node_modules", ".git", "dist", "output", "data", "instance",
             ".venv", "session", ".ruff_cache", ".mypy_cache", "htmlcov"}
CODE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".html", ".css", ".sql"}
DOC_EXT = {".md", ".json", ".txt", ".toml", ".cfg", ".ini", ".yml", ".yaml"}  # shown to reviewers, not code-scored
RUFF_RULES = "F,E9,E722,B,SIM,C901,PLR0912,PLR0913,PLR0915,PLW,UP,RET,TRY"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def is_test(rel):
    name = Path(rel).name
    return rel.startswith("tests/") or "/tests/" in rel or name.startswith("test_") or name.endswith("_test.py") \
        or name == "conftest.py"


def collect(work, bases, base_of=None):
    """Files the agent created or changed; base_of (if given) receives rel -> original file for modified ones."""
    base_files = {}
    for b in bases:
        if b and b.exists():
            for p in b.rglob("*"):
                if p.is_file():
                    base_files[str(p.relative_to(b)).replace("\\", "/")] = p
    authored = {}
    for p in work.rglob("*"):
        rel = str(p.relative_to(work)).replace("\\", "/")
        if not p.is_file() or any(part in SKIP_DIRS for part in Path(rel).parts):
            continue
        if p.suffix not in CODE_EXT and p.suffix not in DOC_EXT:
            continue
        if p.stat().st_size > (400_000 if p.suffix in CODE_EXT else 60_000):
            continue
        if rel in base_files:
            if sha(base_files[rel]) == sha(p):
                continue
            old = base_files[rel].read_text(errors="replace").splitlines()
            new = p.read_text(errors="replace").splitlines()
            added = removed = 0
            for line in difflib.unified_diff(old, new, lineterm="", n=0):
                if line.startswith("+") and not line.startswith("+++"):
                    added += 1
                elif line.startswith("-") and not line.startswith("---"):
                    removed += 1
            authored[rel] = {"status": "modified", "added": added, "removed": removed}
            if base_of is not None:
                base_of[rel] = base_files[rel]
        else:
            authored[rel] = {"status": "new"}
    return authored


def py_sloc(src):
    """Non-blank, non-comment, non-docstring lines."""
    lines = set()
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return sum(1 for ln in src.splitlines() if ln.strip() and not ln.strip().startswith("#"))
    prev = None
    for t in toks:
        if t.type in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER):
            continue
        if t.type == tokenize.STRING and (prev is None or prev.type in (tokenize.INDENT, tokenize.NEWLINE, tokenize.DEDENT, tokenize.NL)):
            prev = t
            continue  # docstring / bare string statement
        for ln in range(t.start[0], t.end[0] + 1):
            lines.add(ln)
        prev = t
    return len(lines)


def nesting_depth(node, depth=0):
    best = depth
    for ch in ast.iter_child_nodes(node):
        inc = isinstance(ch, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.Match))
        best = max(best, nesting_depth(ch, depth + (1 if inc else 0)))
    return best


def py_structure(src, test_file):
    out = {"functions": 0, "classes": 0, "func_lengths": [], "typed_funcs": 0, "doc_funcs": 0, "public_funcs": 0,
           "max_nesting": 0, "syntax_error": False}
    try:
        tree = ast.parse(src)
    except SyntaxError:
        out["syntax_error"] = True
        return out
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out["functions"] += 1
            out["func_lengths"].append((node.end_lineno or node.lineno) - node.lineno + 1)
            out["max_nesting"] = max(out["max_nesting"], nesting_depth(node))
            if test_file:
                continue
            args = [a for a in node.args.args + node.args.kwonlyargs + node.args.posonlyargs if a.arg not in ("self", "cls")]
            typed = node.returns is not None and all(a.annotation is not None for a in args)
            out["typed_funcs"] += typed
            if not node.name.startswith("_"):
                out["public_funcs"] += 1
                out["doc_funcs"] += ast.get_docstring(node) is not None
        elif isinstance(node, ast.ClassDef):
            out["classes"] += 1
    return out


def ts_metrics(src):
    lines = [ln.strip() for ln in src.splitlines()]
    sloc = sum(1 for ln in lines if ln and not ln.startswith(("//", "/*", "*")))
    return {"sloc": sloc,
            "any_usages": len(re.findall(r":\s*any\b|\bas\s+any\b|<any>", src)),
            "ts_ignores": len(re.findall(r"@ts-(ignore|nocheck)", src)),
            "functions": len(re.findall(r"\bfunction\b|=>", src))}


def duplication(texts, window=6):
    """Share of 6-line windows (normalized, non-trivial lines) that occur more than once across files."""
    seen, total = {}, 0
    for src in texts:
        norm = [re.sub(r"\s+", " ", ln.strip()) for ln in src.splitlines()]
        norm = [ln for ln in norm if ln and not ln.startswith(("#", "import ", "from ", "//")) and len(ln) > 3]
        for i in range(len(norm) - window + 1):
            h = hashlib.md5("\n".join(norm[i:i + window]).encode()).hexdigest()
            seen[h] = seen.get(h, 0) + 1
            total += 1
    dup = sum(c for c in seen.values() if c > 1)
    return round(dup / total, 4) if total else 0.0


def run(cmd, cwd, timeout=180):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/work")
    ap.add_argument("--template", default="/template")
    ap.add_argument("--stage-files", default="/stage_files")
    ap.add_argument("--task", required=True)
    a = ap.parse_args()
    src_work = Path(a.work)
    work = Path("/tmp/qwork")
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(src_work, work, ignore=shutil.ignore_patterns("node_modules", "__pycache__", ".pytest_cache"))
    bases = [Path(a.template)] + sorted(Path(a.stage_files).glob("stage*")) if Path(a.stage_files).exists() else [Path(a.template)]
    base_of = {}
    authored = collect(work, bases, base_of)
    # originals of modified files, so findings that were already in the starting code are not charged to the agent
    base_work = Path("/tmp/qbase")
    shutil.rmtree(base_work, ignore_errors=True)
    for rel, src in base_of.items():
        (base_work / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, base_work / rel)

    py_src, py_test_src, files_out = [], [], {}
    func_lengths, totals = [], {"functions": 0, "classes": 0, "typed": 0, "public": 0, "doc": 0}
    sloc = {"python": 0, "python_tests": 0, "typescript": 0, "html_css": 0, "other": 0}
    ts = {"any_usages": 0, "ts_ignores": 0}
    max_nesting = 0
    syntax_errors = 0
    for rel, info in sorted(authored.items()):
        p = work / rel
        text = p.read_text(errors="replace")
        rec = dict(info)
        if p.suffix == ".py":
            test = is_test(rel)
            n = py_sloc(text)
            st = py_structure(text, test)
            rec.update({"sloc": n, "test": test, "functions": st["functions"],
                        "max_func_len": max(st["func_lengths"] or [0]), "syntax_error": st["syntax_error"]})
            syntax_errors += st["syntax_error"]
            if test:
                sloc["python_tests"] += n
                py_test_src.append(text)
            else:
                sloc["python"] += n
                py_src.append(text)
                func_lengths += st["func_lengths"]
                totals["functions"] += st["functions"]
                totals["classes"] += st["classes"]
                totals["typed"] += st["typed_funcs"]
                totals["public"] += st["public_funcs"]
                totals["doc"] += st["doc_funcs"]
                max_nesting = max(max_nesting, st["max_nesting"])
        elif p.suffix in (".ts", ".tsx", ".js", ".jsx"):
            m = ts_metrics(text)
            rec.update(m)
            sloc["typescript"] += m["sloc"]
            ts["any_usages"] += m["any_usages"]
            ts["ts_ignores"] += m["ts_ignores"]
        elif p.suffix in (".html", ".css"):
            n = sum(1 for ln in text.splitlines() if ln.strip())
            rec["sloc"] = n
            sloc["html_css"] += n
        else:
            rec["sloc"] = sum(1 for ln in text.splitlines() if ln.strip())
            sloc["other"] += rec["sloc"]
        files_out[rel] = rec

    py_files = [r for r in authored if r.endswith(".py")]
    src_files = [r for r in py_files if not is_test(r)]

    # radon: complexity + maintainability (non-test code)
    cc_scores, mi_scores = [], []
    if src_files:
        code, out, _ = run([sys.executable, "-m", "radon", "cc", "-j", "-s", *src_files], work)
        try:
            for blocks in json.loads(out or "{}").values():
                if isinstance(blocks, list):
                    cc_scores += [b["complexity"] for b in blocks if isinstance(b, dict) and b.get("type") in ("function", "method")]
        except json.JSONDecodeError:
            pass
        code, out, _ = run([sys.executable, "-m", "radon", "mi", "-j", *src_files], work)
        try:
            mi_scores = [v["mi"] for v in json.loads(out or "{}").values() if isinstance(v, dict) and "mi" in v]
        except json.JSONDecodeError:
            pass

    # ruff (all authored python, tests included: unused imports/variables in tests are still sloppy)
    ruff_by_code = {}
    if py_files:
        _, out, _ = run(["ruff", "check", "--no-cache", "--isolated", "--select", RUFF_RULES, "--line-length", "120",
                         "--output-format", "json", "--exit-zero", *py_files], work)
        try:
            for f in json.loads(out or "[]"):
                ruff_by_code[f["code"]] = ruff_by_code.get(f["code"], 0) + 1
        except json.JSONDecodeError:
            pass
        base_py = [r for r in py_files if r in base_of]
        if base_py:
            _, out, _ = run(["ruff", "check", "--no-cache", "--isolated", "--select", RUFF_RULES, "--line-length", "120",
                             "--output-format", "json", "--exit-zero", *base_py], base_work)
            try:
                for f in json.loads(out or "[]"):
                    if f["code"] in ruff_by_code:
                        ruff_by_code[f["code"]] -= 1
            except json.JSONDecodeError:
                pass
            ruff_by_code = {k: v for k, v in ruff_by_code.items() if v > 0}

    # bandit (non-test code), minus what the original versions of modified files already had
    bandit = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    bandit_issues = []
    if src_files:
        base_src = [r for r in src_files if r in base_of]
        pre = {}
        if base_src:
            _, out, _ = run(["bandit", "-q", "-f", "json", "-s", "B101", *base_src], base_work)
            try:
                for r in json.loads(out or "{}").get("results", []):
                    k = (r["filename"], r["test_id"])
                    pre[k] = pre.get(k, 0) + 1
            except json.JSONDecodeError:
                pass
        _, out, _ = run(["bandit", "-q", "-f", "json", "-s", "B101", *src_files], work)
        try:
            for r in json.loads(out or "{}").get("results", []):
                k = (r["filename"], r["test_id"])
                if pre.get(k):
                    pre[k] -= 1
                    continue
                bandit[r["issue_severity"]] = bandit.get(r["issue_severity"], 0) + 1
                bandit_issues.append(f"{r['test_id']} {r['issue_text'][:80]} ({r['filename']}:{r['line_number']})")
        except json.JSONDecodeError:
            pass

    # vulture: unused code (non-test)
    dead = 0
    if src_files:
        _, out, _ = run(["vulture", "--min-confidence", "80", *src_files], work)
        dead = sum(1 for ln in out.splitlines() if ln.strip())

    # the agent's own tests: count + how much of its own code they cover
    test_count = sum(len(re.findall(r"^\s*(?:async\s+)?def test_", t, flags=re.M)) for t in py_test_src)
    own_cov = None
    own_tests_pass = None
    test_files = [r for r in py_files if is_test(r) and Path(r).name != "conftest.py"]
    if test_files and src_files:
        code, out, err = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--timeout=60",
                              "--cov=.", "--cov-report=json:/tmp/cov.json", *test_files], work, timeout=240)
        own_tests_pass = code == 0
        try:
            cov = json.loads(Path("/tmp/cov.json").read_text())["files"]
            stmts = covered = 0
            for rel in src_files:
                f = cov.get(rel) or cov.get("./" + rel)
                if f:
                    stmts += f["summary"]["num_statements"]
                    covered += f["summary"]["covered_lines"]
            own_cov = round(covered / stmts, 4) if stmts else None
        except Exception:
            pass

    py_authored_lines = sum(v.get("added", 0) if v["status"] == "modified" else files_out[r].get("sloc", 0)
                            for r, v in authored.items() if r.endswith(".py"))
    readme = work / "README.md"
    summary = {
        "task": a.task,
        "files_authored": len(authored),
        "files_new": sum(1 for v in authored.values() if v["status"] == "new"),
        "files_modified": sum(1 for v in authored.values() if v["status"] == "modified"),
        "sloc": sloc,
        "sloc_total": sum(sloc.values()),
        "max_file_sloc": max([v.get("sloc", 0) for v in files_out.values()] or [0]),
        "functions": totals["functions"], "classes": totals["classes"],
        "avg_func_len": round(sum(func_lengths) / len(func_lengths), 1) if func_lengths else None,
        "max_func_len": max(func_lengths or [0]),
        "long_funcs_share": round(sum(1 for f in func_lengths if f > 50) / len(func_lengths), 3) if func_lengths else 0,
        "max_nesting": max_nesting,
        "cc_avg": round(sum(cc_scores) / len(cc_scores), 2) if cc_scores else None,
        "cc_max": max(cc_scores or [0]),
        "cc_over_10_share": round(sum(1 for c in cc_scores if c > 10) / len(cc_scores), 3) if cc_scores else 0,
        "mi_avg": round(sum(mi_scores) / len(mi_scores), 1) if mi_scores else None,
        "type_hint_coverage": round(totals["typed"] / totals["functions"], 3) if totals["functions"] else None,
        "docstring_coverage": round(totals["doc"] / totals["public"], 3) if totals["public"] else None,
        "ruff_findings": sum(ruff_by_code.values()),
        # per 100 lines the agent wrote: whole new files, only the added lines of modified ones
        "ruff_per_100_sloc": round(100 * sum(ruff_by_code.values()) / max(py_authored_lines, 1), 2),
        "ruff_by_code": dict(sorted(ruff_by_code.items(), key=lambda x: -x[1])),
        "bandit": bandit, "bandit_issues": bandit_issues[:10],
        "dead_code_findings": dead,
        "duplication": duplication(py_src),
        "syntax_errors": syntax_errors,
        "ts_any_usages": ts["any_usages"], "ts_ignores": ts["ts_ignores"],
        "own_test_functions": test_count,
        "own_tests_pass": own_tests_pass,
        "own_test_coverage": own_cov,
        "lib_lines_added": sum(v.get("added", 0) for r, v in authored.items() if v["status"] == "modified" and not is_test(r)),
        "lib_lines_removed": sum(v.get("removed", 0) for r, v in authored.items() if v["status"] == "modified" and not is_test(r)),
        "readme_lines": sum(1 for ln in readme.read_text(errors="replace").splitlines() if ln.strip()) if readme.exists() else 0,
    }
    print(json.dumps({"summary": summary, "files": files_out}))


if __name__ == "__main__":
    main()

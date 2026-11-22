"""The command line: every library call is a command, generated from the library itself so the two never drift.

    llmdyno                                  start the web app (same as `llmdyno serve`)
    llmdyno list-models --status ready       a library function: llmdyno.list_models(status="ready")
    llmdyno run transcript RUN_ID --view tool-calls
                                             a method: llmdyno.run(RUN_ID).transcript(), shown as its tool calls
    llmdyno bench "Qwen 32k" --benchmarks suite_quick --json

Function and method names become commands with dashes; parameters without a default are positional, the others
are --options (booleans are --flag / --no-flag). Keyword settings (cloud_model, local_model, estimate, …) go in
--set key=value, values read as JSON when they parse (--set ctx=32768 --set thinking=true). Add --json to any
command for machine-readable output; --data DIR picks the data folder. tests/test_cli.py checks that every public
library call has its command."""
from __future__ import annotations

import argparse
import inspect
import json
import re
import sys
import threading
import webbrowser
from pathlib import Path

# hand-written commands (unchanged from before the generated CLI)
CUSTOM = ("serve", "doctor", "specs", "ci", "token")
# library classes whose methods become `llmdyno <group> <method> ID ...`, with the function that finds one by id
GROUPS = {"Profile": ("profile", "profile"), "Model": ("model", "model"), "Provider": ("provider", "provider"),
          "Harness": ("harness", "harness"), "Benchmark": ("benchmark", "benchmark"), "Suite": ("suite", "suite"),
          "Plan": ("plan", "plan"), "Run": ("run", "run"), "Job": ("job", "job")}
GETTERS = {g for _, g in GROUPS.values()}
GETTER_OF = {group: getter for group, getter in GROUPS.values()}
NOT_COMMANDS = {"init", "connect", "disconnect", "connection",   # --data DIR, --url / --token instead
                "inspect_task", "import_inspect_samples"}     # take or return Python objects (Inspect tasks, datasets)
SKIP_METHODS = {"refresh", "to_dict", "get"}
NO_CLI_PARAMS = {"on_event", "_stop", "quiet"}            # callbacks, internals; quiet follows --json
PLURALS = {"plans", "benchmarks", "harnesses", "models", "runs", "judges", "languages", "instance_ids", "statuses",
           "files"}
RESULT_VIEWS = ("leaderboard", "runs", "cells", "rubric", "agreement", "reviews", "reference", "public")
TRANSCRIPT_VIEWS = ("turns", "tool-calls", "thinking", "final", "usage", "events")


def _first_sentence(obj) -> str:
    text = " ".join((inspect.getdoc(obj) or "").split())
    m = re.search(r"(?<!e\.g\.)(?<!i\.e\.)(?<=[.!?])\s", text)
    return text[:m.start()] if m else text


def _dash(name: str) -> str:
    return name.replace("_", "-")


def _ann(p) -> str:
    return str(p.annotation) if p.annotation is not inspect.Parameter.empty else ""


def _is_seq(name: str, p) -> bool:
    ann = _ann(p)
    if "Sequence" in ann or ann.startswith("list") or isinstance(p.default, (list, tuple)):
        return True
    return name in PLURALS and ann in ("", "Any", "typing.Any")


def _json_or_text(s: str):
    try:
        return json.loads(s)
    except ValueError:
        return s


def _add_params(parser: argparse.ArgumentParser, fn) -> list:
    """Arguments for fn's parameters; returns [(name, kind)] to rebuild the call."""
    spec = []
    for name, p in inspect.signature(fn).parameters.items():
        if name == "self" or name in NO_CLI_PARAMS or name.startswith("_"):
            continue
        ann = _ann(p)
        if p.kind is inspect.Parameter.VAR_KEYWORD:
            parser.add_argument("--set", dest="_set", action="append", default=[], metavar="KEY=VALUE",
                                help="a setting, repeatable (value read as JSON when it parses)")
            spec.append(("**", "set"))
            continue
        if p.kind is inspect.Parameter.VAR_POSITIONAL:
            continue
        if p.default is inspect.Parameter.empty:
            parser.add_argument(name, nargs="+" if _is_seq(name, p) else None,
                                type=json.loads if "dict" in ann else str)
            spec.append((name, "pos"))
            continue
        opt = "--" + _dash(name)
        if isinstance(p.default, bool) and "str" in ann:          # True/False or a value: --llama-cpp [VARIANT]
            parser.add_argument(opt, dest=name, nargs="?", const=True, default=p.default, metavar="VALUE")
            parser.add_argument("--no-" + _dash(name), dest=name, action="store_const", const=False)
        elif isinstance(p.default, bool):
            parser.add_argument(opt, dest=name, action=argparse.BooleanOptionalAction, default=p.default)
        elif _is_seq(name, p):
            parser.add_argument(opt, dest=name, nargs="+", default=p.default)
        elif "dict" in ann or "list" in ann:
            parser.add_argument(opt, dest=name, type=json.loads, default=p.default, metavar="JSON")
        elif isinstance(p.default, (int, float)):
            parser.add_argument(opt, dest=name, type=type(p.default), default=p.default)
        elif "float" in ann:
            parser.add_argument(opt, dest=name, type=float, default=p.default)
        elif "int" in ann and "Union" not in ann:
            parser.add_argument(opt, dest=name, type=int, default=p.default)
        else:
            parser.add_argument(opt, dest=name, default=p.default)
        spec.append((name, "opt"))
    if "quiet" in inspect.signature(fn).parameters:
        spec.append(("quiet", "quiet"))
    return spec


def _views(parser, fn):
    ret = str(inspect.signature(fn).return_annotation)
    if "Results" in ret:
        parser.add_argument("--view", choices=RESULT_VIEWS, default=None, help="which table of the results to show")
        parser.add_argument("--export", metavar="PATH", help="also save the Results page export there")
        parser.add_argument("--level", choices=("runs", "cells", "configs"), default="configs")
        parser.add_argument("--fmt", choices=("csv", "json"), default="csv")
    if "Transcript" in ret:
        parser.add_argument("--view", choices=TRANSCRIPT_VIEWS, default="turns", help="which view of the transcript")


def build_parser():
    from . import __version__, lib
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine-readable output")
    common.add_argument("--data", metavar="DIR", help="data folder (default: LLMDYNO_DATA or the usual one)")
    common.add_argument("--url", metavar="URL", default=None,
                        help="run the command on a LLMDyno server (default: LLMDYNO_URL, else this machine)")
    common.add_argument("--api-token", metavar="TOKEN", default=None,
                        help="that server's access token (default: LLMDYNO_TOKEN)")
    ap = argparse.ArgumentParser(prog="llmdyno", description="Benchmark local and cloud LLMs as coding agents. "
                                 "Every command is also a Python call: see docs/LIBRARY.md.", parents=[common])
    ap.add_argument("--version", action="version", version=f"llmdyno {__version__}")
    sub = ap.add_subparsers(dest="cmd", metavar="COMMAND")
    registry = {}

    sv = sub.add_parser("serve", parents=[common], help="start the web app (the default)",
                        description="Start the web app and its API. `llmdyno` with no command does the same.")
    sv.add_argument("--host", default="127.0.0.1",
                    help="address to listen on; anything but 127.0.0.1 or localhost lets other machines in, "
                         "and they need the access token (llmdyno token)")
    sv.add_argument("--port", type=int, default=None, help="port (default: the port setting, 8777)")
    sv.add_argument("--open", action="store_true", help="open the browser")
    sub.add_parser("doctor", parents=[common], help="check system specs and dependencies",
                   description="Print notes about this machine (architecture, GPU, memory) and the state of "
                               "everything benchmarks need: Docker, the sandbox and code-quality images, llama.cpp, "
                               "the harness images and the SWE-bench harness. `llmdyno setup` installs what is "
                               "missing.")
    sub.add_parser("specs", parents=[common], help="print detected hardware as JSON",
                   description="Print the detected hardware (CPU, RAM, GPUs, driver, disks, Docker) as JSON.")
    tk = sub.add_parser("token", parents=[common], help="the access token remote clients need (made on first use)",
                        description="Print the API token remote clients and browsers must present. It is shown when "
                                    "it is made; --rotate replaces it (the old one stops working at once).")
    tk.add_argument("--rotate", action="store_true", help="make a new token")
    ci = sub.add_parser("ci", parents=[common], help="fail (exit 1) when scores dropped against a baseline",
                        description="Compare results with a baseline for CI: exit 1 when a configuration's score "
                                    "dropped by more than --max-drop points or is missing.")
    ci.add_argument("--baseline", required=True, help="results JSON to compare with (llmdyno results --json)")
    ci.add_argument("--plans", nargs="+", default=None, help="plans to check (default: every plan)")
    ci.add_argument("--results", default=None, metavar="FILE", help="a results JSON instead of --plans")
    ci.add_argument("--metric", default="final", help="final, correctness, quality, … (0-100)")
    ci.add_argument("--max-drop", type=float, default=2.0, help="allowed drop in points (default 2)")
    ci.add_argument("--allow-missing", action="store_true", help="a configuration missing from the results is fine")
    ci.add_argument("--save", default=None, metavar="FILE", help="also save the current results there (next baseline)")

    groups = {}
    for name in lib.__all__:
        obj = getattr(lib, name)
        if name in CUSTOM or name in NOT_COMMANDS or name in GETTERS or isinstance(obj, type) or not callable(obj):
            if isinstance(obj, type) and name in GROUPS:
                groups[name] = obj
            continue
        p = sub.add_parser(_dash(name), parents=[common], help=_first_sentence(obj), description=inspect.getdoc(obj))
        registry[_dash(name)] = (obj, _add_params(p, obj))
        _views(p, obj)
    for cls_name, cls in groups.items():
        group, getter = GROUPS[cls_name]
        gp = sub.add_parser(group, parents=[common], help=_first_sentence(cls))
        gsub = gp.add_subparsers(dest="method", metavar="ACTION", required=True)
        show = gsub.add_parser("show", parents=[common], help=f"everything about one {group}")
        show.add_argument("id")
        registry[f"{group} show"] = (getter, [("id", "pos")])
        for mname, fn in inspect.getmembers(cls, inspect.isfunction):
            if mname.startswith("_") or mname in SKIP_METHODS:
                continue
            mp = gsub.add_parser(_dash(mname), parents=[common], help=_first_sentence(fn),
                                 description=inspect.getdoc(fn))
            mp.add_argument("id", help=f"the {group}'s id or name")
            registry[f"{group} {_dash(mname)}"] = (fn, [("id", "pos")] + _add_params(mp, fn))
            _views(mp, fn)
    return ap, registry


# ------------------------------------------------------------------ output
def _jsonable(x):
    from . import lib
    from .sdk.live import Event
    if isinstance(x, (lib.Results,)):
        return x.to_json()
    if isinstance(x, Event):
        return {"kind": x.kind, "topic": x.topic, "data": x.data, "ts": x.ts}
    if hasattr(x, "to_dict"):
        return x.to_dict()
    if isinstance(x, Path):
        return str(x)
    if isinstance(x, (bytes, bytearray)):
        return f"<{len(x)} bytes>"
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    return x


def _line(x) -> str:
    if hasattr(x, "to_dict") and hasattr(x, "id"):
        d = x.to_dict() if getattr(x, "_d", None) is not None else {}
        bits = [str(d.get(k)) for k in ("name", "title", "kind", "vendor", "quant", "status") if d.get(k) not in (None, "")]
        return "  ".join([x.id, *bits])
    if isinstance(x, dict):
        key = next((k for k in ("id", "repo", "path", "name", "title") if k in x), None)
        rest = [str(x[k]) for k in ("name", "title", "status", "category", "quant", "downloads", "size")
                if k in x and k != key]
        return "  ".join([str(x.get(key, "")), *rest]) if key else json.dumps(x, default=str)
    return str(x)


def _show(x, as_json: bool):
    from .sdk.live import Event
    if inspect.isgenerator(x):
        for item in x:
            if as_json:
                print(json.dumps(_jsonable(item), default=str), flush=True)
            elif isinstance(item, Event):
                what = item.data if isinstance(item.data, str) else (item.status or "")
                if item.kind == "run" and isinstance(item.data, dict):
                    what = f"{item.data.get('benchmark_id', '')} {item.status}"
                print(f"{item.kind:<10} {what}".rstrip(), flush=True)
        return
    if as_json:
        print(json.dumps(_jsonable(x), indent=2, default=str))
        return
    if x is None:
        return
    if isinstance(x, (str, int, float)) or type(x).__str__ is not object.__str__:
        print(x)                                    # text, numbers, and objects that print themselves (Results, Doctor)
        return
    if isinstance(x, list):
        for item in x:
            print(_line(item))
        return
    print(json.dumps(_jsonable(x), indent=2, default=str))


def _view(result, a):
    """--view / --export for Results and Transcript."""
    from . import lib
    view = getattr(a, "view", None)
    if isinstance(result, lib.Results):
        if getattr(a, "export", None):
            result.export(a.export, level=a.level, fmt=a.fmt)
        return getattr(result, view)() if view else result
    if isinstance(result, lib.Transcript):
        return {"turns": result.turns, "tool-calls": result.tool_calls, "thinking": result.thinking,
                "final": result.final_text, "usage": result.usage, "events": lambda: list(result)}[view or "turns"]()
    return result


# ------------------------------------------------------------------ running
def _call(entry, a):
    fn, spec = entry
    args, kwargs = [], {}
    for name, kind in spec:
        if kind == "pos":
            args.append(getattr(a, name))
        elif kind == "opt":
            kwargs[name] = getattr(a, name)
        elif kind == "quiet":
            kwargs["quiet"] = bool(a.json)
        elif kind == "set":
            for item in a._set:
                k, sep, v = item.partition("=")
                if not sep:
                    raise SystemExit(f"--set takes KEY=VALUE, got {item!r}")
                kwargs[k.replace("-", "_")] = _json_or_text(v)
    method = getattr(a, "method", None)
    if method:
        from . import lib
        target = getattr(lib, GETTER_OF[a.cmd])(args[0])
        return target if method == "show" else fn(target, *args[1:], **kwargs)
    return fn(*args, **kwargs)


def remote_notice(host: str) -> str | None:
    """What `serve` says when it listens beyond this machine: the token the first time, a reminder after."""
    import ipaddress
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = host == "localhost"
    if local:
        return None
    from . import auth
    tok, created = auth.ensure_token()
    if created:
        return (f"Remote access is on. Access token (shown once; `llmdyno token --rotate` replaces it):\n  {tok}\n"
                "Clients: llmdyno.connect(url, token=...) or LLMDYNO_TOKEN; browsers ask for it. Use HTTPS or an SSH "
                "tunnel across networks you do not trust.")
    return "Remote access is on: clients need the access token (`llmdyno token --rotate` makes a new one)."


def _token(a):
    from . import auth
    if a.rotate:
        print(auth.rotate())
        return 0
    tok, created = auth.ensure_token()
    if created:
        print(tok)
    else:
        print("A token already exists and is shown only when it is made; `llmdyno token --rotate` makes a new one "
              "(clients using the old one must update).", file=sys.stderr)
    return 0


def _serve(a):
    import uvicorn

    from . import config
    host = a.host
    port = a.port or int(config.get("port"))
    url = f"http://{host}:{port}"
    print(f"LLMDyno on {url}  (data: {config.DATA})", flush=True)
    note = remote_notice(host)
    if note:
        print(note, flush=True)
    if a.open:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run("llmdyno.server:app", host=host, port=port, log_level="warning")
    return 0


def _doctor(a):
    from . import lib
    from .system import specs
    s = specs.detect(force=True)
    if not s["os"]["arch_supported"]:
        print(f"Unsupported architecture {s['os']['arch']}: LLMDyno supports x86-64 and ARM64.")
        return 2
    doc = lib.doctor()
    if a.json:
        print(json.dumps({"notes": s["summary"]["notes"], "checks": list(doc)}, indent=2, default=str))
        return 0
    for n in s["summary"]["notes"]:
        print(f"[{n['level']}] {n['text']}")
    print()
    print(doc)
    return 0


def _ci(a):
    from . import lib
    current = a.results or lib.results(a.plans)
    if a.save and not a.results:
        current.to_json(a.save)
    rep = lib.compare_results(current, a.baseline, metric=a.metric, max_drop=a.max_drop, allow_missing=a.allow_missing)
    if a.json:
        print(json.dumps(rep, indent=2, default=str))
        return 0 if rep["ok"] else 1
    fmt = lambda v: "–" if v is None else f"{v:.1f}"   # noqa: E731
    for r in rep["rows"]:
        flag = "REGRESSED" if r in rep["regressions"] else "missing" if r in rep["missing"] else \
            "new" if r in rep["new"] else "ok"
        change = "" if r["change"] is None else f" ({r['change']:+.1f})"
        print(f"{flag:<10} {r['profile']} · {r['harness']}: {fmt(r['baseline'])} -> {fmt(r['current'])}{change}")
    verdict = "passed" if rep["ok"] else "FAILED"
    print(f"\n{verdict}: {len(rep['regressions'])} regression(s) of more than {a.max_drop} {a.metric} points, "
          f"{len(rep['missing'])} missing")
    return 0 if rep["ok"] else 1


def main(argv=None) -> int:
    ap, registry = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    a = ap.parse_args(argv or ["serve"])
    from . import lib
    from .errors import LLMDynoError, PreflightError
    if a.data:
        lib.init(a.data)                         # otherwise the library opens the usual folder on first use
    import os
    url = a.url or (os.environ.get("LLMDYNO_URL") if a.cmd not in ("serve", "token") else None)
    if url and a.cmd not in ("serve", "token"):
        try:
            lib.connect(url, a.api_token)
        except LLMDynoError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    if a.cmd == "token":
        return _token(a)
    if a.cmd == "serve":
        return _serve(a)
    if a.cmd == "doctor":
        return _doctor(a)
    if a.cmd == "ci":
        try:
            return _ci(a)
        except LLMDynoError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    if a.cmd == "specs":
        print(json.dumps(lib.specs(refresh=True), indent=2, default=str))
        return 0
    key = f"{a.cmd} {a.method}" if getattr(a, "method", None) else a.cmd
    try:
        result = _view(_call(registry[key], a), a)
        _show(result, a.json)
    except PreflightError as e:
        print("error: the plan cannot start:", file=sys.stderr)
        for p in e.problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    except LLMDynoError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except TypeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    return 0

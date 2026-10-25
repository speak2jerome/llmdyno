"""Command line: `llmdyno` starts the web app; `llmdyno doctor` prints the setup checks."""
import argparse

from . import __version__
import json
import sys
import threading
import webbrowser


def main(argv=None):
    ap = argparse.ArgumentParser(prog="llmdyno", description="Benchmark LLMs as coding agents.")
    ap.add_argument("--version", action="version", version=f"llmdyno {__version__}")
    sub = ap.add_subparsers(dest="cmd")
    sv = sub.add_parser("serve", help="start the web app (default)")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=None)
    sv.add_argument("--open", action="store_true", help="open the browser")
    sub.add_parser("doctor", help="check system specs and dependencies")
    sub.add_parser("specs", help="print detected hardware as JSON")
    a = ap.parse_args(argv)
    from . import config, db
    db.init()
    if a.cmd == "doctor":
        from .system import deps, specs
        s = specs.detect(force=True)
        if not s["os"]["arch_supported"]:
            print(f"Unsupported architecture {s['os']['arch']}: LLMDyno supports x86-64 for now.")
            return 2
        for n in s["summary"]["notes"]:
            print(f"[{n['level']}] {n['text']}")
        print()
        for d in deps.check(force=True):
            mark = "OK " if d["ok"] else ("!! " if d["level"] == "required" else "-- ")
            print(f"{mark}{d['name']:<22} {d['level']:<26} {d['detail']}")
        return 0
    if a.cmd == "specs":
        from .system import specs
        print(json.dumps(specs.detect(force=True), indent=2, default=str))
        return 0
    import uvicorn
    host = getattr(a, "host", "127.0.0.1")
    port = getattr(a, "port", None) or int(config.get("port"))
    url = f"http://{host}:{port}"
    print(f"LLMDyno on {url}  (data: {config.DATA})", flush=True)
    if getattr(a, "open", False):
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run("llmdyno.server:app", host=host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Print what LLMDyno detects on this machine: OS, CPU features, GPUs, memory notes and the llama.cpp builds it
would offer. Run it on new hardware (CI does, on x86-64, ARM64 Linux, Windows on ARM and Apple Silicon) or attach
its output to a bug report:

    python scripts/platform_probe.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llmdyno.inference import llamacpp  # noqa: E402
from llmdyno.system import specs  # noqa: E402


def main():
    s = specs.detect(force=True)
    g = specs.primary_gpu(s)
    out = {"os": {k: v for k, v in s["os"].items() if k != "hostname"}, "cpu": {k: v for k, v in s["cpu"].items() if k != "flags"},
           "cpu_flags": sorted(s["cpu"].get("flags") or []), "memory_gb": round(s["memory"]["total_bytes"] / 2**30, 1),
           "gpus": [{k: x.get(k) for k in ("name", "vendor", "vram_total_mib", "unified", "backend", "integrated",
                                           "bandwidth_gbs")} for x in s["gpus"]],
           "primary_gpu": g and g.get("name"), "docker": {k: s["docker"].get(k) for k in ("installed", "running", "arch")},
           "notes": [n.get("text") if isinstance(n, dict) else n for n in s["summary"]["notes"]],
           "llama_cpp_variants": [{"id": v["id"], "ok": v.get("ok"), "why": v.get("why")} for v in llamacpp.variants(s)]}
    print(json.dumps(out, indent=2, default=str))
    if s["os"].get("arch") not in ("x64", "arm64"):
        sys.exit(f"unsupported architecture {s['os'].get('arch')}")


if __name__ == "__main__":
    main()

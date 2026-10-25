"""Compare the metadata-only memory estimate with llama-fit-params on every local GGUF (developer tool).

Usage: python scripts/calibrate_memory.py <models dir> [<llama.cpp dir>]"""
import glob
import json
import sys

from llmdyno import memory
from llmdyno.hub import gguf
from llmdyno.inference import llamacpp

root = sys.argv[1]
if len(sys.argv) > 2:
    llamacpp.use_existing(sys.argv[2])
rows = []
for f in sorted(glob.glob(f"{root}/*/*.gguf")):
    if "mmproj" in f.lower():
        continue
    meta = gguf.read_model([f])
    for ctx in (32768, 65536, 131072):
        for ck in ("q8_0", "f16"):
            p = {"ctx": ctx, "gpu_layers": "all", "cache_k": ck, "cache_v": ck, "flash_attn": "on"}
            est = memory.estimate(meta, p)
            fit = llamacpp.fit_params(f, p)
            d = fit["devices"][0] if fit["devices"] else None
            if not d:
                continue
            rows.append({"model": f.replace("\\", "/").split("/")[-1], "ctx": ctx, "cache": ck,
                         "w_est": est["gpu"]["weights"], "w_fit": d["model"],
                         "kv_est": est["gpu"]["kv"], "kv_fit": d["ctx"], "c_est": est["gpu"]["compute"], "c_fit": d["compute"],
                         "n_vocab": meta["n_vocab"], "n_embd": meta["n_embd"], "n_head": meta["n_head"]})
            r = rows[-1]
            print(f"{r['model'][:34]:34} {ctx:>6} {ck:5} W {r['w_est']:>6}/{r['w_fit']:<6} KV {r['kv_est']:>6}/{r['kv_fit']:<6} "
                  f"C {r['c_est']:>5}/{r['c_fit']:<5}", flush=True)
json.dump(rows, open("calibration.json", "w"), indent=1)

"""Developer check: run one local profile x harness x benchmark end to end without the web server.

Usage: python scripts/dev_smoke_run.py <models dir> <llama.cpp dir> <gguf name substring> <harness id> <benchmark id>"""
import json
import sys
import threading

from llmdyno import db, jobs
from llmdyno.hub import hf
from llmdyno.inference import llamacpp
from llmdyno.profiles import default_local
from llmdyno.runner import executor

models_dir, llama_dir, pick, harness, bench = sys.argv[1:6]
harnesses = harness.split(",")
db.init()
llamacpp.use_existing(llama_dir)
hf.import_folder(models_dir)
with db.Session() as s:
    m = next(m for m in s.query(db.Model).all() if pick.lower() in m.name.lower())
    params = default_local(m.meta)
    params["ctx"] = 65536
    pid = db.new_id("prof")
    s.add(db.Profile(id=pid, name=f"{m.name} test", kind="local", model_id=m.id, params=params))
    s.commit()
print("preflight:", json.dumps(executor.preflight({"profile_ids": [pid], "harness_ids": harnesses,
                                                   "benchmark_ids": [bench], "iterations": 1}), indent=1)[:3000])
plan = executor.create_plan({"profile_ids": [pid], "harness_ids": harnesses, "benchmark_ids": [bench], "iterations": 1,
                             "options": {"quality": True}})


class Ctx:
    params = {"plan_id": plan}
    cancel_event = threading.Event()
    result = {}

    def log(self, x):
        print(x, flush=True)

    def progress(self, *a):
        pass

    def check(self):
        pass


jobs._cancel["x"] = Ctx.cancel_event
executor.execute_plan(Ctx())
with db.Session() as s:
    for r in s.query(db.Run).filter(db.Run.plan_id == plan):
        print(r.status, r.error, r.correctness, r.instruction_following, r.wall_s, r.dir)
        m = r.metrics or {}
        print(r.harness_id, {k: m.get(k) for k in ("tests_passed", "tests_total", "common_checks", "task_checks", "turns", "tool_calls",
                                                  "decode_tps", "peak_context_tokens", "spill_detected", "exit_codes", "errors")})
        print("quality:", json.dumps({k: (v if k != "static" else {kk: vv for kk, vv in (v or {}).items() if kk != "files"})
                                      for k, v in (r.quality or {}).items()}, default=str)[:1500])

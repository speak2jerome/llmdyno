"""Run SWE-bench Verified mini (50 real GitHub issues) graded by the official harness, and export the predictions.

Start small: LIMIT tasks first. Each task pulls its Docker image (1-5 GB) the first time; budget 10-40 minutes per
task on a local model. On ARM64 machines the task images run under x86-64 emulation. Needs Docker and internet access
for the images and the dataset; SWE-bench tasks want a profile with about 64k of context.

    python examples/swebench_mini.py "<profile name>"      # llmdyno list-profiles shows yours
"""
import sys

import llmdyno

if len(sys.argv) < 2:
    names = ", ".join(repr(p.name) for p in llmdyno.list_profiles()) or "none yet: make one with cloud_model() or local_model()"
    sys.exit(f"usage: python examples/swebench_mini.py PROFILE  (profiles: {names})")

LIMIT = 3

llmdyno.setup(harnesses=["pi"], swebench=True)       # adds the official swebench harness in its own venv
imported = llmdyno.import_swebench("verified_mini", limit=LIMIT)
print(f"imported {imported['imported']} tasks into suite {imported['suite_id']}")

model = llmdyno.profile(sys.argv[1])                     # by name or id
plan = llmdyno.bench(model, benchmarks=imported["suite_id"], harnesses="pi", wait=False)
results = plan.wait()

print(results)                                          # includes "SWE-bench resolved x% of n"
plan.swebench_predictions("swebench_predictions.jsonl")  # the official predictions format, for re-grading elsewhere

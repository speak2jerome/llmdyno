"""Compare a cloud model with a local one on the quick suite (3 tasks, about 5 minutes per model locally).

Needs Docker running and OPENAI_API_KEY set. The first run builds the sandbox images and downloads llama.cpp and the
model (several GB). Cloud spend is capped at $1 for this plan.

    python examples/quickstart.py
"""
import llmdyno

print(llmdyno.doctor())
llmdyno.setup(harnesses=["pi"])                       # only installs what is missing

gpt = llmdyno.cloud_model("openai", "gpt-6-luna", reasoning_effort="low", budget_usd=2)
qwen = llmdyno.local_model("unsloth/Qwen3.8-27B-GGUF", quant="UD-Q3_K_XL", ctx=49152)
print(qwen.check()["verdict"])                         # "fits", "tight", "spill" or "oom" on this GPU

results = llmdyno.bench([gpt, qwen], benchmarks="suite_quick", harnesses="pi", budget_usd=1.0)
print(results)
results.to_csv("quickstart_leaderboard.csv")
results.open()                                         # the full dashboard, with transcripts of every run

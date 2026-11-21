"""Which settings work best for one local model? Sweep context size and KV-cache type, skip what does not fit,
and rank the rest. Local only, so it costs nothing but GPU time.

    python examples/local_settings_sweep.py
"""
import llmdyno

REPO, QUANT = "unsloth/Qwen3.8-27B-GGUF", "UD-Q3_K_XL"

candidates = []
for ctx in (32768, 49152, 65536):
    for kv in ("q8_0", "q4_0"):
        p = llmdyno.local_model(REPO, quant=QUANT, ctx=ctx, kv_cache=kv, name=f"Qwen3.8 27B {ctx // 1024}k kv={kv}")
        verdict = p.check()["verdict"]
        print(f"{p.name}: {verdict}")
        if verdict in ("fits", "tight"):                # leave out settings that would spill into system RAM
            candidates.append(p)

results = llmdyno.bench(candidates, benchmarks=["t0_smoke_cli", "t5_bugfix_semver"], harnesses="pi", iterations=2)
print(results)
for row in results.leaderboard():
    print(f"{row['profile']:<36} final {row['final']:>5}  {row['decode_tps'] or 0:>6.1f} tok/s  "
          f"peak VRAM {(row['peak_vram_mib'] or 0) / 1024:.1f} GB")

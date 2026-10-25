"""Memory projection: KV cache maths, offload placement and the fit verdicts."""
from conftest import dense_meta, specs

from llmdyno import memory

MIB = 2**20
BASE = {"ctx": 4096, "cache_k": "f16", "cache_v": "f16", "gpu_layers": "all", "ubatch": 512, "flash_attn": "on"}


def test_kv_cache_f16(meta):
    # 4096 tokens x 8 KV heads x (128 + 128) dims x 2 bytes = 16 MiB per layer
    kv = memory.kv_layers(meta, BASE)
    assert kv == [16 * MIB] * 4


def test_quantized_kv_cache_is_smaller(meta):
    f16 = sum(memory.kv_layers(meta, BASE))
    q8 = sum(memory.kv_layers(meta, {**BASE, "cache_k": "q8_0", "cache_v": "q8_0"}))
    assert q8 / f16 == (34 / 32) / 2


def test_sliding_window_layers_cap_their_context():
    m = dense_meta(swa_layers=[1, 0, 1, 0], sliding_window=1024)
    kv = memory.kv_layers(m, {**BASE, "ctx": 65536})
    # SWA layers keep window + ubatch rounded up to 256 tokens; global layers keep the full context
    assert kv[0] == kv[2] == 1536 * 8 * 512
    assert kv[1] == kv[3] == 65536 * 8 * 512
    full = memory.kv_layers(m, {**BASE, "ctx": 65536, "swa_full": True})
    assert full[0] == full[1]


def test_recurrent_and_shared_layers_have_no_kv():
    m = dense_meta(recurrent_layers=[1, 1, 1, 0], shared_kv_layers=0)
    assert memory.kv_layers(m, BASE)[:3] == [0, 0, 0]
    assert memory.recurrent_state_bytes(m, BASE) > 0
    shared = dense_meta(shared_kv_layers=2)
    assert memory.kv_layers(shared, BASE)[2:] == [0, 0]


def test_partial_offload_moves_weights_to_the_cpu(meta):
    full = memory.estimate(meta, BASE)
    half = memory.estimate(meta, {**BASE, "gpu_layers": 2})
    assert full["gpu_layers"] == 4 and half["gpu_layers"] == 2
    assert half["gpu"]["weights"] < full["gpu"]["weights"]
    assert half["cpu"]["weights"] > full["cpu"]["weights"]


def test_verdicts(meta):
    need = memory.estimate(meta, BASE)["gpu_total"]
    assert memory.check(meta, BASE, specs(vram_free_mib=need + 4000))["verdict"] == "fits"
    assert memory.check(meta, BASE, specs(vram_free_mib=need + 100))["verdict"] == "tight"
    # not enough VRAM: Windows spills into shared memory, Linux fails to allocate
    short = specs(vram_free_mib=need - 500)
    assert memory.check(meta, BASE, short, os_name="nt")["verdict"] == "spill"
    assert memory.check(meta, BASE, short, os_name="posix")["verdict"] == "oom"
    assert memory.check(meta, BASE, specs(vram_free_mib=None))["verdict"] == "cpu"


def test_spill_warning_offers_a_fix(meta):
    need = memory.estimate(meta, {**BASE, "ctx": 131072})["gpu_total"]
    res = memory.check(meta, {**BASE, "ctx": 131072}, specs(vram_free_mib=need - 2000), os_name="nt")
    spill = next(w for w in res["warnings"] if w["code"] == "spill")
    assert spill["fix"], "a spill should come with a concrete way to shrink the profile"


def test_exact_fit_overrides_estimate(meta):
    fit = {"devices": [{"dev": "CUDA0", "model": 1000, "ctx": 200, "compute": 300}], "host": {"model": 50}}
    exact = memory.from_fit(fit)
    assert exact["gpu_total"] == 1000 + 200 + 300 + memory.CUDA_OVERHEAD_MIB
    assert exact["source"] == "llama-fit-params"

"""ARM64 and Apple Silicon: llama.cpp asset selection, macOS probes, ARM CPU features and unified memory."""
import json
from pathlib import Path

from conftest import dense_meta

from llmdyno import memory
from llmdyno.inference import llamacpp
from llmdyno.system import apple, specs

RELEASE = json.loads((Path(__file__).parent / "fixtures" / "llama_release.json").read_text())
ASSETS = RELEASE["assets"]


def names(picked):
    return [a["name"] for a in picked] if picked else picked


# ------------------------------------------------------------------ llama.cpp release assets
def test_parse_asset_reads_os_arch_and_backend():
    p = llamacpp.parse_asset("llama-b12606-bin-win-cuda-13.5-x64.zip")
    assert (p["os"], p["arch"], p["backend"], p["version"]) == ("win", "x64", "cuda", "13.5")
    assert llamacpp.parse_asset("llama-b12606-bin-macos-arm64.tar.gz")["backend"] == "metal"
    assert llamacpp.parse_asset("llama-b12606-bin-ubuntu-arm64.tar.gz")["backend"] == "cpu"
    assert llamacpp.parse_asset("cudart-llama-bin-win-cuda-13.5-x64.zip") is None


def test_windows_cuda_picks_the_newest_toolkit_with_its_runtime():
    got = names(llamacpp.pick_assets(ASSETS, "windows", "x64", "cuda-13"))
    assert got[0] == "llama-b12606-bin-win-cuda-13.5-x64.zip"
    assert got[1].startswith("cudart-llama-") and "13.5-x64" in got[1]


def test_apple_silicon_gets_the_metal_build():
    assert names(llamacpp.pick_assets(ASSETS, "macos", "arm64", "metal")) == ["llama-b12606-bin-macos-arm64.tar.gz"]
    assert llamacpp.pick_assets(ASSETS, "macos", "arm64", "cuda-13") is None


def test_arm64_linux_and_windows_builds_exist():
    lin = llamacpp.available_backends(ASSETS, "linux", "arm64")
    win = llamacpp.available_backends(ASSETS, "windows", "arm64")
    assert "cpu" in lin and "vulkan" in lin
    assert "cpu" in win
    assert all("arm64" in n for n in names(llamacpp.pick_assets(ASSETS, "linux", "arm64", "cpu")))


def test_every_platform_has_at_least_a_cpu_build():
    for os_family, arch in (("windows", "x64"), ("windows", "arm64"), ("linux", "x64"), ("linux", "arm64"),
                            ("macos", "arm64")):
        backends = llamacpp.available_backends(ASSETS, os_family, arch)
        assert backends, (os_family, arch)


# ------------------------------------------------------------------ macOS probes
SYSCTL = """machdep.cpu.brand_string: Apple M3 Pro
hw.optional.arm64: 1
hw.memsize: 38654705664
hw.perflevel0.physicalcpu: 6
hw.perflevel1.physicalcpu: 6
hw.optional.arm.FEAT_DotProd: 1
hw.optional.arm.FEAT_I8MM: 1
hw.optional.arm.FEAT_BF16: 1
iogpu.wired_limit_mb: 0
"""

IOREG = """+-o AGXAcceleratorG15X  <class AGXAcceleratorG15X>
    {
      "PerformanceStatistics" = {"In use system memory"=2147483648,"Alloc system memory"=4294967296,"Device Utilization %"=37,"Tiler Utilization %"=12}
    }
"""

PROFILER = json.dumps({"SPDisplaysDataType": [{"_name": "Apple M3 Pro", "sppci_model": "Apple M3 Pro", "sppci_cores": "18",
                                               "sppci_vendor": "sppci_vendor_Apple"}]})


def test_sysctl_gives_cpu_layout_and_arm_features():
    sc = apple.parse_sysctl(SYSCTL)
    cpu = apple.cpu_from_sysctl(sc)
    assert cpu["arm"] and {"neon", "dotprod", "i8mm", "bf16"} <= cpu["flags"]
    assert (cpu["performance_cores"], cpu["efficiency_cores"]) == (6, 6)


def test_metal_working_set_defaults_and_override():
    assert apple.working_set_limit_mib(36 * 2**30) == int(36 * 1024 * 2 / 3)
    assert apple.working_set_limit_mib(64 * 2**30) == int(64 * 1024 * 3 / 4)
    assert apple.working_set_limit_mib(64 * 2**30, wired_limit_mb=57344) == 57344


def test_wired_limit_suggestion_leaves_room_for_macos():
    assert apple.suggested_wired_limit_mib(36 * 1024, 24576) == 28672          # 36 GB Mac: raise to RAM - 8 GB
    assert apple.suggested_wired_limit_mib(128 * 1024, 98304) == 122880
    assert apple.suggested_wired_limit_mib(16 * 1024, 10922) is None           # small Macs: nothing worth raising
    assert apple.suggested_wired_limit_mib(7 * 1024, 4778) is None             # the 7 GB CI runner
    assert apple.suggested_wired_limit_mib(0, 0) is None


def test_ioreg_and_profiler_parsing():
    st = apple.parse_ioreg_stats(IOREG)
    assert st == {"in_use_bytes": 2 * 2**30, "alloc_bytes": 4 * 2**30, "util_pct": 37}
    assert apple.parse_ioreg_stats("no accelerator here") == {}
    assert apple.gpu_from_profiler(PROFILER) == ("Apple M3 Pro", 18)
    assert apple.bandwidth("Apple M3 Pro") and apple.bandwidth("Apple M4 Max", 32) == 410


def test_linux_arm_cpuinfo_features():
    text = "processor\t: 0\nFeatures\t: fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics fphp asimdhp asimddp sve i8mm\n"
    assert specs.arm_flags_linux(text) == {"neon", "fp16", "dotprod", "sve", "i8mm"}
    assert specs.norm_arch("aarch64") == "arm64" and specs.norm_arch("AMD64") == "x64"


# ------------------------------------------------------------------ unified memory
def apple_specs(limit_mib=24576, used_mib=2048, ram_gb=36):
    return {"gpus": [{"name": "Apple M3 Pro", "vendor": "Apple", "vram_total_mib": limit_mib, "vram_used_mib": used_mib,
                      "vram_free_mib": limit_mib - used_mib, "integrated": False, "unified": True, "backend": "metal",
                      "ram_total_mib": ram_gb * 1024}],
            "memory": {"total_bytes": ram_gb * 2**30, "available_bytes": ram_gb * 2**30 * 0.6},
            "cpu": {"simd_ok": True, "threads": 12, "isa": "arm64"}}


BASE = {"ctx": 8192, "cache_k": "f16", "cache_v": "f16", "gpu_layers": "all", "ubatch": 512, "flash_attn": "on"}


def test_unified_memory_over_the_limit_is_oom_not_spill():
    big = dense_meta(n_layer=40, layer_mib=800)          # ~32 GB of weights on a 24 GB Metal budget
    chk = memory.check(big, BASE, apple_specs(), os_name="posix")
    assert chk["verdict"] == "oom"
    assert any(w.get("code") == "unified_limit" for w in chk["warnings"])
    assert chk["gpu"]["unified"] is True


def test_unified_memory_small_model_fits():
    chk = memory.check(dense_meta(), BASE, apple_specs(), os_name="posix")
    assert chk["verdict"] in ("fits", "ok", "tight")
    assert chk["gpu"]["backend"] == "metal"

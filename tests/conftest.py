"""Every test session gets its own empty data folder, set before llmdyno is imported (config reads it at import)."""
import os
import tempfile

os.environ["LLMDYNO_DATA"] = tempfile.mkdtemp(prefix="llmdyno-test-")

import pytest  # noqa: E402

from llmdyno import db  # noqa: E402

db.init()


def dense_meta(n_layer=4, n_head_kv=8, head_dim=128, layer_mib=100, **extra):
    """Synthetic GGUF summary of a small dense model, in the shape hub/gguf.py produces."""
    meta = {
        "arch": "llama", "n_layer": n_layer, "n_head": 32, "n_head_kv": [n_head_kv] * n_layer,
        "key_length": head_dim, "value_length": head_dim, "n_embd": 4096, "n_vocab": 32000,
        "recurrent_layers": [0] * n_layer, "swa_layers": [0] * n_layer, "sliding_window": 0,
        "layer_bytes": [layer_mib * 2**20] * n_layer, "expert_bytes": [0] * n_layer,
        "embd_bytes": 250 * 2**20, "output_bytes": 250 * 2**20, "tied_embeddings": False, "ctx_train": 131072,
    }
    meta.update(extra)
    return meta


def specs(vram_free_mib=None, vram_total_mib=16303, ram_gb=64):
    gpus = [] if vram_free_mib is None else [{"name": "Test GPU", "vendor": "NVIDIA", "vram_total_mib": vram_total_mib,
                                               "vram_free_mib": vram_free_mib, "integrated": False, "backend": "cuda"}]
    return {"gpus": gpus, "memory": {"total_bytes": ram_gb * 2**30, "available_bytes": ram_gb * 2**30 * 0.7},
            "cpu": {"avx2": True, "threads": 16}}


@pytest.fixture
def meta():
    return dense_meta()

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


class Recorder:
    """A library backend that records calls and answers from a table instead of running anything, for SDK calls with
    effects outside the test's data folder (panic, Docker, downloads, cloud APIs)."""

    def __init__(self, replies=None):
        from llmdyno.sdk._backend import Backend
        self.calls, self.replies = [], dict(replies or {})
        self.__class__ = type("RecorderBackend", (Recorder, Backend), {})

    kind = "recorder"

    def call(self, op, **kwargs):
        self.calls.append((op, kwargs))
        reply = self.replies[op]
        return reply(**kwargs) if callable(reply) else reply

    def subscribe(self, fn, topics):
        return None

    def ops(self):
        return [op for op, _ in self.calls]


@pytest.fixture
def recorder():
    """llmdyno calls go to a Recorder for the test: set .replies[op] before calling."""
    from llmdyno.sdk import _backend
    rec = Recorder()
    prev = _backend.use(rec)
    try:
        yield rec
    finally:
        _backend.use(prev)


def write_gguf(path, n_layer=2, n_embd=64, n_head=4, n_vocab=32, ctx=4096, name="Tiny Test"):
    """A small but valid GGUF file (llama architecture, F32 tensors) that the header reader and importer accept."""
    import struct
    from pathlib import Path

    def s(text):
        b = text.encode()
        return struct.pack("<Q", len(b)) + b
    kv = [("general.architecture", 8, "llama"), ("general.name", 8, name), ("llama.block_count", 4, n_layer),
          ("llama.embedding_length", 4, n_embd), ("llama.attention.head_count", 4, n_head),
          ("llama.attention.head_count_kv", 4, n_head), ("llama.context_length", 4, ctx)]
    tensors = [("token_embd.weight", [n_embd, n_vocab])]
    tensors += [(f"blk.{i}.attn_q.weight", [n_embd, n_embd]) for i in range(n_layer)]
    tensors += [("output.weight", [n_embd, n_vocab])]
    head = b"GGUF" + struct.pack("<IQQ", 3, len(tensors), len(kv))
    for key, t, v in kv:
        head += s(key) + struct.pack("<I", t) + (s(v) if t == 8 else struct.pack("<I", v))
    offset, blobs = 0, []
    for tname, shape in tensors:
        size = 4
        for d in shape:
            size *= d
        head += s(tname) + struct.pack("<I", len(shape)) + b"".join(struct.pack("<Q", d) for d in shape)
        head += struct.pack("<IQ", 0, offset)
        blobs.append(bytes(size))
        offset += (size + 31) // 32 * 32
    head += bytes((-len(head)) % 32)
    data = b"".join(b + bytes((-len(b)) % 32) for b in blobs)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(head + data)
    return Path(path)

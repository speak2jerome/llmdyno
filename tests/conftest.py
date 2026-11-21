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


def transcript_events(t0):
    """A two-call transcript the way the proxy records it: a tool call, its result, then a final answer."""
    import json as _json
    tool = {"type": "tool_call", "id": "call_1", "name": "bash", "args": _json.dumps({"command": "ls"})}
    return [
        {"t": t0, "seq": 1, "ev": "request", "conv": "c1", "model": "local-model", "n_messages": 1,
         "new": [{"role": "user", "blocks": [{"type": "text", "text": "Write hello.py"}]}]},
        {"t": t0 + 1, "seq": 1, "ev": "block_start", "index": "think", "type": "thinking"},
        {"t": t0 + 1, "seq": 1, "ev": "delta", "index": "think", "text": "Let me look"},
        {"t": t0 + 2, "seq": 1, "ev": "response", "status": 200, "finish": "tool_calls",
         "blocks": [{"type": "thinking", "text": "Let me look"}, tool],
         "usage": {"input": 100, "cached": 0, "output": 20, "reasoning": 0}, "ttft_s": 0.5, "wall_s": 2.0,
         "cost_usd": 0.001},
        {"t": t0 + 3, "seq": 2, "ev": "request", "conv": "c1", "model": "local-model", "n_messages": 3,
         "new": [{"role": "assistant", "blocks": [tool]},
                 {"role": "tool", "blocks": [{"type": "tool_result", "id": "call_1", "name": "bash", "text": "README.md"}]}]},
        {"t": t0 + 5, "seq": 2, "ev": "response", "status": 200, "finish": "stop",
         "blocks": [{"type": "text", "text": "Done: hello.py prints hi."}],
         "usage": {"input": 150, "cached": 100, "output": 30, "reasoning": 0}, "ttft_s": 0.4, "wall_s": 1.5,
         "cost_usd": 0.002},
    ]


def write_finished_run(plan_id, run_id, profile_id, t0, benchmark_id="t0_smoke_cli"):
    """A finished plan with one run on disk, as the runner leaves it: workspace, transcript, proxy log, stage log,
    GPU samples. No Docker or model needed."""
    import json as _json

    from llmdyno import config
    plan_dir = config.path("runs_dir") / plan_id
    run_dir = plan_dir / run_id
    (run_dir / "workspace").mkdir(parents=True)
    (run_dir / "workspace" / "hello.py").write_bytes(b"print('hi')\n")
    (run_dir / "workspace" / "data.bin").write_bytes(b"\0\1" * 50)
    (run_dir / "transcript.jsonl").write_text("".join(_json.dumps(e) + "\n" for e in transcript_events(t0)))
    proxy = [{"seq": 1, "ts": t0, "t_end": t0 + 2, "wall_s": 2.0, "ttft_s": 0.5, "finish_reason": "tool_calls",
              "usage_norm": {"input": 100, "cached": 0, "output": 20}, "cost_usd": 0.001, "model": "local-model"},
             {"seq": 2, "ts": t0 + 3, "t_end": t0 + 5, "wall_s": 1.5, "ttft_s": 0.4, "finish_reason": "stop",
              "usage_norm": {"input": 150, "cached": 100, "output": 30}, "cost_usd": 0.002, "model": "local-model"}]
    (run_dir / "proxy.jsonl").write_text("".join(_json.dumps(x) + "\n" for x in proxy))
    (run_dir / "stdout_stage1.log").write_bytes(b"agent says hello\n")
    (plan_dir / f"gpu_{profile_id}.jsonl").write_text(_json.dumps({"ts": t0 + 1, "util": 90, "vram_used_mib": 9000}) + "\n")
    with db.Session() as s:
        s.add(db.Plan(id=plan_id, name=f"Test plan {plan_id}", profile_ids=[profile_id], harness_ids=["pi"],
                      benchmark_ids=[benchmark_id], iterations=1, options={}, status="done", created_at=t0,
                      started_at=t0, ended_at=t0 + 60))
        s.add(db.Run(id=run_id, plan_id=plan_id, profile_id=profile_id, harness_id="pi", benchmark_id=benchmark_id,
                     iteration=1, status="done", dir=str(run_dir), started_at=t0, ended_at=t0 + 60, correctness=1.0,
                     instruction_following=1.0, wall_s=60, cost_usd=0.003,
                     metrics={"tests_passed": 3, "tests_total": 3, "generated_tokens": 50}))
        s.commit()
    return run_dir

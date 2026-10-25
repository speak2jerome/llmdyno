"""GGUF header reader for local files and remote URLs (HTTP range requests; no weights are downloaded).

Reads the metadata key/values and the tensor table. Large arrays (the tokenizer vocabulary) are skipped and
only their length is kept, so a remote header costs a few MB at most."""
import struct
from pathlib import Path

import httpx

T_U8, T_I8, T_U16, T_I16, T_U32, T_I32, T_F32, T_BOOL, T_STR, T_ARR, T_U64, T_I64, T_F64 = range(13)
SCALAR = {T_U8: "<B", T_I8: "<b", T_U16: "<H", T_I16: "<h", T_U32: "<I", T_I32: "<i", T_F32: "<f",
          T_BOOL: "<?", T_U64: "<Q", T_I64: "<q", T_F64: "<d"}
KEEP_ARRAY_MAX = 4096   # small arrays (per-layer head counts, SWA patterns) are kept; vocabularies are not

# ggml type id -> (name, block size, bytes per block). Unknown future types fall back to offset arithmetic.
GGML_TYPES = {
    0: ("F32", 1, 4), 1: ("F16", 1, 2), 2: ("Q4_0", 32, 18), 3: ("Q4_1", 32, 20), 6: ("Q5_0", 32, 22),
    7: ("Q5_1", 32, 24), 8: ("Q8_0", 32, 34), 9: ("Q8_1", 32, 36), 10: ("Q2_K", 256, 84), 11: ("Q3_K", 256, 110),
    12: ("Q4_K", 256, 144), 13: ("Q5_K", 256, 176), 14: ("Q6_K", 256, 210), 15: ("Q8_K", 256, 292),
    16: ("IQ2_XXS", 256, 66), 17: ("IQ2_XS", 256, 74), 18: ("IQ3_XXS", 256, 98), 19: ("IQ1_S", 256, 50),
    20: ("IQ4_NL", 32, 18), 21: ("IQ3_S", 256, 110), 22: ("IQ2_S", 256, 82), 23: ("IQ4_XS", 256, 136),
    24: ("I8", 1, 1), 25: ("I16", 1, 2), 26: ("I32", 1, 4), 27: ("I64", 1, 8), 28: ("F64", 1, 8),
    29: ("IQ1_M", 256, 56), 30: ("BF16", 1, 2), 34: ("TQ1_0", 256, 54), 35: ("TQ2_0", 256, 66), 39: ("MXFP4", 32, 17),
}


class _Source:
    """Sequential reader over a local file or a remote URL fetched in growing range chunks."""

    def __init__(self, target, headers=None, client=None):
        self.local = not str(target).startswith(("http://", "https://"))
        self.buf = b""
        self.pos = 0
        self.fetched = 0
        self.size = None
        if self.local:
            self.f = open(target, "rb")
            self.size = Path(target).stat().st_size
        else:
            self.url = str(target)
            self.headers = headers or {}
            self.client = client or httpx.Client(follow_redirects=True, timeout=60)
            self.chunk = 1 << 20

    def _need(self, n):
        while len(self.buf) - self.pos < n:
            if self.local:
                more = self.f.read(max(n, 1 << 20))
            else:
                start = self.fetched
                r = self.client.get(self.url, headers={**self.headers, "Range": f"bytes={start}-{start + self.chunk - 1}"})
                if r.status_code not in (200, 206):
                    r.raise_for_status()
                if self.size is None:
                    cr = r.headers.get("content-range", "")
                    self.size = int(cr.rsplit("/", 1)[-1]) if "/" in cr and cr.rsplit("/", 1)[-1].isdigit() else None
                more = r.content if r.status_code == 206 else r.content[start:start + self.chunk]
                self.chunk = min(self.chunk * 2, 16 << 20)
            if not more:
                raise EOFError("unexpected end of GGUF header")
            self.fetched += len(more)
            self.buf = self.buf[self.pos:] + more
            self.pos = 0

    def read(self, n):
        self._need(n)
        out = self.buf[self.pos:self.pos + n]
        self.pos += n
        return out

    def skip(self, n):
        while n > 0:
            take = min(n, 8 << 20)
            self.read(take)
            n -= take

    def unpack(self, fmt):
        return struct.unpack(fmt, self.read(struct.calcsize(fmt)))[0]

    def offset(self):
        return self.fetched - (len(self.buf) - self.pos)

    def close(self):
        if self.local:
            self.f.close()


def _read_str(src):
    n = src.unpack("<Q")
    return src.read(n).decode("utf-8", "replace")


def _read_value(src, t):
    if t in SCALAR:
        return src.unpack(SCALAR[t])
    if t == T_STR:
        return _read_str(src)
    if t == T_ARR:
        et, n = src.unpack("<I"), src.unpack("<Q")
        if n > KEEP_ARRAY_MAX:
            if et in SCALAR:
                src.skip(n * struct.calcsize(SCALAR[et]))
            elif et == T_STR:
                for _ in range(n):
                    src.skip(src.unpack("<Q"))
            else:
                for _ in range(n):
                    _read_value(src, et)
            return {"_array_len": n, "_type": et}
        return [_read_value(src, et) for _ in range(n)]
    raise ValueError(f"unknown GGUF value type {t}")


def read_header(target, headers=None, client=None):
    """Return {version, kv, tensors: [{name, shape, type, offset, bytes}], data_offset, file_size, header_bytes}."""
    src = _Source(target, headers, client)
    try:
        if src.read(4) != b"GGUF":
            raise ValueError("not a GGUF file")
        version = src.unpack("<I")
        n_tensors, n_kv = src.unpack("<Q"), src.unpack("<Q")
        kv = {}
        for _ in range(n_kv):
            key = _read_str(src)
            kv[key] = _read_value(src, src.unpack("<I"))
        tensors = []
        for _ in range(n_tensors):
            name = _read_str(src)
            nd = src.unpack("<I")
            shape = [src.unpack("<Q") for _ in range(nd)]
            ttype, off = src.unpack("<I"), src.unpack("<Q")
            tensors.append({"name": name, "shape": shape, "type": ttype, "offset": off})
        align = kv.get("general.alignment", 32) or 32
        end = src.offset()
        data_offset = (end + align - 1) // align * align
        size = src.size
    finally:
        src.close()
    # tensor byte sizes: from the type table when known, else from the gap to the next tensor
    order = sorted(range(len(tensors)), key=lambda i: tensors[i]["offset"])
    for rank, i in enumerate(order):
        t = tensors[i]
        n_el = 1
        for d in t["shape"]:
            n_el *= d
        known = GGML_TYPES.get(t["type"])
        if known:
            t["bytes"] = n_el // known[1] * known[2]
        elif rank + 1 < len(order):
            t["bytes"] = tensors[order[rank + 1]]["offset"] - t["offset"]
        else:
            t["bytes"] = (size - data_offset - t["offset"]) if size else 0
        t["type_name"] = known[0] if known else f"type{t['type']}"
    return {"version": version, "kv": kv, "tensors": tensors, "data_offset": data_offset, "file_size": size,
            "header_bytes": end}


def _arch_get(kv, arch, key, default=None):
    return kv.get(f"{arch}.{key}", default)


def summarize(headers):
    """Condense one or more split headers into the facts the memory estimator and the UI need."""
    first = headers[0]
    kv = first["kv"]
    arch = kv.get("general.architecture", "unknown")
    tensors = [t for h in headers for t in h["tensors"]]
    n_layer = _arch_get(kv, arch, "block_count", 0) or 0

    def per_layer(v, default):
        if isinstance(v, list):
            return [int(x) for x in v] + [int(v[-1]) if v else default] * max(0, n_layer - len(v))
        return [int(v if v is not None else default)] * n_layer

    n_head = per_layer(_arch_get(kv, arch, "attention.head_count", 0), 0)
    n_head_kv = per_layer(_arch_get(kv, arch, "attention.head_count_kv", None), n_head[0] if n_head else 0)
    n_embd = _arch_get(kv, arch, "embedding_length", 0) or 0
    head_dim = (n_embd // n_head[0]) if n_head and n_head[0] else 0
    key_len = _arch_get(kv, arch, "attention.key_length", head_dim) or head_dim
    val_len = _arch_get(kv, arch, "attention.value_length", key_len) or key_len

    swa = _arch_get(kv, arch, "attention.sliding_window", 0) or 0
    pattern = _arch_get(kv, arch, "attention.sliding_window_pattern")
    swa_layers = [False] * n_layer
    if swa:
        if isinstance(pattern, list):
            swa_layers = [bool(x) for x in pattern][:n_layer] + [False] * max(0, n_layer - len(pattern))
        elif isinstance(pattern, int) and pattern > 1:
            swa_layers = [(i % pattern) < (pattern - 1) for i in range(n_layer)]
        elif pattern is None and arch.startswith("gemma"):
            swa_layers = [(i % 6) < 5 for i in range(n_layer)]
        elif pattern is None and arch == "gpt-oss":
            swa_layers = [i % 2 == 0 for i in range(n_layer)]      # llama.cpp hard-codes alternating SWA/full
        else:
            swa_layers = [True] * n_layer

    interval = _arch_get(kv, arch, "full_attention_interval")
    recurrent = [False] * n_layer
    if interval:
        recurrent = [((i + 1) % int(interval)) != 0 for i in range(n_layer)]
    elif any(k.startswith(f"{arch}.ssm.") for k in kv) and arch in ("mamba", "mamba2", "rwkv6", "rwkv7"):
        recurrent = [True] * n_layer
    shared_kv = 0
    for k, v in kv.items():
        if k.startswith(f"{arch}.") and k.endswith("shared_kv_layers") and isinstance(v, int):
            shared_kv = v
    kv_lora = _arch_get(kv, arch, "attention.kv_lora_rank")
    rope_dim = _arch_get(kv, arch, "rope.dimension_count", 0) or 0

    layer_bytes = [0] * n_layer
    expert_bytes = [0] * n_layer
    other = 0
    for t in tensors:
        name = t["name"]
        if name.startswith("blk."):
            try:
                il = int(name.split(".")[1])
            except ValueError:
                other += t["bytes"]
                continue
            if 0 <= il < n_layer:
                layer_bytes[il] += t["bytes"]
                if "_exps" in name or ".exps." in name:
                    expert_bytes[il] += t["bytes"]
                continue
        other += t["bytes"]
    output_bytes = sum(t["bytes"] for t in tensors if t["name"] in ("output.weight", "output_norm.weight"))
    embd_bytes = sum(t["bytes"] for t in tensors if t["name"].startswith("token_embd"))
    has_output = any(t["name"] == "output.weight" for t in tensors)
    types = {}
    for t in tensors:
        types[t["type_name"]] = types.get(t["type_name"], 0) + t["bytes"]
    tok = kv.get("tokenizer.ggml.tokens")
    n_vocab = tok["_array_len"] if isinstance(tok, dict) else (len(tok) if isinstance(tok, list) else 0)
    tmpl = kv.get("tokenizer.chat_template") or ""
    n_params = sum(_numel(t["shape"]) for t in tensors)
    sampling = {k.split(".")[-1]: v for k, v in kv.items() if k.startswith("general.sampling.")}
    return {
        "arch": arch, "name": kv.get("general.name") or kv.get("general.basename") or "", "size_label": kv.get("general.size_label", ""),
        "file_type": kv.get("general.file_type"), "n_params": n_params, "n_layer": n_layer, "n_embd": n_embd,
        "n_head": n_head[0] if n_head else 0, "n_head_kv": n_head_kv, "key_length": key_len, "value_length": val_len,
        "key_length_swa": _arch_get(kv, arch, "attention.key_length_swa"),
        "value_length_swa": _arch_get(kv, arch, "attention.value_length_swa"),
        "nextn_layers": _arch_get(kv, arch, "nextn_predict_layers", 0) or 0,
        "ssm_inner": _arch_get(kv, arch, "ssm.inner_size"), "ssm_state": _arch_get(kv, arch, "ssm.state_size"),
        "ssm_conv": _arch_get(kv, arch, "ssm.conv_kernel"), "ssm_groups": _arch_get(kv, arch, "ssm.group_count"),
        "ctx_train": _arch_get(kv, arch, "context_length", 0) or 0, "n_vocab": n_vocab,
        "sliding_window": swa, "swa_layers": swa_layers, "recurrent_layers": recurrent, "shared_kv_layers": shared_kv,
        "kv_lora_rank": kv_lora, "rope_dim": rope_dim,
        "expert_count": _arch_get(kv, arch, "expert_count", 0) or 0, "expert_used": _arch_get(kv, arch, "expert_used_count", 0) or 0,
        "layer_bytes": layer_bytes, "expert_bytes": expert_bytes, "other_bytes": other, "output_bytes": output_bytes,
        "embd_bytes": embd_bytes, "tied_embeddings": not has_output,
        "total_bytes": sum(t["bytes"] for t in tensors), "tensor_types": dict(sorted(types.items(), key=lambda x: -x[1])),
        "chat_template_tools": ("tools" in tmpl) or ("tool_call" in tmpl), "chat_template_thinking": ("think" in tmpl),
        "has_chat_template": bool(tmpl), "sampling": sampling,
        "split_count": kv.get("split.count", 1) or 1,
    }


def _numel(shape):
    n = 1
    for d in shape:
        n *= d
    return n


def read_model(paths_or_urls, headers=None):
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        heads = [read_header(p, headers, client) for p in paths_or_urls]
    return summarize(heads)

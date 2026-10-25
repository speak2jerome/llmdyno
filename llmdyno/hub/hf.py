"""Hugging Face Hub: search GGUF repos, list quants with sizes, read remote headers, resumable downloads."""
import hashlib
import json
import re
import shutil
import time
from pathlib import Path

import httpx

from .. import config, db, events, secrets
from . import gguf

API = "https://huggingface.co/api"
QUANT_RE = re.compile(r"(?:^|[-_.])((?:UD-)?(?:IQ\d_(?:XXS|XS|S|M|NL)|Q\d_K(?:_(?:XL|L|M|S))?|Q\d_\d(?:_\d_\d)?|TQ\d_\d|"
                      r"MXFP4(?:_MOE)?|NVFP4|BF16|F16|F32))(?=[-_.]|$)", re.I)
SPLIT_RE = re.compile(r"-(\d{5})-of-(\d{5})\.gguf$", re.I)


def _headers():
    tok = secrets.get("hf_token")
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def search(q, limit=30, sort="downloads"):
    params = [("search", q), ("filter", "gguf"), ("sort", sort), ("direction", -1), ("limit", limit)] + [
        ("expand[]", k) for k in ("downloads", "likes", "lastModified", "gated", "pipeline_tag")]
    r = httpx.get(f"{API}/models", params=params, headers=_headers(), timeout=30)
    r.raise_for_status()
    return [{"repo": m["id"], "downloads": m.get("downloads", 0), "likes": m.get("likes", 0),
             "updated": m.get("lastModified"), "pipeline": m.get("pipeline_tag"),
             "gated": bool(m.get("gated"))} for m in r.json()]


def quant_of(name):
    stem = Path(name).name
    m = QUANT_RE.findall(stem)
    return m[-1].upper().replace("UD-", "UD-") if m else "other"


def repo_files(repo):
    """GGUF files grouped into downloadable variants (one quant; split parts together)."""
    r = httpx.get(f"{API}/models/{repo}/tree/main", params={"recursive": "true"}, headers=_headers(), timeout=30)
    if r.status_code == 401 or r.status_code == 403:
        raise PermissionError("this repository is gated or private: add a Hugging Face token in Settings and accept "
                              "the model's terms on huggingface.co")
    r.raise_for_status()
    files = [f for f in r.json() if f.get("type") == "file" and f["path"].lower().endswith(".gguf")]
    groups = {}
    for f in files:
        path = f["path"]
        size = (f.get("lfs") or {}).get("size") or f.get("size") or 0
        sha = (f.get("lfs") or {}).get("oid") or (f.get("lfs") or {}).get("sha256")
        is_mmproj = "mmproj" in path.lower()
        key = SPLIT_RE.sub("", path) if SPLIT_RE.search(path) else path
        g = groups.setdefault(key, {"id": key, "quant": "mmproj" if is_mmproj else quant_of(key), "files": [],
                                    "size_bytes": 0, "mmproj": is_mmproj})
        g["files"].append({"path": path, "size": size, "sha256": sha})
        g["size_bytes"] += size
    out = sorted(groups.values(), key=lambda g: (g["mmproj"], g["size_bytes"]))
    for g in out:
        g["files"].sort(key=lambda f: f["path"])
    info = httpx.get(f"{API}/models/{repo}", headers=_headers(), timeout=30)
    meta = info.json() if info.status_code == 200 else {}
    return {"repo": repo, "variants": out, "gated": bool(meta.get("gated")), "downloads": meta.get("downloads"),
            "likes": meta.get("likes"), "license": (meta.get("cardData") or {}).get("license"),
            "base_model": (meta.get("cardData") or {}).get("base_model"), "tags": meta.get("tags", [])[:30]}


def file_url(repo, path):
    return f"https://huggingface.co/{repo}/resolve/main/{path}"


def _cache_path(repo, variant_id):
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{repo}__{variant_id}")
    return config.DATA / "cache" / "gguf" / f"{safe}.json"


def remote_meta(repo, variant):
    """Parse the header(s) of a remote variant; cached on disk because headers never change for a file."""
    cp = _cache_path(repo, variant["id"])
    if cp.exists():
        return json.loads(cp.read_text(encoding="utf-8"))
    meta = gguf.read_model([file_url(repo, f["path"]) for f in variant["files"]], headers=_headers())
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(meta), encoding="utf-8")
    return meta


# ------------------------------------------------------------------ downloads
def local_dir_for(repo):
    return config.path("models_dir") / repo.replace("/", "__")


def free_bytes(path):
    p = Path(path)
    while not p.exists():
        p = p.parent
    return shutil.disk_usage(p).free


def download(ctx):
    """Job: download every file of a variant with HTTP range resume and SHA-256 verification."""
    model_id = ctx.params["model_id"]
    with db.Session() as s:
        m = s.get(db.Model, model_id)
        repo, files = m.repo, ctx.params["files"]
        target = Path(m.local_dir)
    target.mkdir(parents=True, exist_ok=True)
    total = sum(f["size"] for f in files)
    have = sum((target / Path(f["path"]).name).stat().st_size for f in files if (target / Path(f["path"]).name).exists())
    partial = sum((target / (Path(f["path"]).name + ".part")).stat().st_size for f in files
                  if (target / (Path(f["path"]).name + ".part")).exists())
    need = total - have - partial
    if need > free_bytes(target) - 512 * 2**20:
        raise OSError(f"not enough disk space: {need / 2**30:.1f} GB needed, {free_bytes(target) / 2**30:.1f} GB free "
                      f"on {target.anchor or target}")
    _set_model(model_id, status="downloading", error="")
    done_bytes = have
    t0, last_pub, base_done = time.time(), 0.0, have + partial
    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60, read=120), headers=_headers()) as client:
        for f in files:
            dest = target / Path(f["path"]).name
            if dest.exists() and dest.stat().st_size == f["size"]:
                continue
            part = dest.with_name(dest.name + ".part")
            h = hashlib.sha256()
            pos = part.stat().st_size if part.exists() else 0
            if pos:
                ctx.log(f"resuming {dest.name} at {pos / 2**30:.2f} GB")
                with open(part, "rb") as pf:
                    while chunk := pf.read(8 << 20):
                        h.update(chunk)
            hdr = {"Range": f"bytes={pos}-"} if pos else {}
            with client.stream("GET", file_url(repo, f["path"]), headers=hdr) as r:
                if r.status_code == 200 and pos:
                    pos, h = 0, hashlib.sha256()          # server ignored the range: start over
                elif r.status_code not in (200, 206):
                    r.raise_for_status()
                with open(part, "ab" if pos else "wb") as out:
                    for chunk in r.iter_bytes(4 << 20):
                        if ctx.cancelled:
                            _set_model(model_id, status="paused")
                            ctx.cancel_status = "paused"
                            ctx.check()
                        out.write(chunk)
                        h.update(chunk)
                        pos += len(chunk)
                        now = time.time()
                        if now - last_pub > 0.5:
                            last_pub = now
                            got = done_bytes + pos
                            speed = (got - base_done) / max(now - t0, 0.01)
                            eta = (total - got) / speed if speed > 0 else None
                            frac = got / total if total else 0
                            ctx.progress(frac, f"{got / 2**30:.2f} / {total / 2**30:.2f} GB · {speed / 2**20:.1f} MB/s"
                                         + (f" · {eta / 60:.0f} min left" if eta and eta > 60 else ""))
                            _set_model(model_id, progress=frac, publish_only=True,
                                       extra={"speed_bps": speed, "eta_s": eta, "bytes_done": got})
            if f.get("sha256") and h.hexdigest() != f["sha256"]:
                part.unlink(missing_ok=True)
                raise ValueError(f"checksum mismatch for {dest.name}; the partial file was removed, retry the download")
            part.rename(dest)
            done_bytes += f["size"]
            ctx.log(f"downloaded {dest.name} ({f['size'] / 2**30:.2f} GB, sha256 verified)")
    first = target / Path(files[0]["path"]).name
    meta = gguf.read_model([target / Path(f["path"]).name for f in files])
    _set_model(model_id, status="ready", progress=1.0, meta=meta, size_bytes=total,
               files=[Path(f["path"]).name for f in files])
    ctx.result = {"model_id": model_id, "path": str(first)}
    ctx.progress(1.0, f"{total / 2**30:.2f} GB · checksums verified")


def _set_model(model_id, publish_only=False, extra=None, **fields):
    data = None
    if not publish_only or fields:
        with db.Session() as s:
            m = s.get(db.Model, model_id)
            if m is None:
                return
            for k, v in fields.items():
                setattr(m, k, v)
            s.commit()
            data = model_dict(m)
    if data is None:
        data = {"id": model_id, **fields}
    if extra:
        data.update(extra)
    events.publish("models", "update", data)


def model_dict(m):
    d = db.row(m)
    meta = d.get("meta") or {}
    # per-layer arrays are large and only used server-side
    d["meta"] = {k: v for k, v in meta.items() if k not in ("layer_bytes", "expert_bytes", "swa_layers",
                                                              "recurrent_layers", "n_head_kv")}
    d["meta"]["hybrid"] = any(meta.get("recurrent_layers") or [])
    d["paths"] = [str(Path(m.local_dir) / f) for f in (m.files or [])]
    return d


def import_folder(folder):
    """Register GGUF files that already exist on disk (no copy). Split parts become one model."""
    root = Path(folder)
    if not root.is_dir():
        raise FileNotFoundError(folder)
    found = {}
    for f in sorted(root.rglob("*.gguf")):
        if "mmproj" in f.name.lower() or f.name.endswith(".part"):
            continue
        key = SPLIT_RE.sub("", str(f)) if SPLIT_RE.search(f.name) else str(f)
        found.setdefault(key, []).append(f)
    added = []
    with db.Session() as s:
        existing = {(m.local_dir, tuple(m.files)) for m in s.query(db.Model).all()}
        for parts in found.values():
            parts.sort()
            if SPLIT_RE.search(parts[0].name):
                m_ = SPLIT_RE.search(parts[0].name)
                if len(parts) != int(m_.group(2)):
                    continue                          # incomplete split set
            local_dir, files = str(parts[0].parent), [p.name for p in parts]
            if (local_dir, tuple(files)) in existing:
                continue
            try:
                meta = gguf.read_model(parts)
            except (ValueError, EOFError, OSError):
                continue
            repo = parts[0].parent.name.replace("__", "/") if "__" in parts[0].parent.name else ""
            mid = db.new_id("mdl")
            name = Path(SPLIT_RE.sub(".gguf", parts[0].name)).stem
            s.add(db.Model(id=mid, repo=repo, name=name, quant=quant_of(name), files=files, local_dir=local_dir,
                           size_bytes=sum(p.stat().st_size for p in parts), status="ready", progress=1.0, meta=meta,
                           source="imported"))
            added.append(mid)
        s.commit()
    return added

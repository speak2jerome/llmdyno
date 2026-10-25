"""Docker image builds for the sandbox base, the quality-analysis image and each harness."""
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from .. import config, db
from . import catalog

SANDBOX = "llmdyno-sandbox:1"
QUALITY = "llmdyno-quality:1"
DOCKER_DIR = config.PKG / "docker"
IS_WIN = os.name == "nt"


_SIZE_UNITS = {"B": 1, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12}


def image_exists(tag):
    """Image id, unpacked size and creation time, or None. `docker image ls` reports the unpacked size that users
    recognise; `inspect` reports the compressed content size on the containerd store."""
    p = subprocess.run(["docker", "image", "ls", tag, "--format", "{{.ID}}|{{.Size}}|{{.CreatedAt}}"],
                       capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if IS_WIN else 0)
    line = p.stdout.strip().splitlines()[0] if p.returncode == 0 and p.stdout.strip() else ""
    if not line:
        return None
    iid, size, created = line.split("|", 2)
    num = "".join(ch for ch in size if ch.isdigit() or ch == ".")
    unit = size[len(num):].strip().upper()
    try:
        size_bytes = int(float(num) * _SIZE_UNITS.get(unit, 1))
    except ValueError:
        size_bytes = 0
    return {"id": iid[:12], "size_bytes": size_bytes, "created": created}


def _stream_build(ctx, args, cwd, dockerfile_text=None):
    """Run docker build, forwarding its log lines to the job and keeping a rough progress estimate."""
    tmp = None
    if dockerfile_text is not None:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".Dockerfile", delete=False, encoding="utf-8")
        tmp.write(dockerfile_text)
        tmp.close()
        args = args + ["-f", tmp.name]
    ctx.log("$ " + " ".join(args))
    proc = subprocess.Popen(args + ["--progress", "plain", "."], cwd=cwd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                            creationflags=subprocess.CREATE_NO_WINDOW if IS_WIN else 0)
    steps_total, last = 1, 0
    try:
        for line in proc.stdout:
            ctx.log(line.rstrip())
            if ctx.cancelled:
                proc.kill()
                ctx.check()
            if line.startswith("#") and "[" in line and "/" in line.split("]")[0]:
                try:
                    cur, tot = line.split("[", 1)[1].split("]")[0].split()[-1].split("/")
                    steps_total = max(steps_total, int(tot))
                    last = max(last, int(cur))
                    ctx.progress(min(0.95, last / steps_total), f"step {last}/{steps_total}")
                except (ValueError, IndexError):
                    pass
        proc.wait()
    finally:
        if tmp:
            Path(tmp.name).unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(f"docker build failed with exit code {proc.returncode} (see the log)")


def build_sandbox(ctx):
    _stream_build(ctx, ["docker", "build", "-t", SANDBOX, "-f", str(DOCKER_DIR / "sandbox.Dockerfile")], DOCKER_DIR)
    ctx.result = image_exists(SANDBOX) or {}


def build_quality(ctx):
    if not image_exists(SANDBOX):
        ctx.log("sandbox base missing: building it first")
        build_sandbox(ctx)
    _stream_build(ctx, ["docker", "build", "-t", QUALITY, "--build-arg", f"BASE={SANDBOX}",
                        "-f", str(DOCKER_DIR / "quality.Dockerfile")], DOCKER_DIR)
    ctx.result = image_exists(QUALITY) or {}


def set_build(harness_id, **fields):
    with db.Session() as s:
        b = s.get(db.HarnessBuild, harness_id) or db.HarnessBuild(harness_id=harness_id)
        for k, v in fields.items():
            setattr(b, k, v)
        s.merge(b)
        s.commit()


def build_harness(ctx):
    h = catalog.get(ctx.params["harness_id"], custom_manifests())
    set_build(h.id, status="building", image=h.image(), version=h.version, error="")
    try:
        if not image_exists(SANDBOX):
            ctx.log("sandbox base missing: building it first")
            build_sandbox(ctx)
        with tempfile.TemporaryDirectory() as d:
            _stream_build(ctx, ["docker", "build", "-t", h.image()], d, h.dockerfile(SANDBOX))
        info = image_exists(h.image())
        set_build(h.id, status="ready", built_at=time.time())
        ctx.result = {"image": h.image(), **(info or {})}
    except Exception as e:
        set_build(h.id, status="failed", error=str(e)[:1000])
        raise


def custom_manifests():
    with db.Session() as s:
        return [c.manifest for c in s.query(db.CustomHarness).all()]


def harness_status(h):
    info = image_exists(h.image())
    with db.Session() as s:
        b = s.get(db.HarnessBuild, h.id)
    status = "ready" if info else ("building" if b and b.status == "building" else
                                   "failed" if b and b.status == "failed" else "missing")
    return {"status": status, "image_info": info, "error": b.error if b and status == "failed" else "",
            "smoke": (b.smoke if b else {}) or {}, "built_at": b.built_at if b else None}


def remove_image(tag):
    p = subprocess.run(["docker", "image", "rm", tag], capture_output=True, text=True,
                       creationflags=subprocess.CREATE_NO_WINDOW if IS_WIN else 0)
    return p.returncode == 0, (p.stderr or p.stdout).strip()[-300:]


def dump_json(obj):
    return json.dumps(obj, indent=2)

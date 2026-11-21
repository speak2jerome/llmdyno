"""Portable harness runtimes for benchmarks that bring their own environment image (SWE-bench, Aider polyglot).

The normal path builds each harness on top of the LLMDyno sandbox. A SWE-bench task instead has to run inside the
official instance image, where the repository sits at /testbed with its conda environment already set up. Building a
harness into each of those images would cost hundreds of megabytes per task, so each harness is built once into a
self-contained folder (/opt/dyno-rt: Node, the agent CLI, ripgrep, or a standalone Python venv), copied into a
Docker volume, and mounted read-write into whichever environment image a benchmark names.

The runtime is built on Ubuntu 22.04 (the base of the SWE-bench images) so its dynamically linked tools also run on
any newer glibc, including the Debian 12 polyglot image. Python harnesses use python-build-standalone via uv, which
does not depend on the image's own Python."""
import hashlib
import subprocess
import tempfile

from ..system import specs as sysspecs
from . import catalog, images

RT = catalog.RT
NOWIN = subprocess.CREATE_NO_WINDOW if sysspecs.IS_WIN else 0
PLATFORM_ARCH = {"linux/amd64": "amd64", "linux/arm64": "arm64"}


def sh(args, timeout=600):
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                          creationflags=NOWIN)


def host_platform():
    return "linux/arm64" if sysspecs.norm_arch() == "arm64" else "linux/amd64"


def dockerfile(h):
    lines = [
        "FROM node:24-bookworm-slim AS node",
        "FROM python:3.12-slim-bookworm AS uv",
        f"RUN pip install --no-cache-dir uv=={catalog.UV_VERSION}",
        "FROM ubuntu:22.04",
        "ENV DEBIAN_FRONTEND=noninteractive",
        "RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates ripgrep git "
        "&& rm -rf /var/lib/apt/lists/*",
        f"COPY --from=node /usr/local/bin/node {RT}/bin/node",
        f"COPY --from=node /usr/local/lib/node_modules {RT}/lib/node_modules",
        "COPY --from=uv /usr/local/bin/uv /usr/local/bin/uv",
        f"RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js {RT}/bin/npm "
        f"&& ln -s ../lib/node_modules/npm/bin/npx-cli.js {RT}/bin/npx && cp /usr/bin/rg {RT}/bin/rg",
        f"ENV PATH={RT}/bin:$PATH npm_config_prefix={RT} UV_PYTHON_INSTALL_DIR={RT}/python "
        "UV_PYTHON_PREFERENCE=only-managed UV_NO_CACHE=1",
        *h.runtime_install(),
        f"RUN chmod -R a+rX {RT}",
        f'LABEL org.llmdyno.role=runtime org.llmdyno.harness="{h.id}" org.llmdyno.version="{h.version}"',
    ]
    return "\n".join(lines) + "\n"


def tag(h, platform):
    digest = hashlib.sha1(dockerfile(h).encode()).hexdigest()[:8]
    return f"llmdyno-rt-{h.id}:{h.version}-{PLATFORM_ARCH.get(platform, 'amd64')}-{digest}"


def status(h, platform=None):
    platform = platform or host_platform()
    info = images.image_exists(tag(h, platform))
    return {"tag": tag(h, platform), "platform": platform, "ready": bool(info), "image_info": info}


def build(ctx, h, platform):
    """Build the runtime image (needs the network: npm / PyPI / apt)."""
    t = tag(h, platform)
    with tempfile.TemporaryDirectory() as d:
        images._stream_build(ctx, ["docker", "build", "--platform", platform, "-t", t], d, dockerfile(h))
    return t


def volume_name(h, platform):
    return "dyno-" + tag(h, platform).replace(":", "-").replace(".", "_")


def ensure(ctx, h, platform, log=print):
    """Runtime volume for a harness on a platform, building the image and filling the volume when missing."""
    t = tag(h, platform)
    if not images.image_exists(t):
        log(f"building the portable {h.name} runtime for {platform} (one time, a few minutes)")
        build(ctx, h, platform)
    vol = volume_name(h, platform)
    probe = sh(["docker", "run", "--rm", "--platform", platform, "-v", f"{vol}:/rt", t, "test", "-f", "/rt/.complete"],
               timeout=300)
    if probe.returncode != 0:
        log(f"filling volume {vol}")
        sh(["docker", "volume", "create", "--label", "org.llmdyno.role=runtime", vol])
        r = sh(["docker", "run", "--rm", "--platform", platform, "-v", f"{vol}:/rt", t, "sh", "-c",
                f"rm -rf /rt/* /rt/.complete; cp -a {RT}/. /rt/ && touch /rt/.complete"], timeout=900)
        if r.returncode != 0:
            raise RuntimeError(f"could not fill the runtime volume: {(r.stderr or r.stdout)[-400:]}")
    return {"volume": vol, "image": t, "platform": platform}


def env(h):
    base = {"PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1", "npm_config_offline": "true",
            "NODE_PATH": f"{RT}/lib/node_modules", "DO_NOT_TRACK": "1", "NO_UPDATE_NOTIFIER": "1",
            "PYTHONDONTWRITEBYTECODE": "1"}
    return {**base, **h.runtime_env()}


PREAMBLE = (
    "# environment image: activate its toolchain, then add the mounted harness runtime\n"
    "if [ -f /opt/miniconda3/bin/activate ]; then . /opt/miniconda3/bin/activate testbed >/dev/null 2>&1 || true; fi\n"
    f"export PATH=\"$PATH:{RT}/bin\"\n"
    "git config --global --add safe.directory '*' 2>/dev/null\n"
    "git config --global user.email >/dev/null 2>&1 || { git config --global user.email agent@llmdyno.local; "
    "git config --global user.name 'LLMDyno agent'; }\n"
)

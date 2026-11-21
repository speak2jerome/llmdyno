"""Public benchmarks: SWE-bench and Aider polyglot imports, the SWE-bench harness and predictions."""
import re
from .. import config, db, jobs
from ..benchmarks import polyglot, swebench
from ..benchmarks import registry as benches
from ..harnesses import images, runtime
from .. import errors


def _count(prefix):
    return sum(1 for b in benches.all_benchmarks() if b["id"].startswith(prefix) and not b["builtin"])


def import_catalog():
    sw = swebench.harness_status()
    poly = images.image_exists(polyglot.IMAGE)
    return {
        "swebench": {"datasets": [{"id": k, "name": v["name"], "size": v["size"], "about": v["about"], "hf": v["hf"]}
                                  for k, v in swebench.DATASETS.items()],
                     "imported": _count("swe_"), "harness": sw, "homepage": swebench.HOMEPAGE,
                     "harness_version": (config.get("swebench") or {}).get("harness_version")},
        "polyglot": {"languages": polyglot.LANGS, "imported": _count("pg_"), "image": polyglot.IMAGE,
                     "image_info": poly, "context_ready": polyglot.context_ready(), "homepage": polyglot.HOMEPAGE,
                     "repo": f"https://github.com/{polyglot.REPO}"},
        "runtime_platform": runtime.host_platform(),
    }


def import_swebench(body: dict):
    key = body.get("dataset", "verified_mini")
    if key not in swebench.DATASETS:
        raise errors.http(400, f"unknown dataset {key}")
    ids = [x for x in body.get("instance_ids") or [] if re.fullmatch(r"[\w.\-]+__[\w.\-]+-\d+", x)]
    limit = int(body.get("limit") or 0)
    if limit < 0 or limit > 2000:
        raise errors.http(400, "limit must be 0-2000")
    name = swebench.DATASETS[key]["name"]
    return {"job_id": jobs.submit("import", f"Import {name}" + (f" (first {limit})" if limit else ""),
                                  swebench.import_job, {"dataset": key, "instance_ids": ids, "limit": limit},
                                  ref="swebench", group="import")}


def import_polyglot(body: dict | None = None):
    body = {} if body is None else body
    langs = [x for x in body.get("languages") or list(polyglot.LANGS) if x in polyglot.LANGS]
    if not langs:
        raise errors.http(400, "choose at least one language")
    return {"job_id": jobs.submit("import", "Import Aider polyglot", polyglot.import_job, {"languages": langs},
                                  ref="polyglot", group="import")}


def install_swebench_harness():
    v = (config.get("swebench") or {}).get("harness_version")
    return {"job_id": jobs.submit("install", f"Install SWE-bench harness {v}", swebench.install_harness, {"version": v},
                                  ref="swebench_harness")}


def build_polyglot_image():
    if not polyglot.context_ready():
        raise errors.http(409, "import the polyglot benchmark first")
    return {"job_id": jobs.submit("build", "Build polyglot toolchain image", polyglot.build_image, ref="polyglot_image")}


def remove_imported(kind: str):
    """Delete every imported benchmark of one kind (the dataset can be imported again at any time)."""
    prefix = {"swebench": "swe_", "polyglot": "pg_"}.get(kind)
    if not prefix:
        raise errors.http(404, "unknown import")
    n = 0
    for b in benches.all_benchmarks():
        if b["id"].startswith(prefix) and not b["builtin"]:
            benches.delete_custom(b["id"])
            n += 1
    with db.Session() as s:
        s.query(db.Suite).filter(db.Suite.id.like(f"suite_{kind}%")).delete(synchronize_session=False)
        s.commit()
    return {"removed": n}

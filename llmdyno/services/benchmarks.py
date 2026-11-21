"""Benchmarks and suites: built-in, custom (editor and zip) and validation."""
from .. import db, jobs
from ..benchmarks import registry as benches
from ..benchmarks import validate as bvalidate
from .. import errors
from ._common import _get, download


def list_benchmarks():
    return benches.all_benchmarks()


def benchmark_detail(bid: str):
    return benches.detail(bid)


def benchmark_spec(bid: str):
    return benches.custom_spec(bid)


def create_benchmark(body: dict):
    return benches.save_custom(body)


def update_benchmark(bid: str, body: dict):
    body["id"] = bid
    if benches.get(bid)["builtin"]:
        raise errors.http(403, "built-in benchmarks are read-only; duplicate it to edit")
    return benches.save_custom(body, overwrite=True)


def delete_benchmark(bid: str):
    benches.delete_custom(bid)
    return {"ok": True}


def duplicate_benchmark(bid: str, body: dict):
    return benches.duplicate(bid, body.get("new_id", ""))


def export_benchmark(bid: str):
    return download(benches.export_zip(bid), f"{bid}.zip", "application/zip")


def validate_benchmark(bid: str):
    benches.get(bid)
    return {"job_id": jobs.submit("validate", f"Validate grader: {bid}", bvalidate.validate, {"benchmark_id": bid}, ref=bid)}


def list_suites():
    return benches.suites()


def create_suite(body: dict):
    name = (body.get("name") or "").strip()
    ids = body.get("benchmark_ids") or []
    if not name or not ids:
        raise errors.http(400, "a suite needs a name and at least one benchmark")
    known = {b["id"] for b in benches.all_benchmarks()}
    if set(ids) - known:
        raise errors.http(400, f"unknown benchmarks: {', '.join(sorted(set(ids) - known))}")
    sid = db.new_id("suite")
    with db.Session() as s:
        s.add(db.Suite(id=sid, name=name, description=body.get("description", ""), benchmark_ids=ids))
        s.commit()
    return _get(db.Suite, sid)


def update_suite(sid: str, body: dict):
    if sid.startswith("suite_") and any(s["id"] == sid for s in benches.BUILTIN_SUITES):
        raise errors.http(403, "built-in suites are read-only")
    with db.Session() as s:
        obj = s.get(db.Suite, sid)
        if not obj:
            raise errors.http(404, "suite not found")
        if "name" in body:
            obj.name = body["name"].strip() or obj.name
        if "description" in body:
            obj.description = body["description"]
        if "benchmark_ids" in body:
            if not body["benchmark_ids"]:
                raise errors.http(400, "a suite needs at least one benchmark")
            obj.benchmark_ids = body["benchmark_ids"]
        s.commit()
    return _get(db.Suite, sid)


def delete_suite(sid: str):
    if any(s["id"] == sid for s in benches.BUILTIN_SUITES):
        raise errors.http(403, "built-in suites cannot be deleted")
    with db.Session() as s:
        s.query(db.Suite).filter(db.Suite.id == sid).delete()
        s.commit()
    return {"ok": True}

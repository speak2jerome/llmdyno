"""External benchmarks and references: SWE-bench and Aider polyglot imports, the official SWE-bench harness, SWE-bench
predictions export, portable harness runtimes and Artificial Analysis reference numbers.

The logic lives in llmdyno/services; these routes only map HTTP to service calls."""
from fastapi import APIRouter, Body, Query  # noqa: F401 - used in route signatures
from fastapi.responses import FileResponse, PlainTextResponse, Response  # noqa: F401

from ..services import harnesses as svc_harnesses
from ..services import imports as svc_imports
from ..services import plans as svc_plans
from ..services import references as svc_references

router = APIRouter()


def _send(d):
    """A service download record as an HTTP response (attachment)."""
    if d.get("path"):
        return FileResponse(d["path"], filename=d["filename"], media_type=d["media_type"])
    return Response(d["content"], media_type=d["media_type"],
                    headers={"Content-Disposition": f'attachment; filename="{d["filename"]}"'})


@router.get("/imports")
def import_catalog():
    return svc_imports.import_catalog()


@router.post("/imports/swebench")
def import_swebench(body: dict=Body(...)):
    return svc_imports.import_swebench(body=body)


@router.post("/imports/polyglot")
def import_polyglot(body: dict=Body(default={})):
    return svc_imports.import_polyglot(body=body)


@router.post("/imports/swebench/harness")
def install_swebench_harness():
    return svc_imports.install_swebench_harness()


@router.post("/imports/polyglot/image")
def build_polyglot_image():
    return svc_imports.build_polyglot_image()


@router.delete("/imports/{kind}")
def remove_imported(kind: str):
    return svc_imports.remove_imported(kind=kind)


@router.get("/plans/{pid}/swebench-predictions")
def swebench_predictions(pid: str):
    return _send(svc_plans.swebench_predictions(pid=pid))


@router.get("/harnesses/{hid}/runtime")
def harness_runtime(hid: str, platform: str=''):
    return svc_harnesses.harness_runtime(hid=hid, platform=platform)


@router.post("/harnesses/{hid}/runtime")
def build_harness_runtime(hid: str, body: dict=Body(default={})):
    return svc_harnesses.build_harness_runtime(hid=hid, body=body)


@router.get("/references/aa")
def aa_reference():
    return svc_references.aa_reference()


@router.post("/references/aa/refresh")
def aa_refresh(body: dict=Body(default={})):
    return svc_references.aa_refresh(body=body)


@router.put("/settings/aa-key")
def set_aa_key(body: dict=Body(...)):
    return svc_references.set_aa_key(body=body)


@router.delete("/settings/aa-key")
def delete_aa_key():
    return svc_references.delete_aa_key()


@router.put("/references/aa/override")
def aa_override(body: dict=Body(...)):
    return svc_references.aa_override(body=body)

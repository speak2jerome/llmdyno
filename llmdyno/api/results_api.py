"""Results: scored runs and configurations for the dashboard, judge agreement, exports and the sample dataset.

The logic lives in llmdyno/services; these routes only map HTTP to service calls."""
from fastapi import APIRouter, Body, Query  # noqa: F401 - used in route signatures
from fastapi.responses import FileResponse, PlainTextResponse, Response  # noqa: F401

from ..services import results as svc_results

from ..services._common import _labels  # noqa: E402,F401 - used by llmdyno.lib
from ..services.results import collect  # noqa: E402,F401

router = APIRouter()


def _send(d):
    """A service download record as an HTTP response (attachment)."""
    if d.get("path"):
        return FileResponse(d["path"], filename=d["filename"], media_type=d["media_type"])
    return Response(d["content"], media_type=d["media_type"],
                    headers={"Content-Disposition": f'attachment; filename="{d["filename"]}"'})


@router.get("/results")
def results(plan_ids: str='', weights: str='', quality_weights: str='', pass_threshold: float=0.8, efficiency_ref: str='local', include_sample: bool=True, benchmark_ids: str=''):
    return svc_results.results(plan_ids=plan_ids, weights=weights, quality_weights=quality_weights, pass_threshold=pass_threshold, efficiency_ref=efficiency_ref, include_sample=include_sample, benchmark_ids=benchmark_ids)


@router.get("/results/export")
def export(plan_ids: str='', level: str='runs', fmt: str='csv', weights: str='', quality_weights: str='', benchmark_ids: str=''):
    return _send(svc_results.export(plan_ids=plan_ids, level=level, fmt=fmt, weights=weights,
                                    quality_weights=quality_weights, benchmark_ids=benchmark_ids))


@router.get("/sample")
def sample_status():
    return svc_results.sample_status()


@router.post("/sample")
def load_sample():
    return svc_results.load_sample()


@router.delete("/sample")
def unload_sample():
    return svc_results.unload_sample()


@router.post("/results/weights")
def save_weights(body: dict=Body(...)):
    return svc_results.save_weights(body=body)

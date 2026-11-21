"""REST endpoints for setup, models, profiles, providers, harnesses, benchmarks, plans, runs and jobs.

The logic lives in llmdyno/services; these routes only map HTTP to service calls."""
from fastapi import APIRouter, Body, Query  # noqa: F401 - used in route signatures
from fastapi.responses import FileResponse, PlainTextResponse, Response  # noqa: F401

from ..services import benchmarks as svc_benchmarks
from ..services import harnesses as svc_harnesses
from ..services import judging as svc_judging
from ..services import models as svc_models
from ..services import plans as svc_plans
from ..services import profiles as svc_profiles
from ..services import providers as svc_providers
from ..services import runs as svc_runs
from ..services import settings as svc_settings
from ..services import system as svc_system

router = APIRouter()


def _send(d):
    """A service download record as an HTTP response (attachment)."""
    if d.get("path"):
        return FileResponse(d["path"], filename=d["filename"], media_type=d["media_type"])
    return Response(d["content"], media_type=d["media_type"],
                    headers={"Content-Disposition": f'attachment; filename="{d["filename"]}"'})


@router.get("/system/specs")
def get_specs(refresh: bool=False):
    return svc_system.get_specs(refresh=refresh)


@router.get("/system/deps")
def get_deps(refresh: bool=False):
    return svc_system.get_deps(refresh=refresh)


@router.post("/system/deps/{dep_id}/action")
def dep_action(dep_id: str, body: dict=Body(default={})):
    return svc_system.dep_action(dep_id=dep_id, body=body)


@router.get("/settings")
def get_settings():
    return svc_settings.get_settings()


@router.patch("/settings")
def patch_settings(body: dict=Body(...)):
    return svc_settings.patch_settings(body=body)


@router.put("/settings/hf-token")
def set_hf_token(body: dict=Body(...)):
    return svc_settings.set_hf_token(body=body)


@router.delete("/settings/hf-token")
def del_hf_token():
    return svc_settings.del_hf_token()


@router.post("/system/cleanup")
def cleanup_containers():
    return svc_system.cleanup_containers()


@router.get("/system/gpu")
def system_gpu():
    return svc_system.system_gpu()


@router.get("/system/active")
def system_active():
    return svc_system.system_active()


@router.post("/system/panic")
def system_panic():
    return svc_system.system_panic()


@router.get("/hub/search")
def hub_search(q: str='', sort: str='downloads', limit: int=30):
    return svc_models.hub_search(q=q, sort=sort, limit=limit)


@router.get("/hub/repo")
def hub_repo(repo: str):
    return svc_models.hub_repo(repo=repo)


@router.post("/hub/estimate")
def hub_estimate(body: dict=Body(...)):
    return svc_models.hub_estimate(body=body)


@router.get("/models")
def list_models():
    return svc_models.list_models()


@router.post("/models/download")
def model_download(body: dict=Body(...)):
    return svc_models.model_download(body=body)


@router.post("/models/{mid}/pause")
def model_pause(mid: str):
    return svc_models.model_pause(mid=mid)


@router.post("/models/{mid}/resume")
def model_resume(mid: str):
    return svc_models.model_resume(mid=mid)


@router.delete("/models/{mid}")
def model_delete(mid: str, delete_files: bool=False):
    return svc_models.model_delete(mid=mid, delete_files=delete_files)


@router.post("/models/import")
def model_import(body: dict=Body(...)):
    return svc_models.model_import(body=body)


@router.get("/models/{mid}")
def model_detail(mid: str):
    return svc_models.model_detail(mid=mid)


@router.get("/models/recommended/list")
def recommended():
    return svc_models.recommended()


@router.get("/profiles")
def list_profiles():
    return svc_profiles.list_profiles()


@router.get("/profiles/defaults")
def profile_defaults(kind: str='local', model_id: str | None=None):
    return svc_profiles.profile_defaults(kind=kind, model_id=model_id)


@router.post("/profiles")
def create_profile(body: dict=Body(...)):
    return svc_profiles.create_profile(body=body)


@router.get("/profiles/{pid}")
def get_profile(pid: str):
    return svc_profiles.get_profile(pid=pid)


@router.patch("/profiles/{pid}")
def patch_profile(pid: str, body: dict=Body(...)):
    return svc_profiles.patch_profile(pid=pid, body=body)


@router.delete("/profiles/{pid}")
def delete_profile(pid: str):
    return svc_profiles.delete_profile(pid=pid)


@router.post("/profiles/{pid}/duplicate")
def duplicate_profile(pid: str):
    return svc_profiles.duplicate_profile(pid=pid)


@router.post("/profiles/check")
def check_profile(body: dict=Body(...)):
    return svc_profiles.check_profile(body=body)


@router.post("/profiles/{pid}/smoke")
def smoke_profile(pid: str):
    return svc_profiles.smoke_profile(pid=pid)


@router.get("/profiles/{pid}/export")
def export_profile(pid: str):
    return _send(svc_profiles.export_profile(pid=pid))


@router.post("/profiles/import")
def import_profile(body: dict=Body(...)):
    return svc_profiles.import_profile(body=body)


@router.get("/vendors")
def list_vendors():
    return svc_providers.list_vendors()


@router.get("/providers/local-servers")
def local_servers():
    return svc_providers.local_servers()


@router.get("/providers")
def list_providers():
    return svc_providers.list_providers()


@router.post("/providers")
def create_provider(body: dict=Body(...)):
    return svc_providers.create_provider(body=body)


@router.patch("/providers/{pid}")
def patch_provider(pid: str, body: dict=Body(...)):
    return svc_providers.patch_provider(pid=pid, body=body)


@router.put("/providers/{pid}/key")
def set_provider_key(pid: str, body: dict=Body(...)):
    return svc_providers.set_provider_key(pid=pid, body=body)


@router.delete("/providers/{pid}/key")
def del_provider_key(pid: str):
    return svc_providers.del_provider_key(pid=pid)


@router.post("/providers/{pid}/test")
def test_provider(pid: str):
    return svc_providers.test_provider(pid=pid)


@router.post("/providers/{pid}/reset-spend")
def reset_spend(pid: str):
    return svc_providers.reset_spend(pid=pid)


@router.delete("/providers/{pid}")
def delete_provider(pid: str):
    return svc_providers.delete_provider(pid=pid)


@router.get("/pricing/lookup")
def pricing_lookup(vendor: str, model: str):
    return svc_providers.pricing_lookup(vendor=vendor, model=model)


@router.get("/harnesses")
def list_harnesses():
    return svc_harnesses.list_harnesses()


@router.post("/harnesses/{hid}/build")
def build_harness(hid: str):
    return svc_harnesses.build_harness(hid=hid)


@router.delete("/harnesses/{hid}/image")
def remove_harness_image(hid: str):
    return svc_harnesses.remove_harness_image(hid=hid)


@router.get("/harnesses/{hid}/dockerfile", response_class=PlainTextResponse)
def harness_dockerfile(hid: str):
    return svc_harnesses.harness_dockerfile(hid=hid)


@router.get("/harnesses/{hid}/preview")
def harness_preview(hid: str, api_style: str='openai-chat'):
    return svc_harnesses.harness_preview(hid=hid, api_style=api_style)


@router.get("/harnesses-schema")
def harness_schema():
    return svc_harnesses.harness_schema()


@router.post("/harnesses/custom")
def add_custom_harness(body: dict=Body(...)):
    return svc_harnesses.add_custom_harness(body=body)


@router.put("/harnesses/custom/{hid}")
def update_custom_harness(hid: str, body: dict=Body(...)):
    return svc_harnesses.update_custom_harness(hid=hid, body=body)


@router.delete("/harnesses/custom/{hid}")
def delete_custom_harness(hid: str):
    return svc_harnesses.delete_custom_harness(hid=hid)


@router.get("/benchmarks")
def list_benchmarks():
    return svc_benchmarks.list_benchmarks()


@router.get("/benchmarks/{bid}")
def benchmark_detail(bid: str):
    return svc_benchmarks.benchmark_detail(bid=bid)


@router.get("/benchmarks/{bid}/spec")
def benchmark_spec(bid: str):
    return svc_benchmarks.benchmark_spec(bid=bid)


@router.post("/benchmarks")
def create_benchmark(body: dict=Body(...)):
    return svc_benchmarks.create_benchmark(body=body)


@router.put("/benchmarks/{bid}")
def update_benchmark(bid: str, body: dict=Body(...)):
    return svc_benchmarks.update_benchmark(bid=bid, body=body)


@router.delete("/benchmarks/{bid}")
def delete_benchmark(bid: str):
    return svc_benchmarks.delete_benchmark(bid=bid)


@router.post("/benchmarks/{bid}/duplicate")
def duplicate_benchmark(bid: str, body: dict=Body(...)):
    return svc_benchmarks.duplicate_benchmark(bid=bid, body=body)


@router.get("/benchmarks/{bid}/export")
def export_benchmark(bid: str):
    return _send(svc_benchmarks.export_benchmark(bid=bid))


@router.post("/benchmarks/{bid}/validate")
def validate_benchmark(bid: str):
    return svc_benchmarks.validate_benchmark(bid=bid)


@router.get("/suites")
def list_suites():
    return svc_benchmarks.list_suites()


@router.post("/suites")
def create_suite(body: dict=Body(...)):
    return svc_benchmarks.create_suite(body=body)


@router.put("/suites/{sid}")
def update_suite(sid: str, body: dict=Body(...)):
    return svc_benchmarks.update_suite(sid=sid, body=body)


@router.delete("/suites/{sid}")
def delete_suite(sid: str):
    return svc_benchmarks.delete_suite(sid=sid)


@router.post("/plans/preflight")
def plan_preflight(body: dict=Body(...)):
    return svc_plans.plan_preflight(body=body)


@router.post("/plans")
def create_plan(body: dict=Body(...)):
    return svc_plans.create_plan(body=body)


@router.get("/plans")
def list_plans():
    return svc_plans.list_plans()


@router.get("/plans/{pid}")
def get_plan(pid: str):
    return svc_plans.get_plan(pid=pid)


@router.post("/plans/{pid}/pause")
def pause_plan(pid: str):
    return svc_plans.pause_plan(pid=pid)


@router.post("/plans/{pid}/resume")
def resume_plan(pid: str):
    return svc_plans.resume_plan(pid=pid)


@router.post("/plans/{pid}/cancel")
def cancel_plan(pid: str):
    return svc_plans.cancel_plan(pid=pid)


@router.post("/plans/{pid}/retry")
def retry_plan(pid: str, body: dict=Body(default={})):
    return svc_plans.retry_plan(pid=pid, body=body)


@router.patch("/plans/{pid}")
def rename_plan(pid: str, body: dict=Body(...)):
    return svc_plans.rename_plan(pid=pid, body=body)


@router.delete("/plans/{pid}")
def delete_plan(pid: str, delete_files: bool=True):
    return svc_plans.delete_plan(pid=pid, delete_files=delete_files)


@router.get("/runs/{rid}")
def get_run(rid: str):
    return svc_runs.get_run(rid=rid)


@router.post("/runs/{rid}/cancel")
def cancel_run(rid: str):
    return svc_runs.cancel_run(rid=rid)


@router.post("/runs/{rid}/retry")
def retry_run(rid: str):
    return svc_runs.retry_run(rid=rid)


@router.post("/runs/{rid}/regrade")
def regrade_run(rid: str):
    return svc_runs.regrade_run(rid=rid)


@router.get("/runs/{rid}/transcript")
def run_transcript(rid: str, start: int=0, limit: int=20000):
    return svc_runs.run_transcript(rid=rid, start=start, limit=limit)


@router.get("/runs/{rid}/proxy")
def run_proxy(rid: str):
    return svc_runs.run_proxy(rid=rid)


@router.get("/runs/{rid}/files")
def run_files(rid: str, root: str='workspace'):
    return svc_runs.run_files(rid=rid, root=root)


@router.get("/runs/{rid}/file")
def run_file(rid: str, path: str, root: str='workspace'):
    return PlainTextResponse(svc_runs.run_file(rid=rid, path=path, root=root))


@router.get("/runs/{rid}/log")
def run_log(rid: str, name: str):
    return PlainTextResponse(svc_runs.run_log(rid=rid, name=name))


@router.get("/runs/{rid}/gpu")
def run_gpu(rid: str, max_points: int=600):
    return svc_runs.run_gpu(rid=rid, max_points=max_points)


@router.get("/runs/{rid}/download")
def run_download(rid: str):
    return _send(svc_runs.run_download(rid=rid))


@router.get("/jobs")
def list_jobs(active: bool=False, limit: int=100, kind: str | None=None):
    return svc_system.list_jobs(active=active, limit=limit, kind=kind)


@router.get("/jobs/{jid}")
def get_job(jid: str):
    return svc_system.get_job(jid=jid)


@router.post("/jobs/{jid}/cancel")
def cancel_job(jid: str):
    return svc_system.cancel_job(jid=jid)


@router.delete("/jobs")
def clear_jobs():
    return svc_system.clear_jobs()


@router.get("/judge/defaults")
def judge_defaults():
    return svc_judging.judge_defaults()


@router.post("/judge")
def start_judge(body: dict=Body(...)):
    return svc_judging.start_judge(body=body)


@router.get("/reviews")
def list_reviews(plan_id: str | None=None, run_id: str | None=None):
    return svc_judging.list_reviews(plan_id=plan_id, run_id=run_id)


@router.delete("/reviews")
def delete_reviews(judge_id: str=Query(...), plan_id: str | None=None):
    return svc_judging.delete_reviews(judge_id=judge_id, plan_id=plan_id)

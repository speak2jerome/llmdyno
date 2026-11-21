"""The Python library facade (import llmdyno): no Docker, no network, the test session's temporary data folder."""
import subprocess
import sys

import pytest

import llmdyno
from llmdyno import lib


def test_import_is_light_and_lazy():
    code = ("import sys, llmdyno; assert 'llmdyno.lib' not in sys.modules and 'llmdyno.db' not in sys.modules; "
            "llmdyno.list_benchmarks; assert 'llmdyno.lib' in sys.modules; "
            "heavy = [m for m in ('llmdyno.db', 'llmdyno.services', 'fastapi', 'sqlalchemy') if m in sys.modules]; "
            "assert not heavy, heavy; print('ok')")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    for name in ("bench", "cloud_model", "local_model", "Results", "PreflightError"):
        assert name in dir(llmdyno) and callable(getattr(llmdyno, name))
    with pytest.raises(AttributeError):
        llmdyno.no_such_thing  # noqa: B018


def test_init_switches_data_folders(tmp_path):
    before = llmdyno.data_dir()
    try:
        assert llmdyno.init(tmp_path / "other") == (tmp_path / "other").resolve()
        assert (tmp_path / "other" / "llmdyno.db").exists()
        assert llmdyno.list_profiles() == []
    finally:
        llmdyno.init(before)
    assert llmdyno.data_dir() == before


def test_cloud_model_is_idempotent_and_validates_settings():
    p = llmdyno.cloud_model("custom", "lib-test-model", base_url="http://localhost:9/v1", pricing=None,
                            reasoning_effort="low", ctx=32768)
    assert p.kind == "cloud" and p.params["reasoning_effort"] == "low" and p.params["ctx"] == 32768
    again = llmdyno.cloud_model("custom", "lib-test-model", base_url="http://localhost:9/v1", pricing=None,
                                reasoning_effort="low", ctx=65536)
    assert again.id == p.id and again.params["ctx"] == 65536
    assert llmdyno.profile(p.name) == p and llmdyno.profile(p.id) == p
    assert p.update(max_output_tokens=4096).params["max_output_tokens"] == 4096
    with pytest.raises(TypeError, match="unknown cloud setting"):
        llmdyno.cloud_model("custom", "lib-test-model", base_url="http://localhost:9/v1", pricing=None, cache_k="q8_0")


def test_cloud_model_needs_a_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(llmdyno.LLMDynoError, match="OPENAI_API_KEY"):
        llmdyno.cloud_model("openai", "gpt-lib-test", pricing=None)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    p = llmdyno.cloud_model("openai", "gpt-lib-test", pricing={"input": 1.0, "output": 4.0}, budget_usd=0.5)
    from llmdyno import secrets
    from llmdyno.providers import registry
    assert secrets.get(registry.secret_name(p.info["provider_id"])) == "sk-test-not-a-real-key"
    assert p.info["pricing"]["output"] == 4.0
    from llmdyno.api import routes
    prov = next(x for x in routes.list_providers() if x["id"] == p.info["provider_id"])
    assert prov["budget_usd"] == 0.5 and prov["has_key"]
    with pytest.raises(llmdyno.LLMDynoError, match="unknown vendor"):
        llmdyno.cloud_model("nope", "x")


def test_local_model_errors_without_network():
    with pytest.raises(llmdyno.LLMDynoError, match="either"):
        llmdyno.local_model()
    with pytest.raises(llmdyno.NotFoundError):
        llmdyno.local_model(path="Z:/definitely/not/here.gguf")
    with pytest.raises(llmdyno.NotFoundError, match="not downloaded"):
        llmdyno.local_model("someone/Some-Model-GGUF", quant="Q4_K_M", download=False)


def test_local_settings_map_to_profile_params():
    assert lib._params("local", {"kv_cache": "q4_0", "temperature": 0.6, "ctx": 8192}) == {
        "cache_k": "q4_0", "cache_v": "q4_0", "ctx": 8192, "sampling": {"temperature": 0.6}}
    with pytest.raises(TypeError, match="unknown local setting"):
        lib._params("local", {"reasoning_effort": "high"})


def test_profile_lookup_errors():
    with pytest.raises(llmdyno.NotFoundError, match="no profile"):
        llmdyno.profile("there is no such profile")


def test_bench_reports_blocking_problems_before_starting():
    p = llmdyno.cloud_model("custom", "lib-test-model", base_url="http://localhost:9/v1", pricing=None)
    with pytest.raises(llmdyno.PreflightError) as e:
        llmdyno.bench(p, benchmarks="no_such_benchmark", harnesses="pi", quiet=True)
    assert any("Unknown benchmark" in x for x in e.value.problems)
    assert llmdyno.list_plans() == [] or all(isinstance(x, llmdyno.Plan) for x in llmdyno.list_plans())


def test_public_names_never_shadow_submodules():
    import pkgutil
    subs = {m.name for m in pkgutil.iter_modules(llmdyno.__path__)}
    assert not subs & set(llmdyno.__all__), subs & set(llmdyno.__all__)
    from llmdyno import profiles as profiles_module
    assert hasattr(profiles_module, "merge")              # the internal module, untouched by the facade


def test_benchmarks_and_suites_listing():
    ids = {b["id"] for b in llmdyno.list_benchmarks()}
    assert "t0_smoke_cli" in ids
    assert all(b["category"] == "Smoke test" for b in llmdyno.list_benchmarks(category="smoke test"))
    assert any(s["id"] == "suite_quick" for s in llmdyno.list_suites())


def test_results_from_the_bundled_sample(tmp_path):
    from llmdyno.api import results_api
    loaded_here = not results_api.sample_status()["loaded"]
    if loaded_here:
        results_api.load_sample()
    try:
        r = llmdyno.results("plan_sample_round1")
        lb = r.leaderboard()
        assert len(lb) == 15 and lb[0]["rank"] == 1 and lb[0]["final"] >= lb[-1]["final"]
        assert len(r.runs()) == 75 and r.public() == []
        text = str(r)
        assert "Profile" in text and lb[0]["profile"] in text
        csv_text = r.to_csv(tmp_path / "lb.csv")
        assert csv_text.splitlines()[0].startswith("rank,profile,harness,final")
        assert (tmp_path / "lb.csv").exists()
        assert r.to_json()["leaderboard"][0]["profile"] == lb[0]["profile"]
        heavy = llmdyno.results("plan_sample_round1", correctness=100, instruction_following=0, quality=0, efficiency=0)
        assert heavy.leaderboard()[0]["final"] == heavy.leaderboard()[0]["correctness"]
        assert "<table" in r._repr_html_() and "llmdyno-bar" in r._repr_html_()
        p = llmdyno.plan("plan_sample_round1")
        assert p.status == "done" and len(p.runs()) == 75
        assert len(p.results().leaderboard()) == 15                  # a single Plan, not a list of them
        assert len(llmdyno.results([p, "plan_sample_round1"]).leaderboard()) == 15
    finally:
        if loaded_here:
            results_api.unload_sample()


def test_sdk_modules_only_reach_llmdyno_through_the_backend():
    """SDK code talks to services via call(), so the same objects work against a remote LLMDyno (0.6)."""
    import ast
    import pathlib
    allowed = {"errors", "__version__", "integrations"}
    local_only = {"_backend.py": {"config", "db", "events", "inference"}, "_core.py": {"config"}, "ui.py": {"config"},
                  "parity.py": {"sdk", "server"},
                  "remote.py": {"server"}}                  # the route table of this version, to map calls to URLs           # parity reads the local route table
    sdk = pathlib.Path(llmdyno.__file__).parent / "sdk"
    for f in sdk.glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level >= 2:
                names = {node.module.split(".")[0]} if node.module else {a.name for a in node.names}
                extra = names - allowed - local_only.get(f.name, set())
                assert not extra, f"{f.name} imports {extra}; go through call('area.function') instead"


def test_every_sdk_call_goes_through_the_installed_backend():
    from llmdyno.sdk import _backend

    class Canned(_backend.Backend):
        kind = "canned"

        def __init__(self):
            self.ops = []

        def call(self, op, **kwargs):
            self.ops.append(op)
            return {"profiles.list_profiles": [{"id": "prof_x", "name": "Canned", "kind": "cloud", "params": {}}],
                    "benchmarks.list_suites": [{"id": "suite_canned"}]}[op]

    fake = Canned()
    prev = _backend.use(fake)
    try:
        assert [p.name for p in llmdyno.list_profiles()] == ["Canned"]
        assert llmdyno.profile("canned").id == "prof_x"
        assert llmdyno.list_suites() == [{"id": "suite_canned"}]
        with pytest.raises(llmdyno.LLMDynoError, match="remote"):
            llmdyno.init()
    finally:
        _backend.use(prev)
    assert fake.ops == ["profiles.list_profiles", "profiles.list_profiles", "benchmarks.list_suites"]


def test_handles_compare_by_kind_and_id():
    a, b = llmdyno.Job("job_1"), llmdyno.Job("job_1")
    assert a == b and hash(a) == hash(b) and a != llmdyno.Plan("job_1")
    with pytest.raises(llmdyno.NotFoundError):
        llmdyno.job("job_does_not_exist")


def test_watch_follows_a_job_live_and_ends_with_it():
    import time as _t

    from llmdyno import jobs

    def work(ctx):
        for i in range(3):
            ctx.log(f"step {i}")
            ctx.progress((i + 1) / 3, f"step {i}")
            _t.sleep(0.05)
        ctx.result = {"answer": 42}

    jid = jobs.submit("test", "Watch test", work)
    events = list(llmdyno.watch(jid, poll_s=0.2, timeout=20))
    assert [e.data for e in events if e.kind == "log"][:3] == ["step 0", "step 1", "step 2"]
    assert events[-1].kind == "job" and events[-1].status == "done" and events[-1].finished
    assert llmdyno.Job(jid).wait(quiet=True) == {"answer": 42}


def test_watch_polls_work_it_cannot_hear():
    """A job finished before watching (or running in another process) is still reported, by polling."""
    from llmdyno import jobs
    jid = jobs.submit("test", "Already done", lambda ctx: None)
    llmdyno.Job(jid).wait(quiet=True)
    evs = list(llmdyno.watch(jid, poll_s=0.1, timeout=5))
    assert len(evs) == 1 and evs[0].status == "done"


def test_aio_watch_and_calls():
    import asyncio

    from llmdyno import aio, jobs

    async def main():
        jid = jobs.submit("test", "Async watch", lambda ctx: ctx.log("hello"))
        kinds = [ev.kind async for ev in aio.watch(jid, poll_s=0.1, timeout=10)]
        suites = await aio.list_suites()
        return kinds, suites
    kinds, suites = asyncio.run(main())
    assert kinds[-1] == "job" and any(s["id"] == "suite_quick" for s in suites)


def test_integrations_only_use_the_public_library():
    """Integrations are client-side: they reach LLMDyno through the SDK, so they work against a remote one too."""
    import ast
    import pathlib
    folder = pathlib.Path(llmdyno.__file__).parent / "integrations"
    for f in folder.glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level >= 2:
                names = {node.module.split(".")[0]} if node.module else {a.name for a in node.names}
                extra = names - {"sdk", "errors", "__version__", "lib"}
                assert not extra, f"integrations/{f.name} imports {extra}"

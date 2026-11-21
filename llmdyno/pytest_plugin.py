"""pytest plugin, registered automatically when llmdyno is installed: model and agent regression tests in your suite.

    import pytest

    @pytest.mark.llmdyno(models="Qwen 27B 32k", benchmarks="t0_smoke_cli", harnesses="pi", min_score=80)
    def test_smoke_still_passes(llmdyno_results):
        assert llmdyno_results.best()["correctness"] == 100

The marker runs the plan once per distinct set of arguments in a session (tests sharing them share the run). A test
fails when the best final score is under min_score or the best correctness under min_correctness, so a marked test
needs no body at all. Other marker keywords go to llmdyno.bench(). Fixtures: `llmdyno` (the library, on
--llmdyno-data if given) and `llmdyno_results`. Options: --llmdyno-data DIR, --llmdyno-skip (skip marked tests, e.g. on
machines without Docker or a GPU). Nothing here imports more than pytest until a marked test runs."""
from __future__ import annotations

import pytest

_RUNS: dict = {}
_STATE: dict = {}


def pytest_addoption(parser):
    group = parser.getgroup("llmdyno", "LLMDyno model regression tests")
    group.addoption("--llmdyno-data", default=None, metavar="DIR", help="LLMDyno data folder for marked tests")
    group.addoption("--llmdyno-skip", action="store_true", default=False, help="skip tests marked llmdyno")


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "llmdyno(models, benchmarks='suite_quick', harnesses='pi', min_score=None, min_correctness=None, "
                   "**bench_options): run an LLMDyno plan (once per session), check its scores, and give its Results "
                   "to llmdyno_results")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--llmdyno-skip"):
        skip = pytest.mark.skip(reason="--llmdyno-skip")
        for item in items:
            if item.get_closest_marker("llmdyno"):
                item.add_marker(skip)


def _library(config):
    import llmdyno as lib
    data = config.getoption("--llmdyno-data")
    if data and not _STATE.get("ready"):
        lib.init(data)
    _STATE["ready"] = True
    return lib


def _plan(marker) -> tuple:
    kwargs = dict(marker.kwargs)
    if marker.args:
        kwargs.setdefault("models", marker.args[0])
    limits = {k: kwargs.pop(k) for k in ("min_score", "min_correctness") if k in kwargs}
    if "models" not in kwargs:
        raise pytest.UsageError("@pytest.mark.llmdyno needs models=")
    return kwargs, limits


def _results(config, kwargs):
    key = repr(sorted((k, repr(v)) for k, v in kwargs.items()))
    if key not in _RUNS:
        _RUNS[key] = _library(config).bench(quiet=True, **kwargs)
    return _RUNS[key]


@pytest.fixture(scope="session")
def llmdyno(pytestconfig):
    """The llmdyno library, on the data folder given with --llmdyno-data (else the usual one)."""
    return _library(pytestconfig)


@pytest.fixture
def llmdyno_results(request):
    """The Results of the plan described by the test's @pytest.mark.llmdyno(...)."""
    marker = request.node.get_closest_marker("llmdyno")
    if marker is None:
        raise pytest.UsageError("llmdyno_results needs @pytest.mark.llmdyno(models=..., benchmarks=...)")
    return _results(request.config, _plan(marker)[0])


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_call(item):
    """The score limits are part of the test: a regression is a failure, not a setup error."""
    marker = item.get_closest_marker("llmdyno")
    if marker is None:
        return
    kwargs, limits = _plan(marker)
    if not limits:
        return
    best = _results(item.config, kwargs).best() or {}
    who = f"{best.get('profile')} · {best.get('harness')}"
    if "min_score" in limits and (best.get("final") or 0) < limits["min_score"]:
        pytest.fail(f"best final score {best.get('final')} is under {limits['min_score']} ({who})", pytrace=False)
    if "min_correctness" in limits and (best.get("correctness") or 0) < limits["min_correctness"]:
        pytest.fail(f"best correctness {best.get('correctness')} is under {limits['min_correctness']} ({who})",
                    pytrace=False)

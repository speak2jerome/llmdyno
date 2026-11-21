"""Regression checks for CI (compare_results and `llmdyno ci`) and the pytest plugin."""
import json

import pytest

import llmdyno
from llmdyno import cli

pytest_plugins = ["pytester"]


@pytest.fixture(scope="module")
def sample():
    was = llmdyno.sample_status()["loaded"]
    pid = llmdyno.load_sample()
    yield pid
    if not was:
        llmdyno.unload_sample()


@pytest.fixture
def files(sample, tmp_path):
    base = llmdyno.results(sample).to_json(tmp_path / "baseline.json")
    worse = json.loads(json.dumps(base))
    worse["leaderboard"][0]["final"] -= 5                              # GPT-6 Luna drops 5 points
    worse["leaderboard"] = [r for r in worse["leaderboard"] if r["profile"] != "Gemma 4 E2B Q8_0"]
    (tmp_path / "worse.json").write_text(json.dumps(worse))
    return tmp_path / "baseline.json", tmp_path / "worse.json"


def test_compare_results(sample, files):
    base, worse = files
    same = llmdyno.compare_results(llmdyno.results(sample), base)
    assert same["ok"] and not same["regressions"] and all(r["change"] == 0 for r in same["rows"])
    rep = llmdyno.compare_results(worse, base, max_drop=2)
    assert not rep["ok"] and [r["profile"] for r in rep["regressions"]] == ["GPT-6 Luna"]
    assert rep["regressions"][0]["change"] == -5.0 and [r["profile"] for r in rep["missing"]] == ["Gemma 4 E2B Q8_0"]
    assert llmdyno.compare_results(worse, base, max_drop=6, allow_missing=True)["ok"]
    with pytest.raises(llmdyno.InvalidError):
        llmdyno.compare_results(base.with_name("nope.json"), base)


def test_ci_command(files, capsys, sample):
    base, worse = files
    assert cli.main(["ci", "--baseline", str(base), "--plans", sample]) == 0
    out = capsys.readouterr().out
    assert "passed: 0 regression(s)" in out
    assert cli.main(["ci", "--baseline", str(base), "--results", str(worse)]) == 1
    out = capsys.readouterr().out
    assert "REGRESSED  GPT-6 Luna · Pi" in out and "missing    Gemma 4 E2B Q8_0" in out and "FAILED" in out
    assert cli.main(["ci", "--baseline", str(base), "--results", str(worse), "--max-drop", "10", "--allow-missing",
                     "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_pytest_plugin(pytester, sample, request):
    pytester.makeconftest(f"""
import pytest, llmdyno

@pytest.fixture(autouse=True)
def no_real_runs(monkeypatch):
    calls = []
    def fake_bench(models, benchmarks="suite_quick", harnesses="pi", **kw):
        calls.append((models, benchmarks))
        return llmdyno.results("{sample}")
    monkeypatch.setattr(llmdyno, "bench", fake_bench)
    return calls
""")
    pytester.makepyfile("""
import pytest

@pytest.mark.llmdyno(models="GPT-6 Luna", benchmarks="t1_flask_site", min_score=90)
def test_good(llmdyno_results):
    assert llmdyno_results.best()["profile"] == "GPT-6 Luna"

@pytest.mark.llmdyno(models="GPT-6 Luna", benchmarks="t1_flask_site", min_score=99)
def test_too_strict(llmdyno_results):
    pass

def test_unmarked(llmdyno_results):
    pass

def test_library_fixture(llmdyno):
    assert hasattr(llmdyno, "bench")
""")
    args = [] if request.config.pluginmanager.has_plugin("llmdyno") else ["-p", "llmdyno.pytest_plugin"]
    res = pytester.runpytest_inprocess(*args)
    res.assert_outcomes(passed=2, failed=1, errors=1)
    res.stdout.fnmatch_lines(["*best final score 94.3 is under 99*"])
    skipped = pytester.runpytest_inprocess(*args, "--llmdyno-skip")
    skipped.assert_outcomes(passed=1, skipped=2, errors=1)

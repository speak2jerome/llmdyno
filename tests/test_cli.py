"""The command line is generated from the library: every public call has a command, and commands behave like the
calls (same results, --json output, errors as exit codes)."""
import inspect
import json

import pytest

from llmdyno import cli, lib


@pytest.fixture(scope="module")
def registry():
    return cli.build_parser()[1]


def test_every_library_call_has_a_command(registry):
    missing = []
    for name in lib.__all__:
        obj = getattr(lib, name)
        if isinstance(obj, type):
            if name in cli.GROUPS:
                group = cli.GROUPS[name][0]
                if f"{group} show" not in registry:
                    missing.append(f"{group} show")
                for m, _ in inspect.getmembers(obj, inspect.isfunction):
                    if not m.startswith("_") and m not in cli.SKIP_METHODS and f"{group} {cli._dash(m)}" not in registry:
                        missing.append(f"{group} {cli._dash(m)}")
            continue
        if not callable(obj) or name in cli.CUSTOM or name in cli.NOT_COMMANDS or name in cli.GETTERS:
            continue
        if cli._dash(name) not in registry:
            missing.append(cli._dash(name))
    assert not missing, f"library calls without a CLI command: {missing}"


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_listing_and_json(capsys):
    code, out, _ = run(capsys, "list-suites")
    assert code == 0 and "suite_quick" in out
    code, out, _ = run(capsys, "list-benchmarks", "--category", "smoke test", "--json")
    rows = json.loads(out)
    assert code == 0 and rows and all(r["category"] == "Smoke test" for r in rows)
    code, out, _ = run(capsys, "benchmark", "show", "t0_smoke_cli", "--json")
    assert json.loads(out)["id"] == "t0_smoke_cli"
    code, out, _ = run(capsys, "harness", "dockerfile", "pi")
    assert code == 0 and "FROM" in out


def test_results_views_and_export(capsys, tmp_path):
    from llmdyno import lib as L
    was = L.sample_status()["loaded"]
    run(capsys, "load-sample")
    try:
        code, out, _ = run(capsys, "results", "--plans", "plan_sample_round1")
        assert code == 0 and "Profile" in out and "GPT-6 Luna" in out
        code, out, _ = run(capsys, "results", "--plans", "plan_sample_round1", "--view", "cells", "--json")
        assert len(json.loads(out)) == 75
        code, out, _ = run(capsys, "results", "--plans", "plan_sample_round1", "--benchmarks", "t5_bugfix_semver",
                           "--export", str(tmp_path / "r.json"), "--level", "runs", "--fmt", "json", "--json")
        assert code == 0 and json.loads((tmp_path / "r.json").read_text())["level"] == "runs"
        code, out, _ = run(capsys, "settings", "--json")
        assert "weights" in json.loads(out)
    finally:
        if not was:
            run(capsys, "unload-sample")


def test_errors_become_exit_codes(capsys):
    code, _, err = run(capsys, "profile", "show", "there is no such profile")
    assert code == 1 and err.startswith("error: no profile")
    code, _, err = run(capsys, "suite", "delete", "suite_quick")
    assert code == 1 and "built-in" in err


def test_settings_options_and_methods(capsys, recorder):
    recorder.replies.update({
        "models.hub_repo": {"repo": "a/b", "variants": [{"id": "b-Q4_K_M.gguf", "quant": "Q4_K_M", "mmproj": False,
                                                          "size_bytes": 1, "files": []}]},
        "models.hub_estimate": lambda body: {"check": {"verdict": "fits"}, "params": body["params"]},
        "runs.get_run": lambda rid: {"id": rid, "status": "done", "plan_id": "p"},
        "runs.run_transcript": {"events": [
            {"seq": 1, "ev": "request", "new": []},
            {"seq": 1, "ev": "response", "blocks": [{"type": "tool_call", "id": "c", "name": "bash", "args": "{}"}]}]},
        "system.get_job": {"id": "job_w", "status": "done", "title": "Watched"},
    })
    code, out, _ = run(capsys, "estimate", "a/b", "Q4_K_M", "--set", "ctx=32768", "--set", "kv_cache=q8_0", "--json")
    assert code == 0 and json.loads(out)["params"] == {"ctx": 32768, "cache_k": "q8_0", "cache_v": "q8_0"}
    code, out, _ = run(capsys, "run", "transcript", "run_x", "--view", "tool-calls", "--json")
    assert json.loads(out)[0]["name"] == "bash"
    code, out, _ = run(capsys, "watch", "job_w", "--poll-s", "0.1", "--json")
    assert code == 0 and json.loads(out.splitlines()[-1])["data"]["status"] == "done"

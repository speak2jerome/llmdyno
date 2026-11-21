"""Library parity: models, Hugging Face and profile sharing. Hugging Face calls go through a recording backend."""
import json

import pytest
from conftest import write_gguf

import llmdyno


@pytest.fixture(scope="module")
def tiny(tmp_path_factory):
    folder = tmp_path_factory.mktemp("gguf")
    write_gguf(folder / "Tiny-Test-Q8_0.gguf")
    (folder / "notes.txt").write_text("not a model")
    added = llmdyno.import_models(folder)
    assert len(added) == 1 and llmdyno.import_models(folder) == []            # importing again adds nothing
    yield added[0].refresh()
    for p in llmdyno.list_profiles("local"):
        if p.get("model_id") == added[0].id:
            p.delete()
    added[0].delete()


def test_imported_model_and_lookups(tiny):
    assert tiny.status == "ready" and tiny.quant == "Q8_0" and tiny.paths[0].endswith("Tiny-Test-Q8_0.gguf")
    assert tiny in llmdyno.list_models(status="ready")
    assert llmdyno.model("Tiny-Test-Q8_0") == tiny and llmdyno.model(tiny.id) == tiny
    assert isinstance(tiny.contexts(), list)
    with pytest.raises(llmdyno.NotFoundError):
        llmdyno.model("no-such-model")


def test_profiles_from_a_model_defaults_duplicate_export_import(tiny, tmp_path):
    defaults = llmdyno.profile_defaults("local", tiny)
    assert "ctx" in defaults and "cache_k" in defaults
    assert "reasoning_effort" in llmdyno.profile_defaults("cloud")
    p = tiny.profile(ctx=2048, name="Tiny 2k")
    assert p.kind == "local" and p.params["ctx"] == 2048 and p["model_id"] == tiny.id
    p.update(notes="from the SDK test", tags=["sdk"])
    assert p["notes"] == "from the SDK test" and p["tags"] == ["sdk"]
    twin = p.duplicate(name="Tiny 2k twin", ctx=1024)
    assert twin.id != p.id and twin.name == "Tiny 2k twin" and twin.params["ctx"] == 1024
    exported = p.export(tmp_path / "tiny.profile.json")
    assert exported["llmdyno_profile"] == 1 and exported["model"]["quant"] == "Q8_0"
    assert json.loads((tmp_path / "tiny.profile.json").read_text())["name"] == "Tiny 2k"
    twin.delete()
    p.delete()
    back = llmdyno.import_profile(tmp_path / "tiny.profile.json")
    assert back.name == "Tiny 2k" and back.params["ctx"] == 2048
    back.delete()


def test_hugging_face_calls(recorder):
    variants = [{"id": "Qwen-Q4_K_M.gguf", "quant": "Q4_K_M", "mmproj": False, "size_bytes": 5 * 2**30, "files": []},
                {"id": "mmproj-F16.gguf", "quant": "mmproj", "mmproj": True, "size_bytes": 1, "files": []}]
    recorder.replies.update({
        "models.hub_search": [{"repo": "someone/Qwen-GGUF"}],
        "models.hub_repo": {"repo": "someone/Qwen-GGUF", "variants": variants, "gated": False},
        "models.hub_estimate": lambda body: {"check": {"verdict": "fits"}, "params": body["params"]},
        "models.list_models": [],
        "models.model_download": {"model_id": "mdl_new", "job_id": "job_dl"},
        "system.get_job": {"id": "job_dl", "status": "done", "title": "Download", "result": {}},
        "models.model_detail": {"id": "mdl_new", "name": "Qwen-Q4_K_M", "status": "ready", "quant": "Q4_K_M"},
        "models.recommended": {"gpu": None, "items": [{"repo": "unsloth/Qwen3.8-27B-GGUF", "downloaded": False}]},
        "models.model_pause": {"ok": True},
    })
    assert llmdyno.search_models("qwen") == [{"repo": "someone/Qwen-GGUF"}]
    assert llmdyno.repo_info("someone/Qwen-GGUF")["variants"][0]["quant"] == "Q4_K_M"
    est = llmdyno.estimate("someone/Qwen-GGUF", "q4_k_m", ctx=32768, kv_cache="q8_0")
    assert est["check"]["verdict"] == "fits" and est["params"]["cache_k"] == "q8_0"
    with pytest.raises(llmdyno.NotFoundError, match="has no Q6_K"):
        llmdyno.estimate("someone/Qwen-GGUF", "Q6_K")
    m = llmdyno.download_model("someone/Qwen-GGUF", "Q4_K_M", quiet=True)
    assert isinstance(m, llmdyno.Model) and m.status == "ready"
    assert ("models.model_download", {"body": {"repo": "someone/Qwen-GGUF", "variant_id": "Qwen-Q4_K_M.gguf"}}) \
        in recorder.calls
    m.pause()
    assert llmdyno.recommended_models()[0]["repo"] == "unsloth/Qwen3.8-27B-GGUF"

"""Profile validation and harness adapters (config files and commands render for every harness and API style)."""
import json

import pytest

from llmdyno import profiles
from llmdyno.harnesses import catalog


def test_local_defaults_are_valid():
    assert profiles.validate_local(profiles.LOCAL_DEFAULTS) == []


@pytest.mark.parametrize("patch,needle", [
    ({"ctx": 512}, "ctx"),
    ({"gpu_layers": -3}, "gpu_layers"),
    ({"cache_k": "q3"}, "cache_k"),
    ({"extra_args": ["-m", "other.gguf"]}, "cannot override"),
    ({"extra_args": ["--port", "1"]}, "cannot override"),
    ({"sampling": {"temperature": 3}}, "temperature"),
])
def test_local_validation_rejects(patch, needle):
    errs = profiles.validate_local(profiles.merge(profiles.LOCAL_DEFAULTS, patch))
    assert any(needle in e for e in errs), errs


def test_cloud_validation():
    assert profiles.validate_cloud(profiles.CLOUD_DEFAULTS) == []
    assert profiles.validate_cloud({**profiles.CLOUD_DEFAULTS, "ctx": 1000})


@pytest.mark.parametrize("harness", catalog.BUILTIN, ids=lambda h: h.id)
def test_every_harness_renders(harness):
    for style in harness.apis:
        rc = catalog.RunCtx(model="test-model", base_url="http://dyno-proxy-test:8081", api_style=style, ctx=65536,
                            max_tokens=8192, local=True)
        files = harness.files(rc)
        for rel, content in files.items():
            assert not rel.startswith("/"), "config files are written relative to the sandbox HOME"
            if rel.endswith(".json"):
                json.loads(content)
        for stage in (1, 2):
            cmd = harness.command(rc, stage, 2)
            assert "$PROMPT" in cmd, "the stage prompt must come from the PROMPT variable"
        env = harness.env(rc)
        # agents only ever hold a placeholder: the proxy injects the real key
        assert not any("sk-" in str(v) for v in env.values())
        assert harness.dockerfile("llmdyno-sandbox:1").startswith("FROM llmdyno-sandbox:1")


def test_harness_info_is_serialisable():
    for h in catalog.BUILTIN:
        json.dumps(h.info())

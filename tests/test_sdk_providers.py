"""Library parity: providers, vendors, prices and Artificial Analysis references (no network)."""
import pytest

import llmdyno


def test_provider_lifecycle():
    assert any(v["id"] == "anthropic" for v in llmdyno.vendors())
    p = llmdyno.add_provider("custom", name="SDK local", base_url="http://localhost:9/sdk-provider/v1", budget_usd=1.5)
    try:
        assert p in llmdyno.list_providers(vendor="custom") and llmdyno.provider("SDK local") == p
        assert p.budget_usd == 1.5 and not p.has_key
        assert p.set_key("sk-sdk-test").has_key and "sk-sdk-test" not in str(p.to_dict())
        assert not p.remove_key().has_key
        p.update(name="SDK local 2", budget_usd=2.0)
        assert p.name == "SDK local 2" and p.budget_usd == 2.0
        with pytest.raises(llmdyno.InvalidError, match="negative"):
            p.update(budget_usd=-1)
        result = p.test()                                   # nothing listens on port 9: fails fast, offline
        assert result["ok"] is False and result["error"]
        assert p.reset_spend().spent_usd == 0
        prof = llmdyno.cloud_model("custom", "sdk-model", base_url="http://localhost:9/sdk-provider/v1", pricing=None,
                                   name="SDK provider test profile")
        assert prof["provider_id"] == p.id
        with pytest.raises(llmdyno.ConflictError, match="profile"):
            p.delete()
        prof.delete()
    finally:
        p.delete()
    with pytest.raises(llmdyno.NotFoundError):
        p.refresh()


def test_price_lookup(recorder):
    recorder.replies["providers.pricing_lookup"] = lambda vendor, model: {"match": {"input": 3.0, "output": 15.0}
                                                                          if model == "known" else None}
    assert llmdyno.lookup_price("anthropic", "known") == {"input": 3.0, "output": 15.0}
    assert llmdyno.lookup_price("anthropic", "unknown") is None


def test_artificial_analysis_key_matches_and_refresh(recorder):
    recorder.replies["references.aa_refresh"] = lambda body: {"models": 300, "fetched_at": 1.0, "force": body["force"]}
    assert llmdyno.refresh_aa(force=True)["force"] is True


def test_artificial_analysis_local_state():
    assert llmdyno.set_aa_key("aa-test-not-real")["has_key"] is True
    ref = llmdyno.aa_reference()
    assert ref["has_key"] and "matches" in ref and "model_list" in ref
    assert llmdyno.remove_aa_key()["has_key"] is False
    p = llmdyno.cloud_model("custom", "aa-model", base_url="http://localhost:9/v1", pricing=None, name="AA test")
    try:
        assert llmdyno.set_aa_match(p, "claude-sonnet-5-5") == {p.id: "claude-sonnet-5-5"} or \
            llmdyno.set_aa_match(p, "claude-sonnet-5-5")[p.id] == "claude-sonnet-5-5"
        assert p.id not in llmdyno.set_aa_match(p, None)
    finally:
        p.delete()
    with pytest.raises(llmdyno.InvalidError, match="empty"):
        llmdyno.set_aa_key("  ")

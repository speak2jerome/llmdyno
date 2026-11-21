"""Settings and the Hugging Face token."""
from pathlib import Path
from .. import config, secrets
from .. import errors


def get_settings():
    s = config.load_settings()
    s["hf_token_set"] = secrets.has("hf_token")
    s["data_dir"] = str(config.DATA)
    return s


def patch_settings(body: dict):
    allowed = {"models_dir", "runs_dir", "electricity_usd_per_kwh", "theme", "onboarded", "default_vram_margin_mib",
               "cloud_concurrency", "weights", "quality_weights", "llama_port"}
    bad = set(body) - allowed
    if bad:
        raise errors.http(400, f"cannot change {', '.join(sorted(bad))}")
    for k in ("models_dir", "runs_dir"):
        if k in body:
            p = Path(body[k])
            if not p.is_absolute():
                raise errors.http(400, f"{k} must be an absolute path")
            p.mkdir(parents=True, exist_ok=True)
    if "electricity_usd_per_kwh" in body and not 0 <= float(body["electricity_usd_per_kwh"]) <= 5:
        raise errors.http(400, "electricity price must be between 0 and 5 USD/kWh")
    if "cloud_concurrency" in body and not 1 <= int(body["cloud_concurrency"]) <= 16:
        raise errors.http(400, "cloud concurrency must be 1-16")
    return config.save_settings(body)


def set_hf_token(body: dict):
    secrets.set("hf_token", body.get("token", ""))
    return {"hf_token_set": secrets.has("hf_token")}


def del_hf_token():
    secrets.delete("hf_token")
    return {"hf_token_set": False}

"""Artificial Analysis reference numbers and their API key."""
from .. import config, secrets
from ..benchmarks import artificial_analysis as aa
from .. import errors
from ._common import _labels


def aa_reference():
    profs = _labels()[0]
    ref = aa.reference(profs)
    return {**aa.status(), "matches": {pid: {"score": m["score"], "manual": m["manual"], "model": m["model"]}
                                       for pid, m in ref.items()},
            "model_list": [{k: m.get(k) for k in ("slug", "name", "creator")} for m in aa.load_cache().get("models") or []]}


def aa_refresh(body: dict | None = None):
    body = {} if body is None else body
    try:
        c = aa.refresh(force=bool(body.get("force")))
    except PermissionError as e:
        raise errors.http(400, str(e)) from e
    except RuntimeError as e:
        raise errors.http(429, str(e)) from e
    except Exception as e:  # noqa: BLE001 - network and API errors go back to the user as text
        raise errors.http(502, f"Artificial Analysis request failed: {e}") from e
    return {"models": len(c.get("models") or []), "fetched_at": c.get("fetched_at")}


def set_aa_key(body: dict):
    key = (body.get("key") or "").strip()
    if not key:
        raise errors.http(400, "the key is empty")
    secrets.set(aa.SECRET, key)
    return aa.status()


def delete_aa_key():
    secrets.delete(aa.SECRET)
    return aa.status()


def aa_override(body: dict):
    pid = body.get("profile_id")
    if not pid:
        raise errors.http(400, "profile_id is required")
    ov = dict(aa.overrides())
    if body.get("slug"):
        ov[pid] = str(body["slug"])[:120]
    else:
        ov.pop(pid, None)
    cur = config.get("aa_reference") or {}
    config.save_settings({"aa_reference": {**cur, "overrides": ov}})
    return {"overrides": ov}

"""Cloud providers: vendors, keys, budgets, connection tests and price lookup."""
import time
from .. import db, secrets
from ..providers import registry as providers
from .. import errors
from ._common import _get


def list_vendors():
    return providers.VENDORS


def _provider_out(p):
    d = dict(p)
    d["has_key"] = secrets.has(providers.secret_name(p["id"]))
    d["key_hint"] = secrets.masked(providers.secret_name(p["id"]))
    from .. import llm
    d["spent_usd"] = round(llm.ledger_spent(p["id"]), 6)
    return d


def list_providers():
    with db.Session() as s:
        return [_provider_out(db.row(p)) for p in s.query(db.Provider).order_by(db.Provider.created_at).all()]


def create_provider(body: dict):
    vendor = providers.BY_ID.get(body.get("vendor"))
    if not vendor:
        raise errors.http(400, "unknown vendor")
    style = body.get("api_style") or vendor["api_style"]
    if style not in vendor["styles"]:
        raise errors.http(400, f"{vendor['name']} supports {', '.join(vendor['styles'])}")
    base = (body.get("base_url") or vendor["styles"].get(style) or vendor["base_url"]).strip()
    if not base.startswith(("http://", "https://")):
        raise errors.http(400, "base URL must start with http:// or https://")
    budget = float(body.get("budget_usd", 5))
    if budget < 0:
        raise errors.http(400, "budget cannot be negative")
    pid = db.new_id("prov")
    with db.Session() as s:
        s.add(db.Provider(id=pid, vendor=vendor["id"], name=(body.get("name") or vendor["name"]).strip(), base_url=base,
                          api_style=style, budget_usd=budget))
        s.commit()
    if body.get("api_key"):
        secrets.set(providers.secret_name(pid), body["api_key"])
    return _provider_out(_get(db.Provider, pid))


def patch_provider(pid: str, body: dict):
    p = _get(db.Provider, pid)
    vendor = providers.BY_ID.get(p["vendor"], providers.BY_ID["custom"])
    with db.Session() as s:
        obj = s.get(db.Provider, pid)
        if "name" in body:
            obj.name = body["name"].strip() or obj.name
        if "budget_usd" in body:
            if float(body["budget_usd"]) < 0:
                raise errors.http(400, "budget cannot be negative")
            obj.budget_usd = float(body["budget_usd"])
        if "api_style" in body:
            if body["api_style"] not in vendor["styles"]:
                raise errors.http(400, f"{vendor['name']} supports {', '.join(vendor['styles'])}")
            obj.api_style = body["api_style"]
            if p["vendor"] != "custom":
                obj.base_url = vendor["styles"][body["api_style"]] or obj.base_url
        if "base_url" in body:
            if not body["base_url"].startswith(("http://", "https://")):
                raise errors.http(400, "base URL must start with http:// or https://")
            obj.base_url = body["base_url"].strip()
        s.commit()
    return _provider_out(_get(db.Provider, pid))


def set_provider_key(pid: str, body: dict):
    _get(db.Provider, pid)
    secrets.set(providers.secret_name(pid), body.get("api_key", ""))
    return _provider_out(_get(db.Provider, pid))


def del_provider_key(pid: str):
    secrets.delete(providers.secret_name(pid))
    return _provider_out(_get(db.Provider, pid))


def test_provider(pid: str):
    p = _get(db.Provider, pid)
    key = secrets.get(providers.secret_name(pid))
    if not key and p["vendor"] != "custom":
        raise errors.http(400, "add an API key first")
    try:
        res = providers.list_models(p["base_url"], p["api_style"], key)
        ok, err = True, None
    except (PermissionError, ConnectionError) as e:
        res, ok, err = {"models": [], "latency_ms": None}, False, str(e)
    with db.Session() as s:
        obj = s.get(db.Provider, pid)
        obj.last_check = {"ok": ok, "error": err, "at": time.time(), "latency_ms": res["latency_ms"], "n_models": len(res["models"])}
        if ok:
            obj.models_cache = res["models"]
        s.commit()
    return {"ok": ok, "error": err, "models": res["models"], "latency_ms": res["latency_ms"]}


def reset_spend(pid: str):
    from .. import llm
    _get(db.Provider, pid)
    llm.ledger_reset(f"provider_{pid}")
    return _provider_out(_get(db.Provider, pid))


def delete_provider(pid: str):
    with db.Session() as s:
        n = s.query(db.Profile).filter(db.Profile.provider_id == pid).count()
        if n:
            raise errors.http(409, f"{n} profile(s) use this provider; delete them first")
        s.query(db.Provider).filter(db.Provider.id == pid).delete()
        s.commit()
    secrets.delete(providers.secret_name(pid))
    return {"ok": True}


def pricing_lookup(vendor: str, model: str):
    hit = providers.lookup_price(vendor, model)
    return {"match": hit}

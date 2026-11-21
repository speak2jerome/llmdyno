"""Which library call gives access to each web API route, so the Python library can do everything the web app does.

SDK functions declare the routes they cover with @covers("METHOD /path"). Routes not covered yet are listed in
PENDING_ROUTES in the SDK module of their area. tests/test_parity.py fails when a route is neither covered nor pending,
when a pending route is already covered, or when @covers names a route that does not exist. Release 0.4.0 needs every
PENDING_ROUTES list empty."""
from __future__ import annotations

import importlib
import pkgutil

# Not part of LLMDyno's API: FastAPI's generated docs and the single-page app's catch-all route.
NOT_API = {"GET /openapi.json", "GET /docs", "GET /docs/oauth2-redirect", "GET /redoc", "GET /{full_path:path}"}

# Part of the API, with no separate library call by design.
EXEMPT = {
    "GET /api/health": "the library uses it to see whether the dashboard is up (serve(), open()); nothing to call",
}


def _modules():
    from .. import sdk
    for m in pkgutil.iter_modules(sdk.__path__):
        if m.name not in ("parity",):
            yield importlib.import_module(f"llmdyno.sdk.{m.name}")


def app_routes() -> set[str]:
    """Every route the web server answers, as "METHOD /path" ("WS /ws" for the WebSocket)."""
    from ..server import app
    out = set()
    for r in app.routes:
        methods = getattr(r, "methods", None)
        if methods is None:
            out.add(f"WS {r.path}")
            continue
        out |= {f"{m} {r.path}" for m in methods if m != "HEAD"}
    return out


def coverage() -> dict[str, list[str]]:
    """Route -> the SDK callables that cover it."""
    from . import _core
    for _ in _modules():                     # importing every area module runs its @covers decorators
        pass
    return {k: list(v) for k, v in _core.ROUTES.items()}


def pending() -> dict[str, str]:
    """Route -> the SDK module that still has to cover it."""
    out = {}
    for mod in _modules():
        for route in getattr(mod, "PENDING_ROUTES", ()):
            out[route] = mod.__name__
    return out


def report() -> dict:
    """{"covered": {...}, "pending": {...}, "missing": [...], "exempt": {...}} for the whole API."""
    routes = app_routes() - NOT_API
    cov, pend = coverage(), pending()
    return {"covered": {r: cov[r] for r in sorted(routes) if r in cov},
            "pending": {r: pend[r] for r in sorted(routes) if r in pend and r not in cov},
            "missing": sorted(routes - set(cov) - set(pend) - set(EXEMPT)),
            "exempt": dict(EXEMPT)}

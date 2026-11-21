"""The Python library can do everything the web app does: every API route has a library call, or is pending in the
SDK module of its area (and 0.4.0 empties those lists). See llmdyno/sdk/parity.py."""
import pytest

import llmdyno
from llmdyno import lib
from llmdyno.sdk import parity


@pytest.fixture(scope="module")
def report():
    return parity.report()


def test_every_route_is_covered_or_pending(report):
    assert not report["missing"], ("web API routes with no library call; add one (with @covers) or, for now, list "
                                   f"them in the area's PENDING_ROUTES: {report['missing']}")


def test_covers_only_names_real_routes():
    unknown = sorted(set(parity.coverage()) - parity.app_routes())
    assert not unknown, f"@covers names routes the server does not have: {unknown}"


def test_pending_lists_are_up_to_date():
    done = sorted(set(parity.pending()) & set(parity.coverage()))
    assert not done, f"covered now, so remove from PENDING_ROUTES: {done}"
    gone = sorted(set(parity.pending()) - parity.app_routes())
    assert not gone, f"PENDING_ROUTES lists routes the server does not have: {gone}"
    assert not set(parity.EXEMPT) & set(parity.pending())


def test_coverage_comes_from_public_api(report):
    """A route only counts as covered by something a user can call: a public function or a public class's method."""
    public = set(lib.__all__)
    for route, names in report["covered"].items():
        ok = False
        for name in names:
            parts = name.removeprefix("llmdyno.sdk.").split(".", 1)[1].split(".")
            if parts[0] in public and not any(p.startswith("_") for p in parts[1:]):
                ok = True
        assert ok, f"{route} is only covered by non-public code: {names}"


def test_full_parity(report):
    """Since 0.4.0 nothing is pending: a new route needs its library call in the same change."""
    total = len(report["covered"]) + len(report["pending"]) + len(report["exempt"])
    assert total == len(parity.app_routes() - parity.NOT_API)
    assert not report["pending"], f"routes without a library call: {sorted(report['pending'])}"


def test_watch_and_aio_are_public():
    assert callable(llmdyno.watch) and llmdyno.Event
    from llmdyno import aio
    assert aio is llmdyno.aio
    import asyncio
    assert asyncio.iscoroutinefunction(aio.list_suites) and asyncio.iscoroutinefunction(aio.call)

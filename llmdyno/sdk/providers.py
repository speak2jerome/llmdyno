"""Cloud providers: vendors, keys, budgets and spend, connection tests and price lookup."""
from __future__ import annotations

__all__: list[str] = []

# Web API routes this module does not cover yet (see sdk/parity.py); remove each one as it gets a library call.
PENDING_ROUTES = (
    "GET /api/pricing/lookup",
    "GET /api/providers",
    "POST /api/providers",
    "DELETE /api/providers/{pid}",
    "PATCH /api/providers/{pid}",
    "DELETE /api/providers/{pid}/key",
    "PUT /api/providers/{pid}/key",
    "POST /api/providers/{pid}/reset-spend",
    "POST /api/providers/{pid}/test",
    "GET /api/vendors",
)

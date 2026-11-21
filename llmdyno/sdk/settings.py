"""Settings and tokens (Hugging Face)."""
from __future__ import annotations

__all__: list[str] = []

# Web API routes this module does not cover yet (see sdk/parity.py); remove each one as it gets a library call.
PENDING_ROUTES = (
    "GET /api/settings",
    "PATCH /api/settings",
    "DELETE /api/settings/hf-token",
    "PUT /api/settings/hf-token",
)

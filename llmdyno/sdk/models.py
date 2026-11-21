"""GGUF models: Hugging Face search, fit estimates before download, downloads, imports and the recommended list."""
from __future__ import annotations

__all__: list[str] = []

# Web API routes this module does not cover yet (see sdk/parity.py); remove each one as it gets a library call.
PENDING_ROUTES = (
    "POST /api/hub/estimate",
    "GET /api/hub/repo",
    "GET /api/hub/search",
    "GET /api/models",
    "POST /api/models/download",
    "POST /api/models/import",
    "GET /api/models/recommended/list",
    "DELETE /api/models/{mid}",
    "GET /api/models/{mid}",
    "POST /api/models/{mid}/pause",
    "POST /api/models/{mid}/resume",
)

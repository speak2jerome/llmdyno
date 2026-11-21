"""Agent harnesses: built-in and custom, images, Dockerfiles, previews and portable runtimes."""
from __future__ import annotations

__all__: list[str] = []

# Web API routes this module does not cover yet (see sdk/parity.py); remove each one as it gets a library call.
PENDING_ROUTES = (
    "GET /api/harnesses",
    "GET /api/harnesses-schema",
    "POST /api/harnesses/custom",
    "DELETE /api/harnesses/custom/{hid}",
    "PUT /api/harnesses/custom/{hid}",
    "POST /api/harnesses/{hid}/build",
    "GET /api/harnesses/{hid}/dockerfile",
    "DELETE /api/harnesses/{hid}/image",
    "GET /api/harnesses/{hid}/preview",
    "GET /api/harnesses/{hid}/runtime",
    "POST /api/harnesses/{hid}/runtime",
)

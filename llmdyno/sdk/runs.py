"""Runs: details, transcripts, workspace files, logs, GPU telemetry, cancel, retry and re-grade."""
from __future__ import annotations

__all__: list[str] = []

# Web API routes this module does not cover yet (see sdk/parity.py); remove each one as it gets a library call.
PENDING_ROUTES = (
    "GET /api/runs/{rid}",
    "POST /api/runs/{rid}/cancel",
    "GET /api/runs/{rid}/download",
    "GET /api/runs/{rid}/file",
    "GET /api/runs/{rid}/files",
    "GET /api/runs/{rid}/gpu",
    "GET /api/runs/{rid}/log",
    "GET /api/runs/{rid}/proxy",
    "POST /api/runs/{rid}/regrade",
    "POST /api/runs/{rid}/retry",
    "GET /api/runs/{rid}/transcript",
)

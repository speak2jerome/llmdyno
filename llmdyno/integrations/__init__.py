"""Integrations with mainstream libraries: data frames, notebooks, charts, experiment tracking and tracing, model
gateways and hubs, agent frameworks, Inspect AI and pytest.

Each integration is an optional extra (pip install "llmdyno[mlflow]", "llmdyno[plot]", … or "llmdyno[all]") and lives in
its own module here. Nothing is imported until you use it, and a missing package raises LLMDynoError naming the extra
to install, so the core install stays small."""
from __future__ import annotations

import importlib

from ..errors import LLMDynoError

__all__ = ["require"]


def require(module: str, extra: str, what: str | None = None):
    """Import an optional dependency, or explain which extra provides it."""
    try:
        return importlib.import_module(module)
    except ImportError as e:
        raise LLMDynoError(f"{what or module} needs the {extra!r} extra: pip install \"llmdyno[{extra}]\"") from e

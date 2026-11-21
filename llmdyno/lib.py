"""LLMDyno as a Python library.

    import llmdyno

    gpt = llmdyno.cloud_model("openai", "gpt-6-luna", reasoning_effort="low", budget_usd=2)
    qwen = llmdyno.local_model("unsloth/Qwen3.8-27B-GGUF", quant="UD-Q3_K_XL", ctx=49152)
    results = llmdyno.bench([gpt, qwen], benchmarks="suite_quick", harnesses="pi")
    print(results)

Everything goes through the same engine, data folder and database as the web app, so a plan started from Python shows
up in the dashboard (`llmdyno.serve()` or `results.open()`), and profiles made in the UI can be used from Python.
Long operations (downloads, image builds, plans) block and print progress by default; Ctrl+C cancels them cleanly.

The code lives in llmdyno/sdk, one module per area; this module gathers the public names, and `import llmdyno`
exports them lazily. Every name in __all__ here is available as llmdyno.<name>.
"""
from __future__ import annotations

from .errors import (
    ConflictError, ForbiddenError, InsufficientStorageError, InvalidError, LLMDynoError, NotFoundError, PreflightError,
    RateLimitError, RiskNotAcknowledgedError, UpstreamError,
)
from .sdk import agents as _agents
from .sdk import benchmarks as _benchmarks
from .sdk import harnesses as _harnesses
from .sdk import interop as _interop
from .sdk import judging as _judging
from .sdk import live as _live
from .sdk import models as _models
from .sdk import plans as _plans
from .sdk import profiles as _profiles
from .sdk import providers as _providers
from .sdk import references as _references
from .sdk import remote as _remote
from .sdk import results as _results
from .sdk import runs as _runs
from .sdk import settings as _settings
from .sdk import system as _system
from .sdk import ui as _ui
from .sdk._core import Job, data_dir, init, job
from .sdk.agents import *  # noqa: F401,F403
from .sdk.benchmarks import *  # noqa: F401,F403
from .sdk.harnesses import *  # noqa: F401,F403
from .sdk.interop import *  # noqa: F401,F403
from .sdk.judging import *  # noqa: F401,F403
from .sdk.live import *  # noqa: F401,F403
from .sdk.models import *  # noqa: F401,F403
from .sdk.plans import *  # noqa: F401,F403
from .sdk.profiles import *  # noqa: F401,F403
from .sdk.profiles import _params  # noqa: F401 - kept for code written against 0.3
from .sdk.providers import *  # noqa: F401,F403
from .sdk.references import *  # noqa: F401,F403
from .sdk.remote import *  # noqa: F401,F403
from .sdk.results import *  # noqa: F401,F403
from .sdk.runs import *  # noqa: F401,F403
from .sdk.settings import *  # noqa: F401,F403
from .sdk.system import *  # noqa: F401,F403
from .sdk.ui import *  # noqa: F401,F403

_AREAS = (_system, _profiles, _models, _providers, _harnesses, _agents, _benchmarks, _plans, _runs, _results, _judging,
          _references, _settings, _live, _interop, _remote, _ui)

__all__ = ["LLMDynoError", "InvalidError", "ForbiddenError", "NotFoundError", "ConflictError", "RiskNotAcknowledgedError",
           "RateLimitError", "UpstreamError", "InsufficientStorageError", "PreflightError", "Job", "job", "init",
           "data_dir"]
__all__ += [name for area in _AREAS for name in area.__all__]

"""LLMDyno: benchmark local (llama.cpp) and cloud LLMs as coding agents.

Use it as a library:

    import llmdyno

    gpt = llmdyno.cloud_model("openai", "gpt-6-luna", reasoning_effort="low")
    qwen = llmdyno.local_model("unsloth/Qwen3.8-27B-GGUF", quant="UD-Q3_K_XL", ctx=49152)
    results = llmdyno.bench([gpt, qwen], benchmarks="suite_quick", harnesses="pi")
    print(results)

or as an app: `llmdyno serve --open` (or llmdyno.serve()). Both use the same data folder. See docs/LIBRARY.md.

The version follows Semantic Versioning. While it is 0.x, a minor release (0.2.0) may change the API, the data
folder layout or the database schema (with an automatic migration); patch releases (0.1.1) only fix things.
"""
from typing import TYPE_CHECKING

__version__ = "0.3.0"

# The public API lives in llmdyno.lib and is loaded on first use, so `import llmdyno` stays instant and starts
# nothing (no database, no Docker, no web server) until you call something. Public names must never equal a
# submodule's name (profiles, benchmarks, judge, …): Python would set the module over the function, or the reverse.
_PUBLIC = (
    "LLMDynoError", "NotFoundError", "ConflictError", "PreflightError", "Profile", "Plan", "Results", "Doctor",
    "init", "data_dir", "doctor", "setup", "cloud_model", "local_model", "list_profiles", "profile", "list_benchmarks",
    "list_suites", "import_swebench", "import_polyglot", "preflight", "bench", "list_plans", "plan", "results", "review",
    "serve",
)
__all__ = ["__version__", *_PUBLIC]

if TYPE_CHECKING:  # pragma: no cover - for IDEs and type checkers
    from .lib import (  # noqa: F401
        ConflictError, Doctor, LLMDynoError, NotFoundError, Plan, PreflightError, Profile, Results, bench, cloud_model,
        data_dir, doctor, import_polyglot, import_swebench, init, list_benchmarks, list_plans, list_profiles, list_suites,
        local_model, plan, preflight, profile, results, review, serve, setup,
    )


def __getattr__(name):
    if name in _PUBLIC:
        from . import lib
        value = getattr(lib, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'llmdyno' has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | set(_PUBLIC))

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

__version__ = "0.3.1"

# The public API is gathered in llmdyno.lib (code in llmdyno/sdk) and loaded on first use, so `import llmdyno` stays
# instant and starts nothing (no database, no Docker, no web server) until you call something. Public names must
# never equal a submodule's name (jobs, profiles, benchmarks, judge, …): Python would set the module over the
# function, or the reverse. tests/test_library.py checks this.

if TYPE_CHECKING:  # pragma: no cover - for IDEs and type checkers
    from .lib import *  # noqa: F401,F403


def _lib():
    import importlib
    return importlib.import_module("llmdyno.lib")


def _public() -> list:
    return _lib().__all__


def _is_submodule(name: str) -> bool:
    import os
    base = os.path.join(os.path.dirname(__file__), name)
    return os.path.isdir(base) or os.path.isfile(base + ".py")


def __getattr__(name):
    if name == "__all__":                                    # for `from llmdyno import *` and the tests
        return ["__version__", *_public()]
    if name in ("aio", "errors"):                            # public submodules: llmdyno.aio without importing it
        import importlib
        return importlib.import_module(f"llmdyno.{name}")
    if not name.startswith("_") and not _is_submodule(name):   # `from llmdyno import db` must not load the API
        lib = _lib()
        if name in lib.__all__:
            value = getattr(lib, name)
            globals()[name] = value
            return value
    raise AttributeError(f"module 'llmdyno' has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | set(_public()))

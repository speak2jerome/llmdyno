# Contributing to LLMDyno

Thanks for helping. Bug reports, benchmarks, harness adapters, provider presets and docs fixes are all welcome.

## Development setup

```bash
git clone https://github.com/speak2jerome/llmdyno.git
cd llmdyno
python -m venv .venv
.venv/bin/pip install -e ".[dev]"            # Windows: .venv\Scripts\pip install -e ".[dev]"
cd frontend && npm ci && cd ..
```

`[dev]` installs pytest and ruff. For the integration tests, type checking, notebooks and the docs site, install
what CI's extras job installs: `pip install -e ".[dev,all,typing,notebooks,docs]"`. Without them those tests are
skipped, not failed. You need Node 22 or later for the frontend and the JavaScript client.

Run the backend and the UI dev server side by side:

```bash
.venv/bin/llmdyno serve                     # API on http://127.0.0.1:8777
cd frontend && npm run dev                  # UI with hot reload on http://127.0.0.1:5177 (proxies /api and /ws)
```

A checkout keeps its data in `./data`. Set `LLMDYNO_DATA` to a scratch folder when you try things that write data.

The built UI in `llmdyno/web/static/` is committed so users don't need Node. If you change anything in `frontend/`,
run `npm run build` and commit the result, including new files: the build writes new, content-hashed file names
(`git add -A llmdyno/web/static`).

## Before you open a pull request

```bash
.venv/bin/ruff check llmdyno tests scripts
.venv/bin/pytest
cd frontend && npm run build && cd ..          # type-checks, then builds
```

If you changed the web API, the library or the CLI, also regenerate the files made from them; tests fail when they are
out of date:

```bash
python scripts/gen_js_client.py                # js/src/generated.ts, the JavaScript client's operations
python scripts/gen_reference_docs.py           # docs/reference/cli.md and docs/reference/web-api.md
```

And when you touch these areas:

| You changed | Also run |
|---|---|
| `js/` | `cd js && npm ci && npm run typecheck && npm run build && npm test` |
| the library's types | `pyright` (strict for `llmdyno/sdk` and `llmdyno/errors.py`, standard elsewhere) |
| `examples/notebooks/` | `pytest --nbmake examples/notebooks -p no:llmdyno` |
| `docs/` or `mkdocs.yml` | `mkdocs build --strict` (or `mkdocs serve` to preview) |
| packaging | `python -m build && twine check dist/*` |

The tests need no GPU, Docker or network. CI runs lint and tests on Linux, Windows and macOS, on x86-64 and ARM64,
with Python 3.11 to 3.13; a second job adds every extra, pyright, the notebooks, the docs build and packaging checks;
and two more test the JavaScript client (on Node 22 and 24, against a live server) and build the frontend.
[docs/RELEASING.md](docs/RELEASING.md#what-ci-checks) has the details.

## Rules the tests enforce

- **Every web API route has a library call.** Mark the SDK function or method with `@covers("METHOD /api/path")`
  (`tests/test_parity.py`).
- **Every library call has a command.** The CLI is generated from the library (`tests/test_cli.py`); give new
  functions a docstring, because its first sentence becomes the command's help.
- **The JavaScript client knows every operation** (`tests/test_js_client.py`), and **the generated reference pages
  are current** (`tests/test_docs_site.py`).
- **Every docs page is in the navigation, with a description and an `llms.txt` link** (`tests/test_docs_site.py`
  and `mkdocs build --strict`).
- **README links are absolute**, because the README is also the PyPI page (`tests/test_versioning.py`).
- **The versions agree** across the Python package, the frontend, the JS client, `CITATION.cff` and `codemeta.json`.

## What goes where

| Area | Path | Guide |
|---|---|---|
| Harness adapters | `llmdyno/harnesses/catalog.py` (add to `BUILTIN`), plus the README table and `NOTICE.md` | [docs/HARNESSES.md](docs/HARNESSES.md) |
| Built-in benchmarks | `llmdyno/benchmarks/builtin/`, suites in `llmdyno/benchmarks/registry.py` | [docs/BENCHMARKS.md](docs/BENCHMARKS.md) |
| Cloud provider presets | `llmdyno/providers/registry.py` (`VENDORS`), the key variable in `ENV_KEYS` in `llmdyno/sdk/profiles.py`, and the vendor list in the `cloud_model()` docstring | |
| Memory projection | `llmdyno/memory.py` | re-run `scripts/calibrate_memory.py` on real GGUFs |
| Library calls | `llmdyno/services/<area>.py` (the logic) and `llmdyno/sdk/<area>.py` (the library) | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| JavaScript client | `js/src/` (`generated.ts` is generated) | [docs/JAVASCRIPT.md](docs/JAVASCRIPT.md) |
| Documentation | `docs/`, `mkdocs.yml` (navigation and page descriptions), `docs/llms.txt` | |
| Mascot sprites | `scripts/make_logo.py` | edit the layers, run the script, then rebuild the frontend |

## Style

- Python: ruff with a 120-character line limit. Comments explain why, not what.
- TypeScript: strict mode, functional React components, the shared kit in `frontend/src/ui.tsx`. The JavaScript
  client runs its `.ts` files directly on Node, so it uses only erasable syntax (no enums or parameter properties).
- UI and docs text: plain, specific, and honest about trade-offs. Say what a button does and what it costs.

## Versioning

LLMDyno follows Semantic Versioning (0.x for now). Add a line under `## [Unreleased]` in `CHANGELOG.md` for any
user-visible change. Maintainers cut releases with `scripts/bump_version.py`; see [docs/RELEASING.md](docs/RELEASING.md).
If you change the database schema, bump `SCHEMA_VERSION` in `llmdyno/db.py` and add a migration.

## Code of conduct

Be kind and assume good faith. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

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

Run the backend and the UI dev server side by side:

```bash
.venv/bin/llmdyno serve                     # API on http://127.0.0.1:8777
cd frontend && npm run dev                  # UI with hot reload on http://127.0.0.1:5177
```

The built UI in `llmdyno/web/static/` is committed so users don't need Node. If you change anything in `frontend/`,
run `npm run build` and commit the result.

## Before you open a pull request

```bash
.venv/bin/ruff check llmdyno tests scripts
.venv/bin/pytest
cd frontend && npx tsc --noEmit && npm run build
```

The tests need no GPU, Docker or network. CI runs the same checks on Windows and Linux.

## What goes where

| Area | Path | Guide |
|---|---|---|
| Harness adapters | `llmdyno/harnesses/catalog.py` | [docs/HARNESSES.md](docs/HARNESSES.md) |
| Built-in benchmarks | `llmdyno/benchmarks/builtin/` | [docs/BENCHMARKS.md](docs/BENCHMARKS.md) |
| Cloud provider presets | `llmdyno/providers/registry.py` | add an entry to `VENDORS` |
| Memory projection | `llmdyno/memory.py` | re-run `scripts/calibrate_memory.py` on real GGUFs |
| Mascot sprites | `scripts/make_logo.py` | edit the layers, then run the script |

## Style

- Python: ruff with a 120-character line limit. Comments explain why, not what.
- TypeScript: strict mode, functional React components, the shared kit in `frontend/src/ui.tsx`.
- UI text: plain, specific, and honest about trade-offs. Say what a button does and what it costs.

## Versioning

LLMDyno follows Semantic Versioning (0.x for now). Add a line under `## [Unreleased]` in `CHANGELOG.md` for any
user-visible change. Maintainers cut releases with `scripts/bump_version.py`; see [docs/RELEASING.md](docs/RELEASING.md).
If you change the database schema, bump `SCHEMA_VERSION` in `llmdyno/db.py` and add a migration.

## Code of conduct

Be kind and assume good faith. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

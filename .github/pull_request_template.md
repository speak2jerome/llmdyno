## What and why

<!-- What does this change, and what problem does it solve? -->

## How it was tested

<!-- Commands you ran, runs you watched, screenshots for UI changes. -->

## Checklist

- [ ] `ruff check llmdyno tests scripts` and `pytest` pass
- [ ] UI changes: `npm run build` in `frontend/`, and the built files are committed, new ones included
- [ ] Web API, library or CLI changes: `python scripts/gen_js_client.py` and `python scripts/gen_reference_docs.py`
- [ ] JavaScript client changes: `npm run typecheck && npm test` in `js/`
- [ ] Docs changes: `mkdocs build --strict`; a new page is in the nav, with a description and an `llms.txt` link
- [ ] User-visible change: a line under `## [Unreleased]` in `CHANGELOG.md`, and the docs updated
- [ ] Database schema change: `SCHEMA_VERSION` bumped and a migration added

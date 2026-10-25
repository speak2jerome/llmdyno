# Releasing

LLMDyno uses [Semantic Versioning](https://semver.org). While the major version is 0:

- **0.MINOR.0** may change the HTTP API, the data folder layout or the database schema. Schema changes ship with a
  migration in `llmdyno/db.py` (`SCHEMA_VERSION` + `MIGRATIONS`).
- **0.x.PATCH** only fixes bugs.

The version is written down in one place, `llmdyno/__init__.py`. `pyproject.toml` reads it; the UI gets it at build
time from `frontend/package.json`, which the bump script keeps in step. CI fails if they disagree.

## Steps

1. Make sure `main` is green and `CHANGELOG.md` lists everything under `## [Unreleased]`.
2. Bump:

   ```bash
   python scripts/bump_version.py minor        # or patch, or an explicit version such as 0.3.0-rc.1
   ```

   This updates `llmdyno/__init__.py`, `frontend/package.json` and `package-lock.json`, and turns the Unreleased
   section of the changelog into the new release.
3. Rebuild the UI so the committed bundle carries the new version:

   ```bash
   cd frontend && npm run build && cd ..
   ```

4. Commit and tag:

   ```bash
   git commit -am "Release v0.2.0"
   git tag -a v0.2.0 -m "LLMDyno 0.2.0"
   git push && git push --tags
   ```

5. The **Release** workflow checks that the tag matches `__version__`, runs the tests, builds the wheel and source
   archive, and publishes a GitHub release with the changelog section as its notes.

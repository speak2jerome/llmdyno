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

   This updates `llmdyno/__init__.py`, `frontend/package.json`, `package-lock.json`, the JavaScript client's
   `js/package.json`, `js/package-lock.json` and `js/src/version.ts`, `CITATION.cff` and the bug-report template, and
   turns the Unreleased section of the changelog into the new release.
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

## Publishing to PyPI

The Release workflow also uploads the wheel and source archive to PyPI, so `pip install llmdyno` works, once two
things are set up (both one-time, no token is stored):

1. On pypi.org, add a trusted publisher (a "pending publisher" before the first upload): owner `speak2jerome`,
   repository `llmdyno`, workflow `release.yml`, environment `pypi`.
2. In the GitHub repository settings, add the variable `PUBLISH_PYPI` with the value `true`.

Until then the PyPI job is skipped and releases go to GitHub only.

## Publishing to npm

The JavaScript client in `js/` (`npm install llmdyno`, `npx llmdyno`) has the same version as the Python package,
and the Release workflow publishes it to npm with provenance from the same tag. Setup, once:

1. Create an account on npmjs.com, with two-factor authentication.
2. Publish the first version by hand, because npm links a workflow only to a package that exists:

   ```bash
   cd js && npm ci && npm run build && npm login && npm publish --access public
   ```

3. On npmjs.com, go to llmdyno, then Settings, then Trusted publishing. Add GitHub Actions with owner
   `speak2jerome`, repository `llmdyno`, workflow `release.yml` and environment `npm`.
4. In the GitHub repository settings, add the variable `PUBLISH_NPM` with the value `true`.

After that, every tag publishes to npm as well, and no token is stored. A pre-release version (`0.6.0-rc.1`) goes
out under the `next` tag, so `npm install llmdyno` keeps getting the latest release.

## Documentation site

`.github/workflows/docs.yml` builds the site with MkDocs (`mkdocs build --strict`) on every push to `main` that touches
the docs or the library, and publishes it to GitHub Pages. One-time setup: in the repository's Settings → Pages, set
"Source" to "GitHub Actions". To preview locally: `pip install -e ".[docs]"` then `mkdocs serve`.

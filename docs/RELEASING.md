# Releasing

LLMDyno uses [Semantic Versioning](https://semver.org). While the major version is 0:

- **0.MINOR.0** may change the public API, the HTTP API, the data folder layout or the database schema. Schema changes
  ship with a migration in `llmdyno/db.py` (`SCHEMA_VERSION` + `MIGRATIONS`).
- **0.x.PATCH** never changes the API, the data folder or the schema. It fixes bugs, and may also update packaging,
  documentation and metadata.

One tag publishes everywhere: a GitHub release, the Python package on PyPI and the JavaScript package on npm, all with
the same version.

## Where the version is written

`llmdyno/__init__.py` holds the version, and `pyproject.toml` reads it from there. `scripts/bump_version.py` writes it
into everything else, and tests fail if any of them disagree:

- `frontend/package.json` and `frontend/package-lock.json` (the UI shows the version, so the bundle is rebuilt);
- `js/package.json`, `js/package-lock.json` and `js/src/version.ts` (the npm package);
- `CITATION.cff` (version and release date) and `codemeta.json` (version and `dateModified`);
- the version placeholder in `.github/ISSUE_TEMPLATE/bug_report.yml`;
- `CHANGELOG.md`, whose `## [Unreleased]` section becomes the new release, with its compare link.

## Steps

1. Make sure `main` is green and `CHANGELOG.md` lists everything under `## [Unreleased]`.
2. Bump, on a branch:

   ```bash
   git switch -c release/X.Y.Z
   python scripts/bump_version.py minor        # or patch, major, or an explicit version such as 0.7.0-rc.1
   ```

3. Rebuild the UI so the committed bundle carries the new version:

   ```bash
   cd frontend && npm run build && cd ..
   ```

   The build writes new, content-hashed file names under `llmdyno/web/static/assets/` and deletes the old ones, so
   the next step must add new files, not only modified ones (`tests/test_static_ui.py` fails when `index.html` points
   at a file that isn't there).

4. If the web API changed, regenerate the files made from it, and check the docs site:

   ```bash
   python scripts/gen_js_client.py
   python scripts/gen_reference_docs.py
   mkdocs build --strict
   ```

5. Commit, open a pull request and wait for CI:

   ```bash
   git add -A
   git commit -m "Release vX.Y.Z"
   git push -u origin release/X.Y.Z
   ```

6. When CI is green, bring `main` up to the branch (fast-forward) and push an annotated tag:

   ```bash
   git switch main && git merge --ff-only release/X.Y.Z && git push
   git tag -a vX.Y.Z -m "LLMDyno X.Y.Z"
   git push origin vX.Y.Z
   ```

The `.github/workflows/release.yml` workflow then runs three jobs:

- **release**: checks that the tag matches `__version__`, runs the Python tests (Ubuntu, Python 3.12), builds the
  wheel and source archive, and publishes a GitHub release with both files attached and the changelog section as its
  notes ("See CHANGELOG.md" if the section is missing). A version with a `-` (such as `0.7.0-rc.1`) is marked as a
  pre-release.
- **pypi** and **npm**: run only after the release job succeeds, so failing tests block publishing.

PyPI and npm never let a version be uploaded twice. If something is wrong with a published release, fix it in a new
patch version.

## Publishing to PyPI

The `pypi` job uploads the wheel and source archive to PyPI once two things are set up (both one-time; no token is
stored anywhere):

1. On pypi.org, add a trusted publisher (a "pending publisher" before the first upload): owner `speak2jerome`,
   repository `llmdyno`, workflow `release.yml`, environment `pypi`.
2. In the GitHub repository settings, add the variable `PUBLISH_PYPI` with the value `true`.

Until then the job is skipped and releases go to GitHub only. Pre-releases go to PyPI too, under their normalized
version (`0.7.0rc1`); pip installs them only with `--pre` or an exact version.

## Publishing to npm

The `npm` job checks that `js/package.json` matches the tag, runs `npm ci`, the build and the tests on Node 24, and
publishes with provenance. Setup, once:

1. Create an account on npmjs.com, with two-factor authentication.
2. Publish the first version by hand, because npm links a workflow only to a package that exists:

   ```bash
   cd js && npm ci && npm run build && npm login && npm publish --access public
   ```

3. On npmjs.com, go to llmdyno, then Settings, then Trusted publishing. Add GitHub Actions with owner
   `speak2jerome`, repository `llmdyno`, workflow `release.yml` and environment `npm`.
4. In the GitHub repository settings, add the variable `PUBLISH_NPM` with the value `true`.

After that, every tag publishes to npm as well, and no token is stored. A pre-release version (`0.7.0-rc.1`) goes
out under the `next` tag, so `npm install llmdyno` keeps getting the latest release. npm's page may also list a
`0.0.0-stage` version: that is a placeholder npm made for the package's staged publishing, not a release.

## What CI checks

`.github/workflows/ci.yml` runs on every pull request and push to `main`:

| Job | Where | What |
|---|---|---|
| Python | Ubuntu and Windows × Python 3.11, 3.12 and 3.13; macOS, Ubuntu ARM64 and Windows ARM64 (allowed to fail) on 3.12 | `ruff check`, `pytest`, `llmdyno --version`, `scripts/platform_probe.py` |
| Integrations, typing, notebooks, docs | Ubuntu, Python 3.12, every extra | `pytest` with the integrations, `pyright`, the example notebooks with nbmake, `mkdocs build --strict`, `python -m build` and `twine check` |
| JavaScript | Node 22 and 24 | `gen_js_client.py --check`, type check, build, unit tests, live tests against a running server, installing the packed package and a dry run of `npx llmdyno` |
| Frontend | Node 22 | `tsc`, `npm run build` |

## After a release

- The GitHub release lists the wheel and source archive.
- `pip index versions llmdyno` and `npm view llmdyno dist-tags` show the new version, and
  `pip install llmdyno==X.Y.Z` and `npx llmdyno@X.Y.Z --version` work in a clean folder.
- The docs site redeployed (the Docs workflow runs on the push to `main`).
- The README badges follow within minutes: the PyPI badge reads PyPI's JSON API through shields.io, which caches it for
  two minutes. GitHub keeps its own copy of each badge image; if one still shows the old version after an hour, purge
  it with `curl -X PURGE <the badge's camo.githubusercontent.com URL>`.
- PyPI and npm show the README as it was at release time, so documentation fixes reach them only with the next
  release.

## Documentation site

`.github/workflows/docs.yml` builds the site with MkDocs (`mkdocs build --strict`) and publishes it to GitHub Pages on
every push to `main` that touches `docs/`, `mkdocs.yml`, `CHANGELOG.md`, `llmdyno/`, `scripts/mkdocs_seo.py` or the
workflow itself, and on demand from the Actions tab. One-time setup: in the repository's Settings → Pages, set "Source"
to "GitHub Actions". To preview locally: `pip install -e ".[docs]"` then `mkdocs serve`.

Two pages are generated from the code: `python scripts/gen_reference_docs.py` writes
[the command line reference](reference/cli.md) and [the web API map](reference/web-api.md), and
`tests/test_docs_site.py` fails when they are out of date. Every page in the navigation also needs a description in
`mkdocs.yml` (`extra.page_descriptions`) and a link in `docs/llms.txt`; the same test checks both.

You are working in /workspace, an existing Python library called `semverlite` (semantic versions and npm-style ranges).

Users have filed the bug reports in `ISSUE.md`. Please:

1. Find and fix the root cause of each reported issue in the library code. Follow the semver 2.0.0 specification and npm's range semantics.
2. Don't break existing behaviour: `pytest -q` must keep passing. Do not modify `tests/test_basic.py`.
3. Add regression tests for each issue in a new file `tests/test_issues.py`, with at least one test per issue.
4. Add one bullet per fix under `## Unreleased` in `CHANGELOG.md`, referencing the issue number (e.g. `#12`).

There is no internet access, so do not install anything. When you are finished, reply with a short summary of each root cause and fix.

# Writing a benchmark

A benchmark is a coding task with hidden grading. The agent sees the prompt and the starter workspace; it never sees
the tests. Grading runs in a fresh offline container after the agent has finished.

The quickest route is **Benchmarks → New benchmark** in the app: a step-by-step editor for prompts, starter files,
hidden tests, checks and a reference solution, followed by automatic validation. This page describes the files it
produces, which you can also write by hand and import as a zip.

## Layout

```
my_task/
├── benchmark.json          metadata, stages, grader, context needs
├── prompts/stage1.md       one prompt per stage
├── workspace/              starter files the agent begins with (optional)
├── grader/
│   ├── spec.json           checks and where the hidden tests are
│   └── tests/              hidden pytest files
└── reference/              a known-good solution (used for validation)
```

## benchmark.json

```json
{
  "id": "my_task",
  "version": 1,
  "title": "Word-frequency CLI",
  "summary": "One line shown in lists.",
  "description": "What it tests and why.",
  "category": "CLI",
  "difficulty": "easy",
  "languages": ["Python"],
  "tags": ["cli"],
  "stages": [{ "prompt": "prompts/stage1.md", "timeout_s": 600 }],
  "grade_each_stage": false,
  "grader": { "type": "spec", "path": "grader/spec.json", "timeout_s": 300 },
  "min_context": 16000,
  "expected_minutes": { "local": 1, "cloud": 0.5 },
  "reference": "reference"
}
```

- **Stages** are sent one after another to the same workspace. Multi-stage tasks test whether an agent can extend
  its own code; with `grade_each_stage` the hidden tests run after every stage.
- **min_context** is the context size the task needs; profiles below it get a warning before the plan starts.
- Bump **version** when you change the task, so results from different versions aren't silently compared.

## grader/spec.json

```json
{
  "tests": "grader/tests",
  "checks": [
    { "name": "module_present", "type": "file_exists", "path": "wordfreq.py" },
    { "name": "own_tests_exist", "type": "test_count", "path": "tests", "min": 3 },
    { "name": "own_tests_pass", "type": "command", "cmd": "python -m pytest -q tests", "expect_exit": 0 }
  ]
}
```

- **Hidden tests** (pytest) decide correctness: the share of tests that pass.
- **Checks** decide instruction following. Types: `file_exists`, `file_contains` (`path`, `text`), `glob`
  (`pattern`, `min`), `test_count` (`path`, `min`) and `command` (`cmd`, `expect_exit`). Checks with an empty path
  or a pattern that matches anything are rejected, because they would pass on any workspace.

The grader image has Python 3.12 and Node 24 with common libraries preinstalled; it has no internet.

## Validation

**Validate grader** runs the grader twice: on the starter workspace, where the hidden tests should fail, and on the
starter plus the reference solution, where they should pass. A benchmark that passes on the empty starter, or fails
on its own reference, is flagged before anyone wastes a GPU-hour on it.

## Tips for good tasks

- Specify behaviour precisely (tie-breaking, error codes, output format) and test exactly that.
- Ask for the agent's own tests too: a check that they exist and pass rewards agents that verify their work.
- Keep runtime dependencies to what the sandbox image already has.
- Prefer several small, sharp tests over one large one, so partial credit means something.

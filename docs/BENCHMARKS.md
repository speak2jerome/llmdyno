# Writing a benchmark

A benchmark is a coding task with hidden grading. The agent sees the prompt and the starting workspace; it never sees
the tests. Grading runs in a fresh offline container after the agent has finished.

The quickest route is **Benchmarks → Create benchmark** in the app: a step-by-step editor (Basics, Stages, Starting
files, Grading, Reference, Review) for prompts, starter files, hidden tests, checks and a reference solution, with
"Save & validate" at the end. From Python, `llmdyno.create_benchmark(spec)` takes the same spec, and
`llmdyno.benchmark("t0_smoke_cli").duplicate("my_copy")` gives you an editable copy of any benchmark. This page
describes the files they produce, which you can also write by hand and import as a zip.

## Layout

```
my_task/
├── benchmark.json          metadata, stages, grader, context needs
├── prompts/stage1.md       one prompt per stage
├── workspace/              starter files the agent begins with (named by "workspace" in benchmark.json)
├── grader/
│   ├── spec.json           checks and where the hidden tests are (or grade.py for a script grader)
│   └── tests/              hidden pytest files
├── reference/              a known-good solution, used only for validation
└── probes/                 optional robustness tests for the code-quality score
```

Your benchmarks live in `<data folder>/benchmarks/<id>/`. A folder you put there by hand is picked up too.

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
  "workspace": "workspace",
  "reference": "reference"
}
```

| Field | Required | Default | What it does |
|---|---|---|---|
| `id` | yes | | Lower-case letters, digits and underscores (no dashes), 3 to 61 characters. For a zip import it must match the folder name. |
| `title` | yes | | Shown in lists, plans and results. |
| `stages` | yes | | One entry per stage: `prompt` (a path to the prompt file) and `timeout_s` (required; multiplied by the plan's timeout multiplier). `add_files` names a folder copied into the workspace before that stage. |
| `grader` | yes | | `type` (`spec` or `script` for your own benchmarks), `path` (default `grader/spec.json`) and `timeout_s` (default 600). |
| `workspace` | no | none | The folder of starter files. **Without it the agent starts in an empty workspace**, even if a `workspace/` folder exists. |
| `reference` | no | none | The folder of a known-good solution, laid over the starter for validation. |
| `probes` | no | none | A folder of pytest files run against the finished workspace (offline, in the code-quality image); the share that pass is the "probes" part of the quality score. |
| `decompress` | no | none | `.gz` files in the workspace to unpack after copying (for large data files). |
| `grade_each_stage` | no | `false` | Run the hidden tests after every stage, not just the last. |
| `min_context` | no | | The context size the task needs; profiles below it get a warning before the plan starts. |
| `expected_minutes` | no | 5 local, 3 cloud | Used for time estimates until real runs exist. |
| `reference_tokens` | no | 200 000 in, 12 000 out, 80% cache hits | Used for cost estimates until three runs of the task have finished. |
| `version` | no | | Recorded with every run. Results are grouped by `id`, not version, so give a task a new id when a change makes old and new results incomparable. |
| `summary`, `description`, `category`, `difficulty`, `languages`, `tags` | no | | Shown on the Benchmarks page and used by its filters. |
| `env` | no | | Run the task in its own Docker image (see below). |

LLMDyno adds some fields when it loads a benchmark (`builtin`, `dir`, `n_stages`, `has_reference`, `has_probes`); don't
write them yourself.

- **Stages** are sent one after another to the same workspace. Multi-stage tasks test whether an agent can extend
  its own code. With `add_files`, a later stage can bring in new files (a data drop, a bug report); put them in
  `stage_files/stageN/` so the quality analysis knows they are not the agent's.

## Grading

Each run gets two scores from the grader:

- **Correctness** is the share of hidden tests that pass. A benchmark with checks but no hidden tests scores 0 for
  correctness, which still carries half the final score by default, so always include hidden tests.
- **Instruction following** is the share of checks that pass, averaged together with three checks LLMDyno adds to
  every run: the agent made no attempt to install packages (the sandbox is offline), it finished within the time
  limit, and its final message is a real summary (at least 20 characters).

### A spec grader (grader/spec.json)

```json
{
  "tests": "grader/tests",
  "timeout_s": 600,
  "checks": [
    { "name": "module_present", "type": "file_exists", "path": "wordfreq.py" },
    { "name": "own_tests_exist", "type": "test_count", "path": "tests", "min": 3 },
    { "name": "own_tests_pass", "type": "command", "cmd": "python -m pytest -q tests", "expect_exit": 0 }
  ]
}
```

- **`tests`** is the folder of hidden pytest files, relative to the benchmark folder. They run with the workspace as
  the current folder and on `PYTHONPATH`, 60 seconds per test, `timeout_s` for the whole run (default 600).
- **`checks`** each have a `name` (default `check_<n>`) and a `type`:

| Type | Fields | Passes when |
|---|---|---|
| `file_exists` | `path` | the file exists in the workspace |
| `file_contains` | `path`, `text` | the file contains the text (case-sensitive) |
| `glob` | `pattern`, `min` (default 1) | at least `min` files match the pattern |
| `test_count` | `path`, `min` (default 1) | the agent wrote at least `min` test functions (`def test_…` in `test_*.py`) under `path` |
| `command` | `cmd`, `expect_exit` (default 0), `timeout` (default 300) | the shell command, run in the workspace, exits with that code |

The editor and `create_benchmark()` reject checks with an empty path or a pattern that matches anything, because they
would pass on any workspace. Zip imports and folders you write by hand are not checked this way, so validate them.

### A script grader

For grading that pytest and checks can't express, set `"grader": {"type": "script", "path": "grader/grade.py"}`. The
script runs as `python /task/grader/grade.py` in the grader container, with:

- `/work`: a copy of the finished workspace (the current folder);
- `/task`: the benchmark folder, read-only;
- `/grader_common`: helpers you can import (`pytest_results`, `run`, `count_test_functions`, `emit`);
- environment variables `STAGE`, `WORK`, `TASK_DIR` and `SPEC`;
- no network and 8 GB of memory.

The last line it prints must be JSON with at least `correctness` and `instruction_following` (0 to 1), `tests_total`
and `tests_passed`; `checks_total`, `checks_passed`, `tests` and `checks` are shown on the run page if present, and any
other keys are kept with the run. The built-in tasks other than the smoke test use script graders; their `grade.py`
files are good examples.

The grader image has Python 3.12 and Node 24 with common libraries preinstalled; it has no internet.

## Suites

A suite is a named list of benchmarks. Plans take suite ids and benchmark ids mixed together; they are expanded in
order, without duplicates.

| Suite | Benchmarks |
|---|---|
| `suite_smoke` | the two-minute smoke test (`t0_smoke_cli`) |
| `suite_quick` | the smoke test, the Flask site and the bug fixes (`t0`, `t1`, `t5`): about 5 minutes per local profile |
| `suite_round1` | the five tasks of the round 1 study (`t1` to `t5`) |
| `suite_web` | both web-application tasks (`t1`, `t2`) |

Imports add `suite_swebench_<dataset>` and `suite_polyglot_all` / `suite_polyglot_<language>`. Make your own on the
Benchmarks page ("New suite") or with `llmdyno.create_suite(name, benchmark_ids)`.

## Benchmarks with their own image

A task that needs a particular environment (a repository with its dependencies installed, or compilers the sandbox
doesn't have) can name a Docker image. The agent then runs inside that image instead of the LLMDyno sandbox, with the
harness mounted in from its portable runtime. SWE-bench and Aider polyglot imports use this; your own benchmarks can
too:

```json
"env": {
  "image": "ghcr.io/me/my-env:1",
  "platform": "linux/amd64",
  "workspace": "volume",
  "repo_dir": "/srv/app",
  "base_commit": "0123abcd",
  "grader_in_env": true
}
```

- **workspace** `bind` (default): the run folder is mounted at `/workspace` as usual, starting from the benchmark's
  starter files. `volume`: whatever is at `repo_dir` inside the image is copied into a fresh Docker volume per run and
  mounted at both `repo_dir` and `/workspace`, so installed packages and editable installs keep pointing at the right
  place.
- **platform** is read from the image name when it says (`x86_64`, `amd64`, `arm64`), otherwise it is the host's. Set
  it for images built for one architecture only; they run under emulation on the other.
- **base_commit** is used to diff the agent's changes when the image's own `HEAD` can't be read.
- **grader_in_env** runs the grader in the same image (it needs `python`, version 3, on the PATH); otherwise the grader
  uses the standard sandbox image.
- Images are pulled when a run starts. Images whose names start with `llmdyno-` are built locally and never pulled.
- The image should have `bash` and `git` and run as root. If it has `/opt/miniconda3/bin/activate`, the `testbed`
  environment is activated before the agent starts, as in the SWE-bench images.
- Code-quality analysis and probes are skipped for these benchmarks.

Grader types for imported tasks: `swebench` (the official harness, see the README) and `polyglot` (the exercise's
original tests restored over the agent's copies, every test enabled, solved only if all pass). Both score correctness
as 1 or 0. Agents from `python_harness()` and `node_harness()` can't run these tasks; see
[Harnesses](HARNESSES.md#2-your-own-agent).

## Importing and sharing

- **Export** a benchmark as a zip from its drawer ("Export as zip"), with `Benchmark.export(path)` or
  `llmdyno benchmark export ID`.
- **Import** a zip on the Benchmarks page ("Import zip") or with `llmdyno.import_benchmark(path)`. The zip must hold
  exactly one `<id>/benchmark.json`, the id must match the folder, a benchmark with that id must not exist yet, and the
  grader must be `spec` or `script`.

## Validation

**Validate grader** (or `Benchmark.validate()`) grades two workspaces:

1. **The starter**, with every stage's `add_files` copied in. It is flagged when it already passes more than half the
   hidden tests, because then the tests don't measure the agent's work.
2. **The starter plus the reference**, which must pass every hidden test. Checks don't have to pass here.

It also flags a grader that crashes, or a benchmark with nothing to grade. Without a reference solution only the
first half runs, and the report says so. For SWE-bench tasks it grades the task's gold patch with the official harness
instead, which must resolve; if it doesn't, the image or Docker setup on this machine is the problem, not the model.

## Tips for good tasks

- Specify behaviour precisely (tie-breaking, error codes, output format) and test exactly that.
- Ask for the agent's own tests too: a check that they exist and pass rewards agents that verify their work.
- Keep runtime dependencies to what the sandbox image already has.
- Prefer several small, sharp tests over one large one, so partial credit means something.

"""Benchmarks and suites: built-in, your own and imported (SWE-bench, Aider polyglot)."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from ..errors import NotFoundError
from ._core import Handle, Job, _id, call, covers

__all__ = ["Benchmark", "Suite", "list_benchmarks", "benchmark", "create_benchmark", "import_benchmark", "list_suites",
           "suite", "create_suite", "import_catalog", "import_swebench", "import_polyglot", "install_swebench_harness",
           "build_polyglot_image", "remove_imported"]

_SUMMARY_KEYS = ("id", "title", "category", "difficulty", "languages", "summary", "n_stages", "expected_minutes",
                 "builtin")


@covers("GET /api/benchmarks")
def list_benchmarks(category: str | None = None, search: str | None = None) -> list:
    """Benchmarks in the data folder (built-in, your own and imported), as dicts with id, title, category, …"""
    out = []
    for b in call("benchmarks.list_benchmarks"):
        if category and b.get("category", "").lower() != category.lower():
            continue
        text = f"{b['id']} {b.get('title', '')} {b.get('summary', '')} {' '.join(b.get('tags') or [])}".lower()
        if search and search.lower() not in text:
            continue
        out.append({k: b.get(k) for k in _SUMMARY_KEYS})
    return out


@covers("GET /api/suites")
def list_suites() -> list:
    """Suites (named groups of benchmarks): built-in ones plus yours and those created by imports."""
    return call("benchmarks.list_suites")


@covers("POST /api/imports/swebench")
def import_swebench(dataset: str = "verified_mini", *, limit: int | None = None,
                    instance_ids: Sequence[str] | None = None, quiet: bool = False) -> dict:
    """Import SWE-bench tasks as benchmarks: dataset "verified" (500), "lite" (300) or "verified_mini" (50).
    Grading needs the official harness: setup(swebench=True). Returns the new benchmark ids and suite id."""
    r = call("imports.import_swebench", body={"dataset": dataset, "limit": limit or 0,
                                              "instance_ids": list(instance_ids or [])})
    return Job(r["job_id"]).wait(quiet=quiet)


@covers("POST /api/imports/polyglot")
def import_polyglot(languages: Sequence[str] | None = None, *, quiet: bool = False) -> dict:
    """Import Aider's polyglot benchmark (cpp, go, java, javascript, python, rust). Needs the toolchain image:
    setup(polyglot=True)."""
    r = call("imports.import_polyglot", body={"languages": list(languages) if languages else None})
    return Job(r["job_id"]).wait(quiet=quiet)


@covers("GET /api/imports")
def import_catalog() -> dict:
    """What can be imported and what is ready: SWE-bench datasets and its harness, the polyglot languages, image and
    exercise cache, and how many of each are imported."""
    return call("imports.import_catalog")


@covers("POST /api/imports/swebench/harness")
def install_swebench_harness(quiet: bool = False) -> dict:
    """Install the official SWE-bench harness into its own virtual environment (about 250 MB)."""
    return Job(call("imports.install_swebench_harness")["job_id"]).wait(quiet=quiet)


@covers("POST /api/imports/polyglot/image")
def build_polyglot_image(quiet: bool = False) -> dict:
    """Build the polyglot toolchain image (C++, Go, Java, JavaScript, Rust; a few GB)."""
    return Job(call("imports.build_polyglot_image")["job_id"]).wait(quiet=quiet)


@covers("DELETE /api/imports/{kind}")
def remove_imported(kind: str) -> int:
    """Delete every imported benchmark of one kind ("swebench" or "polyglot") and its suites; returns how many
    benchmarks were removed. They can be imported again at any time."""
    return call("imports.remove_imported", kind=kind)["removed"]


# ------------------------------------------------------------------ single benchmarks, your own ones
class Benchmark(Handle):
    """A benchmark: its stages and prompts, starter workspace, grader and reference solution."""

    _get_op, _id_arg = "benchmarks.benchmark_detail", "bid"

    @property
    def title(self) -> str:
        return self._data["title"]

    @property
    def builtin(self) -> bool:
        return bool(self._data.get("builtin"))

    @property
    def prompts(self) -> list:
        """The prompt of each stage, in order."""
        return list(self._data.get("prompts") or [])

    @covers("GET /api/benchmarks/{bid}")
    def refresh(self) -> "Benchmark":
        return super().refresh()

    @covers("GET /api/benchmarks/{bid}/spec")
    def spec(self) -> dict:
        """The editable definition of one of your benchmarks (what create_benchmark() and update() take)."""
        return call("benchmarks.benchmark_spec", bid=self.id)

    @covers("PUT /api/benchmarks/{bid}")
    def update(self, spec: dict) -> "Benchmark":
        """Replace one of your benchmarks with a new spec (built-in ones are read-only: duplicate() them first)."""
        call("benchmarks.update_benchmark", bid=self.id, body=dict(spec))
        return self.refresh()

    @covers("POST /api/benchmarks/{bid}/duplicate")
    def duplicate(self, new_id: str) -> "Benchmark":
        """An editable copy under a new id (3-61 lowercase letters, digits or underscores)."""
        return Benchmark(call("benchmarks.duplicate_benchmark", bid=self.id, body={"new_id": new_id}))

    @covers("DELETE /api/benchmarks/{bid}")
    def delete(self) -> None:
        call("benchmarks.delete_benchmark", bid=self.id)

    @covers("GET /api/benchmarks/{bid}/export")
    def export(self, path: Union[str, Path, None] = None) -> bytes:
        """The benchmark as a zip (its folder: benchmark.json, workspace, grader, reference); written to path if
        given. import_benchmark() reads it back."""
        data = call("benchmarks.export_benchmark", bid=self.id)["content"]
        if path:
            Path(path).write_bytes(data)
        return data

    @covers("POST /api/benchmarks/{bid}/validate")
    def validate(self, wait: bool = True, quiet: bool = False) -> Union[dict, Job]:
        """Check the grader: the starter workspace must fail it and the reference solution must pass. Returns the
        report (or the Job with wait=False). Needs Docker and the sandbox image."""
        job = Job(call("benchmarks.validate_benchmark", bid=self.id)["job_id"])
        return job.wait(quiet=quiet) if wait else job

    def __repr__(self):
        d = self._d or {}
        return f"<llmdyno.Benchmark {self.id} {d.get('title', '')!r}>"


def benchmark(benchmark_id: str) -> Benchmark:
    """A benchmark by id, with everything about it."""
    return Benchmark(benchmark_id).refresh()


@covers("POST /api/benchmarks")
def create_benchmark(spec: dict) -> Benchmark:
    """Create your own benchmark from a spec, the same one the benchmark editor builds: id, title, prompts per stage,
    starter files, hidden tests or checks for the grader, an optional reference solution. See docs/BENCHMARKS.md."""
    return Benchmark(call("benchmarks.create_benchmark", body=dict(spec)))


@covers("POST /api/upload/benchmark")
def import_benchmark(source: Union[str, Path, bytes]) -> Benchmark:
    """Add a benchmark from a zip (a path or its bytes), such as one Benchmark.export() made on another machine."""
    data = source if isinstance(source, (bytes, bytearray)) else Path(source).expanduser().read_bytes()
    return Benchmark(call("benchmarks.import_benchmark_zip", data=bytes(data)))


# ------------------------------------------------------------------ suites
class Suite(Handle):
    """A named group of benchmarks; pass its id wherever benchmarks are expected."""

    @property
    def name(self) -> str:
        return self._data["name"]

    @property
    def benchmark_ids(self) -> list:
        return list(self._data.get("benchmark_ids") or [])

    def refresh(self) -> "Suite":
        hit = [x for x in call("benchmarks.list_suites") if x["id"] == self.id]
        if not hit:
            raise NotFoundError(f"no suite {self.id}")
        self._d = hit[0]
        return self

    @covers("PUT /api/suites/{sid}")
    def update(self, *, name: str | None = None, benchmarks: Sequence | None = None,
               description: str | None = None) -> "Suite":
        """Rename it, change its description or its benchmarks (built-in suites are read-only)."""
        body = {k: v for k, v in (("name", name), ("description", description)) if v is not None}
        if benchmarks is not None:
            body["benchmark_ids"] = [_id(b) for b in benchmarks]
        self._d = call("benchmarks.update_suite", sid=self.id, body=body)
        return self

    @covers("DELETE /api/suites/{sid}")
    def delete(self) -> None:
        call("benchmarks.delete_suite", sid=self.id)

    def __repr__(self):
        d = self._d or {}
        return f"<llmdyno.Suite {self.id} {d.get('name', '')!r} {len(d.get('benchmark_ids') or [])} benchmarks>"


def suite(suite_id: str) -> Suite:
    """A suite by id."""
    return Suite(suite_id).refresh()


@covers("POST /api/suites")
def create_suite(name: str, benchmarks: Sequence, description: str = "") -> Suite:
    """A new suite of benchmarks (Benchmark objects or ids)."""
    return Suite(call("benchmarks.create_suite", body={"name": name, "description": description,
                                                       "benchmark_ids": [_id(b) for b in benchmarks]}))

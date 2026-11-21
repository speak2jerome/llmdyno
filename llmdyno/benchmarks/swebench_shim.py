"""Launch the official SWE-bench harness (swebench.harness.run_evaluation) with Unix line endings on Windows.

The harness writes the model patch and the eval script to disk with Path.write_text() and copies the files into the
Linux task container as they are. On Windows, text mode turns every "\\n" into "\\r\\n", so `git apply` rejects the
patch and bash chokes on the script. This shim makes write_text keep "\\n" (and UTF-8) and then runs the harness
unchanged, so grading stays the official one. It runs in the harness's own venv, so it imports nothing from LLMDyno.

    python swebench_shim.py -d dataset.json -s test -i <id> -p preds.jsonl -id <run> ...
"""
import pathlib
import runpy
import sys

# this file sits next to LLMDyno's own swebench.py: keep its folder off the path so the installed package is used
_here = pathlib.Path(__file__).resolve().parent
sys.path = [p for p in sys.path if p and pathlib.Path(p).resolve() != _here]

if sys.platform == "win32":
    _write_text = pathlib.Path.write_text

    def write_text(self, data, encoding=None, errors=None, newline=None):
        return _write_text(self, data, encoding=encoding or "utf-8", errors=errors,
                           newline="\n" if newline is None else newline)

    pathlib.Path.write_text = write_text

sys.argv[0] = "swebench.harness.run_evaluation"
runpy.run_module("swebench.harness.run_evaluation", run_name="__main__", alter_sys=True)

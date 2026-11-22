"""The JavaScript client in js/ stays in step with the server: its table of operations is generated from the web API's
routes (scripts/gen_js_client.py), and its version is the Python package's. The client's own tests run with npm."""
import importlib.util
import json
from pathlib import Path

import llmdyno

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "js"


def _generator():
    spec = importlib.util.spec_from_file_location("gen_js_client", ROOT / "scripts" / "gen_js_client.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generated_operations_are_current():
    current = (JS / "src" / "generated.ts").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert current == _generator().render(), "the web API changed: run python scripts/gen_js_client.py"


def test_every_service_operation_reaches_the_javascript_client():
    from llmdyno.sdk.remote import route_table
    text = (JS / "src" / "generated.ts").read_text(encoding="utf-8")
    missing = [op for op in route_table() if f'"{op}": {{' not in text]
    assert not missing


def test_javascript_package_version_is_the_python_version():
    pkg = json.loads((JS / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((JS / "package-lock.json").read_text(encoding="utf-8"))
    assert pkg["name"] == "llmdyno" and pkg["version"] == llmdyno.__version__
    assert lock["version"] == lock["packages"][""]["version"] == llmdyno.__version__
    assert f'VERSION = "{llmdyno.__version__}"' in (JS / "src" / "version.ts").read_text(encoding="utf-8")


def test_javascript_package_metadata():
    pkg = json.loads((JS / "package.json").read_text(encoding="utf-8"))
    assert pkg["bin"] == {"llmdyno": "dist/cli.js"} and pkg["type"] == "module" and pkg["license"] == "MIT"
    assert pkg["engines"]["node"] == ">=22" and not pkg.get("dependencies")
    assert pkg["repository"]["directory"] == "js" and pkg["homepage"].startswith("https://")
    assert (JS / "README.md").exists() and (JS / "LICENSE").read_text() == (ROOT / "LICENSE").read_text()

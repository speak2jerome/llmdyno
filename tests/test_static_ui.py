"""The committed web UI build is whole: every file index.html loads is in the package.

`npm run build` writes content-hashed file names and deletes the old ones, so a release commit that only stages
modified files (git commit -am) would ship an index.html pointing at scripts that are not there."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "llmdyno" / "web" / "static"


def test_index_html_points_at_files_that_exist():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="/([^"#?]+)"', html)
    assert any(r.startswith("assets/") and r.endswith(".js") for r in refs), "index.html loads no script bundle"
    missing = [r for r in refs if not (STATIC / r).is_file()]
    assert not missing, f"index.html refers to files missing from llmdyno/web/static: {missing}; rebuild and commit"

"""Bump the LLMDyno version everywhere it is written down, and roll the changelog.

    python scripts/bump_version.py patch        # 0.1.0 -> 0.1.1
    python scripts/bump_version.py minor        # 0.1.0 -> 0.2.0
    python scripts/bump_version.py 0.3.0-rc.1   # an explicit version

The single source of truth is llmdyno/__init__.py (pyproject reads it through hatch). This script also updates
frontend/package.json and package-lock.json, and turns the CHANGELOG's "Unreleased" section into the new release.
It does not commit or tag; it prints the commands to do that.
"""
import datetime
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "llmdyno" / "__init__.py"
PKG = ROOT / "frontend" / "package.json"
LOCK = ROOT / "frontend" / "package-lock.json"
CHANGELOG = ROOT / "CHANGELOG.md"
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?$")
REPO = "https://github.com/speak2jerome/llmdyno"


def current():
    return re.search(r'__version__ = "([^"]+)"', INIT.read_text(encoding="utf-8")).group(1)


def next_version(cur, how):
    if SEMVER.match(how):
        return how
    major, minor, patch = (int(x) for x in SEMVER.match(cur).groups()[:3])
    if how == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if how == "minor":
        return f"{major}.{minor + 1}.0"
    if how == "major":
        return f"{major + 1}.0.0"
    sys.exit(f"expected patch, minor, major or a version like 0.2.0, got {how!r}")


def write_json(path, update):
    data = json.loads(path.read_text(encoding="utf-8"))
    update(data)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def roll_changelog(old, new):
    text = CHANGELOG.read_text(encoding="utf-8")
    if "## [Unreleased]" not in text:
        sys.exit("CHANGELOG.md has no '## [Unreleased]' section")
    today = datetime.date.today().isoformat()
    text = text.replace("## [Unreleased]", f"## [Unreleased]\n\n## [{new}] - {today}", 1)
    text = re.sub(r"^\[Unreleased\]: .*$", f"[Unreleased]: {REPO}/compare/v{new}...HEAD\n[{new}]: {REPO}/compare/v{old}...v{new}",
                  text, count=1, flags=re.M)
    CHANGELOG.write_text(text, encoding="utf-8")


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    old = current()
    new = next_version(old, sys.argv[1])
    if new == old:
        sys.exit(f"already at {old}")
    INIT.write_text(re.sub(r'__version__ = "[^"]+"', f'__version__ = "{new}"', INIT.read_text(encoding="utf-8")),
                    encoding="utf-8")
    write_json(PKG, lambda d: d.__setitem__("version", new))

    def lock(d):
        d["version"] = new
        d.get("packages", {}).get("", {})["version"] = new
    if LOCK.exists():
        write_json(LOCK, lock)
    roll_changelog(old, new)
    print(f"{old} -> {new}\n\nNext:\n  cd frontend && npm run build && cd ..\n  git commit -am \"Release v{new}\"\n"
          f"  git tag -a v{new} -m \"LLMDyno {new}\"\n  git push && git push --tags")


if __name__ == "__main__":
    main()

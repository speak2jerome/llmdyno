"""npm-style version ranges: comparators, caret, tilde, x-ranges, hyphen ranges and ||."""
from __future__ import annotations

import re

from .version import InvalidVersion, Version

_OPS = (">=", "<=", ">", "<", "=")
_PARTIAL = re.compile(r"^v?(?P<major>\d+|[xX*])(?:\.(?P<minor>\d+|[xX*]))?(?:\.(?P<patch>\d+|[xX*]))?"
                      r"(?:-(?P<pre>[0-9A-Za-z.-]+))?$")


class InvalidRange(ValueError):
    pass


def _is_wild(part):
    return part is None or part in ("x", "X", "*")


def _partial(text):
    m = _PARTIAL.match(text)
    if not m:
        raise InvalidRange(f"invalid version in range: {text!r}")
    major, minor, patch = m.group("major"), m.group("minor"), m.group("patch")
    return major, minor, patch, m.group("pre")


def _v(major, minor=0, patch=0, pre=None):
    return Version(int(major), int(minor), int(patch), tuple(pre.split(".")) if pre else ())


def _expand_caret(text):
    major, minor, patch, pre = _partial(text)
    if _is_wild(major):
        return [(">=", _v(0))]
    if _is_wild(minor):
        return [(">=", _v(major)), ("<", _v(int(major) + 1))]
    if _is_wild(patch):
        lower = _v(major, minor)
        if int(major) == 0:
            return [(">=", lower), ("<", _v(0, int(minor) + 1))]
        return [(">=", lower), ("<", _v(int(major) + 1))]
    lower = _v(major, minor, patch, pre)
    return [(">=", lower), ("<", _v(int(major) + 1))]


def _expand_tilde(text):
    major, minor, patch, pre = _partial(text)
    if _is_wild(major):
        return [(">=", _v(0))]
    if _is_wild(minor):
        return [(">=", _v(major)), ("<", _v(int(major) + 1))]
    lower = _v(major, minor, 0 if _is_wild(patch) else patch, pre)
    return [(">=", lower), ("<", _v(major, int(minor) + 1))]


def _expand_xrange(op, text):
    major, minor, patch, pre = _partial(text)
    if _is_wild(major):
        return [(">=", _v(0))] if op in ("", "=", ">=", "<=") else [("<", _v(0))]
    if not _is_wild(minor) and not _is_wild(patch):
        return [(op or "=", _v(major, minor, patch, pre))]
    if _is_wild(minor):
        lo, hi = _v(major), _v(int(major) + 1)
    else:
        lo, hi = _v(major, minor), _v(major, int(minor) + 1)
    if op in ("", "="):
        return [(">=", lo), ("<", hi)]
    if op == ">":
        return [(">=", hi)]
    if op == ">=":
        return [(">=", lo)]
    if op == "<":
        return [("<", lo)]
    return [("<", hi)]  # "<="


def _parse_comparator_set(text):
    text = re.sub(r"\s*-\s+", " - ", text.strip())
    if " - " in text:
        lo_text, hi_text = (s.strip() for s in text.split(" - ", 1))
        lo = _expand_xrange(">=", lo_text)
        hi = _expand_xrange("<=", hi_text)
        return lo + hi
    comps = []
    for tok in re.sub(r"(>=|<=|>|<|=|\^|~)\s+", r"\1", text).split():
        if tok.startswith("^"):
            comps += _expand_caret(tok[1:])
        elif tok.startswith("~"):
            comps += _expand_tilde(tok[1:].lstrip(">"))
        else:
            op = next((o for o in _OPS if tok.startswith(o)), "")
            comps += _expand_xrange(op, tok[len(op):])
    return comps


def _test(op, a, b):
    return {"=": a == b, ">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b}[op]


class Range:
    def __init__(self, text: str):
        self.text = text
        parts = [p for p in text.split("||")]
        try:
            self.sets = [_parse_comparator_set(p) if p.strip() else [(">=", _v(0))] for p in parts]
        except InvalidVersion as e:
            raise InvalidRange(str(e)) from e

    def __repr__(self):
        return f"Range({self.text!r})"

    def contains(self, version: Version | str, include_prerelease: bool = False) -> bool:
        if isinstance(version, str):
            version = Version.parse(version)
        for comps in self.sets:
            if not all(_test(op, version, bound) for op, bound in comps):
                continue
            if version.prerelease and not include_prerelease:
                # Prereleases only match if a comparator in the same set has a prerelease on the same tuple.
                if not any(b.prerelease and (b.major, b.minor, b.patch) == (version.major, version.minor, version.patch)
                           for _, b in comps):
                    continue
            return True
        return False


def satisfies(version: Version | str, range_text: str, include_prerelease: bool = False) -> bool:
    return Range(range_text).contains(version, include_prerelease)


def max_satisfying(versions, range_text: str):
    r = Range(range_text)
    ok = [Version.parse(v) if isinstance(v, str) else v for v in versions]
    ok = [v for v in ok if r.contains(v)]
    return max(ok) if ok else None

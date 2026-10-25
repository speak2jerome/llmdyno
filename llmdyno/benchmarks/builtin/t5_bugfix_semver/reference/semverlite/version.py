"""Semantic version parsing and precedence (https://semver.org)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import total_ordering

_SEMVER = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


class InvalidVersion(ValueError):
    pass


def _pre_key(pre):
    # numeric identifiers sort numerically and below alphanumeric ones (semver 11.4)
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre)


@total_ordering
@dataclass(frozen=True, eq=False)
class Version:
    major: int
    minor: int
    patch: int
    prerelease: tuple = field(default_factory=tuple)
    build: tuple = field(default_factory=tuple)

    @classmethod
    def parse(cls, text: str) -> "Version":
        m = _SEMVER.match(text.strip())
        if not m:
            raise InvalidVersion(f"invalid version: {text!r}")
        pre = tuple(m.group("pre").split(".")) if m.group("pre") else ()
        for ident in pre:
            if ident.isdigit() and len(ident) > 1 and ident.startswith("0"):
                raise InvalidVersion(f"numeric prerelease identifier has leading zero: {text!r}")
        build = tuple(m.group("build").split(".")) if m.group("build") else ()
        return cls(int(m.group("major")), int(m.group("minor")), int(m.group("patch")), pre, build)

    def __str__(self) -> str:
        s = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            s += "-" + ".".join(self.prerelease)
        if self.build:
            s += "+" + ".".join(self.build)
        return s

    @property
    def is_prerelease(self) -> bool:
        return bool(self.prerelease)

    def _key(self):
        pre_key = (1,) if not self.prerelease else (0, _pre_key(self.prerelease))
        return (self.major, self.minor, self.patch, pre_key)

    def __eq__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() == other._key()

    def __lt__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() < other._key()

    def __hash__(self):
        return hash(self._key())

    def bump_major(self) -> "Version":
        return Version(self.major + 1, 0, 0)

    def bump_minor(self) -> "Version":
        return Version(self.major, self.minor + 1, 0)

    def bump_patch(self) -> "Version":
        if self.prerelease:
            return Version(self.major, self.minor, self.patch)
        return Version(self.major, self.minor, self.patch + 1)


def parse(text: str) -> Version:
    return Version.parse(text)

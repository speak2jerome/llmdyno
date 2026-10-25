import random

import pytest

from semverlite import InvalidVersion, Version, max_satisfying, parse, satisfies

SPEC_CHAIN = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2",
              "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0"]


# ---- #12 prerelease precedence ----
def test_issue12_spec_chain_strictly_increasing():
    vs = [parse(v) for v in SPEC_CHAIN]
    for a, b in zip(vs, vs[1:]):
        assert a < b, (str(a), str(b))


def test_issue12_sorting_shuffled():
    vs = [parse(v) for v in SPEC_CHAIN]
    shuffled = vs[:]
    random.Random(7).shuffle(shuffled)
    assert [str(v) for v in sorted(shuffled)] == SPEC_CHAIN


def test_issue12_numeric_identifiers_numeric():
    assert parse("1.0.0-rc.2") < parse("1.0.0-rc.10")
    assert parse("1.0.0-2") < parse("1.0.0-11")


def test_issue12_numeric_lower_than_alphanumeric():
    assert parse("1.0.0-999") < parse("1.0.0-alpha")
    assert parse("1.0.0-alpha.99") < parse("1.0.0-alpha.beta")


def test_issue12_max_and_ranges_use_new_order():
    assert max([parse("2.0.0-rc.2"), parse("2.0.0-rc.10"), parse("2.0.0-rc.9")]) == parse("2.0.0-rc.10")
    assert satisfies("1.2.3-rc.10", ">1.2.3-rc.2")


# ---- #15 build metadata ignored for precedence ----
def test_issue15_equal_ignoring_build():
    assert parse("1.0.0+build.1") == parse("1.0.0+build.2")
    assert parse("1.0.0+abc") == parse("1.0.0")


def test_issue15_hash_consistent():
    assert hash(parse("1.0.0+build.1")) == hash(parse("1.0.0+build.2"))
    assert len({parse("1.0.0+a"), parse("1.0.0+b"), parse("1.0.0")}) == 1


def test_issue15_ordering_ignores_build():
    a, b = parse("1.0.0-rc.1+zzz"), parse("1.0.0-rc.1+aaa")
    assert not a < b and not b < a
    assert parse("1.0.0+zzz") < parse("1.0.1+aaa")


def test_issue15_str_keeps_build():
    assert str(parse("1.0.0+build.7")) == "1.0.0+build.7"


# ---- #17 caret on 0.x ----
@pytest.mark.parametrize("version,rng,expected", [
    ("0.2.3", "^0.2.3", True),
    ("0.2.9", "^0.2.3", True),
    ("0.3.0", "^0.2.3", False),
    ("0.2.2", "^0.2.3", False),
    ("0.0.3", "^0.0.3", True),
    ("0.0.4", "^0.0.3", False),
    ("0.2.9", "^0.2", True),
    ("0.3.0", "^0.2", False),
    ("0.0.9", "^0.0", True),
    ("0.1.0", "^0.0", False),
    ("0.9.9", "^0", True),
    ("1.0.0", "^0", False),
    ("1.9.9", "^1.2.3", True),
    ("2.0.0", "^1.2.3", False),
    ("0.2.3-beta.2", "^0.2.3-beta.1", True),
    ("0.3.0", "^0.2.3-beta.1", False),
])
def test_issue17_caret(version, rng, expected):
    assert satisfies(version, rng) is expected


def test_issue17_max_satisfying():
    assert max_satisfying(["0.2.3", "0.2.9", "0.3.1", "1.0.0"], "^0.2.3") == Version(0, 2, 9)


# ---- regressions: behaviour that must not change ----
@pytest.mark.parametrize("version,rng,expected", [
    ("1.2.3", "~1.2", True), ("1.3.0", "~1.2", False), ("0.2.5", "~0.2.3", True), ("0.3.0", "~0.2.3", False),
    ("1.5.0", "1.x", True), ("2.0.0", "1.x", False), ("5.0.0", "*", True),
    ("2.3.9", "1.2 - 2.3", True), ("2.4.0", "1.2 - 2.3", False),
    ("1.2.3", ">=1.0.0 <1.2.3", False), ("1.2.2", ">=1.0.0 <1.2.3", True),
    ("1.2.3-alpha", "*", False), ("3.0.0", "<2.0.0 || >=3.0.0", True), ("2.5.0", "<2.0.0 || >=3.0.0", False),
])
def test_regression_ranges(version, rng, expected):
    assert satisfies(version, rng) is expected


def test_regression_parse_invalid():
    for bad in ("1.2.3-01", "1.02.3", "1.2"):
        with pytest.raises(InvalidVersion):
            parse(bad)


def test_regression_release_beats_prerelease():
    assert parse("1.0.0-rc.99") < parse("1.0.0") < parse("1.0.1-alpha")

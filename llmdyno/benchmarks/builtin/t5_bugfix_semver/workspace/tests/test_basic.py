import pytest

from semverlite import InvalidRange, InvalidVersion, Version, max_satisfying, parse, satisfies


def test_parse_and_str():
    v = parse("1.2.3-beta.1+exp.sha.5114f85")
    assert (v.major, v.minor, v.patch) == (1, 2, 3)
    assert v.prerelease == ("beta", "1")
    assert str(v) == "1.2.3-beta.1+exp.sha.5114f85"
    assert str(parse("v2.0.0")) == "2.0.0"


@pytest.mark.parametrize("bad", ["1.2", "01.2.3", "1.2.3-", "1.2.3-01", "a.b.c", ""])
def test_invalid_versions(bad):
    with pytest.raises(InvalidVersion):
        parse(bad)


def test_basic_ordering():
    assert parse("1.2.3") < parse("1.2.4") < parse("1.3.0") < parse("2.0.0")
    assert parse("1.0.0-alpha") < parse("1.0.0")
    assert parse("1.0.0-alpha") < parse("1.0.0-beta")


def test_bumps():
    v = parse("1.2.3")
    assert str(v.bump_patch()) == "1.2.4"
    assert str(v.bump_minor()) == "1.3.0"
    assert str(v.bump_major()) == "2.0.0"
    assert str(parse("1.2.3-rc.1").bump_patch()) == "1.2.3"


@pytest.mark.parametrize("version,rng,expected", [
    ("1.2.3", ">=1.2.0", True),
    ("1.2.3", ">1.2.3", False),
    ("1.2.3", "^1.0.0", True),
    ("2.0.0", "^1.0.0", False),
    ("1.2.9", "~1.2.3", True),
    ("1.3.0", "~1.2.3", False),
    ("1.2.7", "1.2.x", True),
    ("1.3.0", "1.2.x", False),
    ("2.3.4", "1.2.3 - 2.3.4", True),
    ("2.3.5", "1.2.3 - 2.3.4", False),
    ("3.1.0", "^1.0.0 || ^3.0.0", True),
    ("1.2.3-beta.1", "^1.0.0", False),
    ("1.2.3-beta.2", ">=1.2.3-beta.1", True),
])
def test_satisfies(version, rng, expected):
    assert satisfies(version, rng) is expected


def test_max_satisfying():
    assert max_satisfying(["1.2.3", "1.4.0", "2.0.0"], "^1.2.0") == Version(1, 4, 0)
    assert max_satisfying(["1.2.3"], "^2.0.0") is None


def test_invalid_range():
    with pytest.raises(InvalidRange):
        satisfies("1.0.0", ">=banana")

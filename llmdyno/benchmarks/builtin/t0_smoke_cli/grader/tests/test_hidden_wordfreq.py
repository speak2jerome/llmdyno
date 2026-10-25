import subprocess
import sys

import wordfreq


def test_basic_counts():
    assert wordfreq.top_words("b a b c b a", 2) == [("b", 3), ("a", 2)]


def test_case_and_apostrophes():
    assert wordfreq.top_words("Don't stop. don't STOP don't", 2) == [("don't", 3), ("stop", 2)]


def test_ties_alphabetical():
    assert wordfreq.top_words("pear apple pear apple fig", 3) == [("apple", 2), ("pear", 2), ("fig", 1)]


def test_default_and_nonpositive():
    assert len(wordfreq.top_words("a b c d e")) == 3
    assert wordfreq.top_words("a b", 0) == []


def test_punctuation_and_digits_separate():
    assert wordfreq.top_words("x1x, x;x 2", 5) == [("x", 4)]


def test_cli_output(tmp_path):
    f = tmp_path / "t.txt"
    f.write_text("one two two three three three")
    out = subprocess.run([sys.executable, "wordfreq.py", str(f), "-n", "2"], capture_output=True, text=True)
    assert out.returncode == 0
    assert out.stdout.strip().splitlines() == ["three\t3", "two\t2"]


def test_cli_missing_file(tmp_path):
    out = subprocess.run([sys.executable, "wordfreq.py", str(tmp_path / "nope.txt")], capture_output=True, text=True)
    assert out.returncode == 1
    assert out.stderr.strip()

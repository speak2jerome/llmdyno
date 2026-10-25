"""Beyond-spec robustness probes for the inventory CLI: bad input must give a clean error, never a traceback."""
import subprocess
import sys


def cli(db, *args):
    return subprocess.run([sys.executable, "-m", "inventory", "--db", str(db), *map(str, args)],
                          capture_output=True, text=True, timeout=60)


def clean_failure(r):
    return r.returncode != 0 and "Traceback" not in r.stderr


def test_non_numeric_qty_is_clean_error(tmp_path):
    assert clean_failure(cli(tmp_path / "inv", "add", "A1", "Widget", "lots", "1.50"))


def test_non_numeric_price_is_clean_error(tmp_path):
    assert clean_failure(cli(tmp_path / "inv", "add", "A1", "Widget", "3", "cheap"))


def test_unknown_command_is_clean_error(tmp_path):
    assert clean_failure(cli(tmp_path / "inv", "explode"))


def test_insufficient_stock_has_no_traceback(tmp_path):
    db = tmp_path / "inv"
    cli(db, "add", "A1", "Widget", 1, 2)
    assert clean_failure(cli(db, "adjust", "A1", "-5", "--reason", "sale"))


def test_corrupt_database_is_clean_error(tmp_path):
    db = tmp_path / "inv"
    db.write_bytes(b"\x00\x01 definitely not a database or json \xff")
    assert clean_failure(cli(db, "list"))


def test_unicode_round_trip(tmp_path):
    db = tmp_path / "inv"
    assert cli(db, "add", "Ä1", "Café crème", 2, 3.5).returncode == 0
    assert "Café crème" in cli(db, "list").stdout


def test_missing_db_argument_is_clean_error(tmp_path):
    r = subprocess.run([sys.executable, "-m", "inventory", "list"], capture_output=True, text=True, timeout=60, cwd=tmp_path)
    assert clean_failure(r)

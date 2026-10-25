import json
from decimal import Decimal

import pytest
from helpers import cli, lines

from inventory.errors import InventoryError
from inventory.models import Item, Movement
from inventory.store import InventoryStore


def test_price_is_decimal_quantized():
    assert Item("A", "x", 1, 1.005).price == Decimal("1.01")
    assert Item("A", "x", 1, "2.5").price == Decimal("2.50")
    assert Item("A", "x", 1, 3).price == Decimal("3.00")
    assert isinstance(Item("A", "x", 1, 0.1).price, Decimal)


def test_total_value_decimal(tmp_path):
    s = InventoryStore(tmp_path / "inv")
    s.add_item(Item("A1", "x", 3, 0.1))
    s.add_item(Item("B2", "y", 7, 0.15))
    total = s.total_value()
    assert isinstance(total, Decimal) and total == Decimal("1.35")
    assert str(total) == "1.35"


def test_prices_roundtrip_storage(tmp_path):
    InventoryStore(tmp_path / "inv").add_item(Item("A1", "x", 1, 0.1))
    assert InventoryStore(tmp_path / "inv").get("A1").price == Decimal("0.10")


def test_report_json_strings(tmp_path):
    db = tmp_path / "inv"
    cli(db, "add", "A1", "Thing", 3, 0.1)
    data = json.loads(cli(db, "report", "--format", "json").stdout)
    item = data["items"][0]
    assert item["price"] == "0.10" and item["value"] == "0.30" and data["total_value"] == "0.30"


def test_report_csv_no_float_noise(tmp_path):
    db = tmp_path / "inv"
    cli(db, "add", "A1", "Thing", 3, 0.1)
    assert lines(cli(db, "report", "--format", "csv"))[1] == "A1,Thing,3,0.10,0.30"


def mk(tmp_path):
    s = InventoryStore(tmp_path / "inv")
    s.add_item(Item("A1", "Widget", 5, 1))
    s.add_item(Item("B2", "Bolt", 10, 1))
    return s


def test_undo_last_overall(tmp_path):
    s = mk(tmp_path)
    s.adjust("A1", -2, "sale")
    s.adjust("B2", 3, "restock")
    mv = s.undo_last_adjustment()
    assert isinstance(mv, Movement) and (mv.sku, mv.delta, mv.reason) == ("B2", -3, "undo: restock")
    assert s.get("B2").qty == 10 and s.history()[-1].reason == "undo: restock"


def test_undo_for_sku(tmp_path):
    s = mk(tmp_path)
    s.adjust("A1", -2, "sale")
    s.adjust("B2", 3, "restock")
    mv = s.undo_last_adjustment("A1")
    assert (mv.sku, mv.delta, mv.reason) == ("A1", 2, "undo: sale")
    assert s.get("A1").qty == 5 and s.get("B2").qty == 13


def test_cannot_undo_initial_or_undo_or_nothing(tmp_path):
    s = mk(tmp_path)
    with pytest.raises(InventoryError):
        s.undo_last_adjustment()  # last movement is B2 initial
    s.adjust("A1", 1, "found")
    s.undo_last_adjustment()
    with pytest.raises(InventoryError):
        s.undo_last_adjustment()  # last movement is an undo
    assert s.get("A1").qty == 5
    empty = InventoryStore(tmp_path / "empty")
    with pytest.raises(InventoryError):
        empty.undo_last_adjustment()


def test_undo_persists(tmp_path):
    s = mk(tmp_path)
    s.adjust("A1", -4, "sale")
    s.undo_last_adjustment("A1")
    again = InventoryStore(tmp_path / "inv")
    assert again.get("A1").qty == 5 and again.history("A1")[-1].reason == "undo: sale"


def test_cli_undo(tmp_path):
    db = tmp_path / "inv"
    cli(db, "add", "A1", "Widget", 5, 1)
    cli(db, "adjust", "A1", "-2", "--reason", "sale")
    r = cli(db, "undo", "A1")
    assert r.returncode == 0
    parts = lines(r)[-1].split("\t")
    assert parts[1:] == ["A1", "2", "undo: sale"]
    assert cli(db, "undo", "A1").returncode == 1

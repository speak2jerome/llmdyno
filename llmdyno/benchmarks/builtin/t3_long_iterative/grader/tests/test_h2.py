from datetime import datetime

import pytest
from helpers import cli, lines

from inventory.errors import InsufficientStock, InventoryError, UnknownSku
from inventory.models import Item, Movement
from inventory.store import InventoryStore


def mk(tmp_path):
    s = InventoryStore(tmp_path / "inv")
    s.add_item(Item("A1", "Widget", 5, 2.5))
    s.add_item(Item("B2", "Bolt", 0, 0.5))
    return s


def test_adjust_returns_updated_item(tmp_path):
    item = mk(tmp_path).adjust("A1", 3, "restock")
    assert item.sku == "A1" and item.qty == 8


def test_adjust_unknown(tmp_path):
    with pytest.raises(UnknownSku):
        mk(tmp_path).adjust("ZZ", 1, "x")


def test_insufficient_changes_nothing(tmp_path):
    s = mk(tmp_path)
    assert issubclass(InsufficientStock, InventoryError)
    before = len(s.history())
    with pytest.raises(InsufficientStock):
        s.adjust("A1", -6, "sale")
    assert s.get("A1").qty == 5 and len(s.history()) == before


def test_initial_movement_only_when_positive(tmp_path):
    s = mk(tmp_path)
    assert [(m.sku, m.delta, m.reason) for m in s.history()] == [("A1", 5, "initial")]


def test_history_order_and_filter(tmp_path):
    s = mk(tmp_path)
    s.adjust("B2", 4, "restock")
    s.adjust("A1", -1, "sale")
    s.adjust("B2", -2, "sale")
    assert [(m.sku, m.delta) for m in s.history()] == [("A1", 5), ("B2", 4), ("A1", -1), ("B2", -2)]
    assert [m.delta for m in s.history("B2")] == [4, -2]
    assert all(isinstance(m, Movement) for m in s.history())


def test_timestamps_iso(tmp_path):
    s = mk(tmp_path)
    s.adjust("A1", 1, "x")
    for m in s.history():
        datetime.fromisoformat(m.timestamp.replace("Z", "+00:00"))


def test_history_persists(tmp_path):
    s = mk(tmp_path)
    s.adjust("A1", -2, "sale")
    again = InventoryStore(tmp_path / "inv")
    assert [(m.sku, m.delta, m.reason) for m in again.history()] == [("A1", 5, "initial"), ("A1", -2, "sale")]
    assert again.get("A1").qty == 3


def test_cli_adjust_and_history(tmp_path):
    db = tmp_path / "inv"
    cli(db, "add", "A1", "Widget", 5, 2.5)
    r = cli(db, "adjust", "A1", "-3", "--reason", "sale")
    assert r.returncode == 0
    assert lines(cli(db, "list")) == ["A1\tWidget\t2\t2.50"]
    hist = [l.split("\t") for l in lines(cli(db, "history", "A1"))]
    assert [(h[1], h[2], h[3]) for h in hist] == [("A1", "5", "initial"), ("A1", "-3", "sale")]
    r = cli(db, "adjust", "A1", "-10", "--reason", "sale")
    assert r.returncode == 1

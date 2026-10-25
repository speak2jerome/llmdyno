import pytest
from helpers import cli, lines

from inventory.errors import DuplicateSku, InventoryError, UnknownSku
from inventory.models import Item
from inventory.store import InventoryStore


def test_list_sorted_by_sku(tmp_path):
    s = InventoryStore(tmp_path / "inv")
    for sku in ("C3", "A1", "B2"):
        s.add_item(Item(sku, f"n{sku}", 1, 1.5))
    assert [i.sku for i in s.list_items()] == ["A1", "B2", "C3"]


def test_persists_across_instances(tmp_path):
    p = tmp_path / "inv"
    InventoryStore(p).add_item(Item("A1", "Widget", 5, 2.5))
    item = InventoryStore(p).get("A1")
    assert (item.sku, item.name, item.qty, float(item.price)) == ("A1", "Widget", 5, 2.5)


def test_get_unknown(tmp_path):
    with pytest.raises(UnknownSku):
        InventoryStore(tmp_path / "inv").get("X")


def test_remove(tmp_path):
    s = InventoryStore(tmp_path / "inv")
    s.add_item(Item("A1", "Widget", 5, 2.5))
    s.remove_item("A1")
    with pytest.raises(UnknownSku):
        s.get("A1")
    assert s.list_items() == []


def test_error_hierarchy():
    assert issubclass(DuplicateSku, InventoryError) and issubclass(UnknownSku, InventoryError)
    assert issubclass(InventoryError, Exception)


def test_cli_add_list_remove(tmp_path):
    db = tmp_path / "inv"
    assert cli(db, "add", "B2", "Bolt", 10, 0.25).returncode == 0
    assert cli(db, "add", "A1", "Anchor", 3, 4).returncode == 0
    assert lines(cli(db, "list")) == ["A1\tAnchor\t3\t4.00", "B2\tBolt\t10\t0.25"]
    assert cli(db, "remove", "A1").returncode == 0
    assert lines(cli(db, "list")) == ["B2\tBolt\t10\t0.25"]


def test_cli_errors_exit_1(tmp_path):
    db = tmp_path / "inv"
    r = cli(db, "remove", "NOPE")
    assert r.returncode == 1 and r.stderr.strip()
    cli(db, "add", "A1", "Anchor", 3, 4)
    r = cli(db, "add", "A1", "Again", 1, 1)
    assert r.returncode == 1 and r.stderr.strip()

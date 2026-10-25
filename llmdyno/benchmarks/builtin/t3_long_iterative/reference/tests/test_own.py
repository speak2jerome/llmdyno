from inventory.models import Item
from inventory.store import InventoryStore


def test_own_1(tmp_path):
    s = InventoryStore(tmp_path / "x")
    s.add_item(Item("A", "a", 1, 1))
    assert s.get("A").qty == 1


def test_own_2(tmp_path):
    assert InventoryStore(tmp_path / "x").list_items() == []


def test_own_3(tmp_path):
    assert InventoryStore(tmp_path / "x").search("q") == []


def test_own_4(tmp_path):
    assert InventoryStore(tmp_path / "x").low_stock(1) == []


def test_own_5(tmp_path):
    assert InventoryStore(tmp_path / "x").history() == []

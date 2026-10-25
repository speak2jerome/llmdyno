from inventory.models import Item
from inventory.store import InventoryStore


def make(tmp_path):
    store = InventoryStore(tmp_path / "inv.json")
    store.add_item(Item("A1", "Blue Widget", 3, 2.25))
    store.add_item(Item("B2", "Bolt", 40, 0.5))
    store.add_item(Item("C3", "widget stand", 1, 10.5))
    return store


def test_search_case_insensitive(tmp_path):
    assert [i.sku for i in make(tmp_path).search("WIDGET")] == ["A1", "C3"]


def test_low_stock_order(tmp_path):
    assert [i.sku for i in make(tmp_path).low_stock(3)] == ["C3", "A1"]


def test_total_value(tmp_path):
    assert float(make(tmp_path).total_value()) == 37.25

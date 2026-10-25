import pytest

from inventory.errors import InsufficientStock
from inventory.models import Item
from inventory.store import InventoryStore


def test_adjust_and_history(tmp_path):
    store = InventoryStore(tmp_path / "inv.json")
    store.add_item(Item("A1", "Widget", 5, 2.5))
    store.adjust("A1", -2, "sale")
    assert store.get("A1").qty == 3
    reasons = [(m.reason, m.delta) for m in store.history("A1")]
    assert reasons == [("initial", 5), ("sale", -2)]


def test_insufficient_stock(tmp_path):
    store = InventoryStore(tmp_path / "inv.json")
    store.add_item(Item("A1", "Widget", 1, 2.5))
    with pytest.raises(InsufficientStock):
        store.adjust("A1", -2, "sale")
    assert store.get("A1").qty == 1

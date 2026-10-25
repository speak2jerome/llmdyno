from decimal import Decimal

import pytest

from inventory.errors import InventoryError
from inventory.models import Item
from inventory.store import InventoryStore


def test_decimal_total(tmp_path):
    store = InventoryStore(tmp_path / "inv.db")
    store.add_item(Item("A1", "Widget", 3, 0.1))
    assert store.total_value() == Decimal("0.30")


def test_undo(tmp_path):
    store = InventoryStore(tmp_path / "inv.db")
    store.add_item(Item("A1", "Widget", 5, 1))
    store.adjust("A1", -2, "sale")
    mv = store.undo_last_adjustment()
    assert (mv.delta, mv.reason) == (2, "undo: sale")
    assert store.get("A1").qty == 5
    with pytest.raises(InventoryError):
        store.undo_last_adjustment()

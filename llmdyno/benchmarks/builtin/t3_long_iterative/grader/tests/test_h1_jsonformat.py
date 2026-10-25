import json

from inventory.models import Item
from inventory.store import InventoryStore


def test_json_file_format(tmp_path):
    p = tmp_path / "inv.json"
    InventoryStore(p).add_item(Item("A1", "Widget", 5, 2.5))
    data = json.loads(p.read_text())
    assert data["items"] == [{"sku": "A1", "name": "Widget", "qty": 5, "price": 2.5}]

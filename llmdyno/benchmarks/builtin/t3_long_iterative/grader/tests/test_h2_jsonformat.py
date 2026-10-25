import json

from inventory.models import Item
from inventory.store import InventoryStore


def test_history_in_json_file(tmp_path):
    p = tmp_path / "inv.json"
    s = InventoryStore(p)
    s.add_item(Item("A1", "Widget", 5, 2.5))
    s.adjust("A1", -1, "sale")
    hist = json.loads(p.read_text())["history"]
    assert [(h["sku"], h["delta"], h["reason"]) for h in hist] == [("A1", 5, "initial"), ("A1", -1, "sale")]
    assert all("timestamp" in h for h in hist)

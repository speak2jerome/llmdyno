import json
import shutil
from pathlib import Path

from helpers import cli, lines

from inventory.models import Item
from inventory.store import InventoryStore

LEGACY = {
    "items": [
        {"sku": "K9", "name": "Kettle", "qty": 4, "price": 19.5},
        {"sku": "M1", "name": "Mug", "qty": 12, "price": 3.25},
        {"sku": "P5", "name": "Plate", "qty": 0, "price": 6.0},
    ],
    "history": [
        {"sku": "M1", "delta": 10, "reason": "initial", "timestamp": "2026-01-02T09:00:00"},
        {"sku": "K9", "delta": 5, "reason": "initial", "timestamp": "2026-01-02T09:05:00"},
        {"sku": "M1", "delta": 2, "reason": "restock", "timestamp": "2026-01-03T10:00:00"},
        {"sku": "K9", "delta": -1, "reason": "sale", "timestamp": "2026-01-04T11:30:00"},
    ],
}


def is_sqlite(path):
    return Path(path).read_bytes()[:16] == b"SQLite format 3\x00"


def legacy(tmp_path):
    p = tmp_path / "store.json"
    p.write_text(json.dumps(LEGACY))
    return p


def test_new_file_is_sqlite(tmp_path):
    p = tmp_path / "fresh"
    s = InventoryStore(p)
    s.add_item(Item("A1", "Widget", 2, 2.5))
    s.adjust("A1", 1, "restock")
    assert is_sqlite(p)
    again = InventoryStore(p)
    assert again.get("A1").qty == 3 and len(again.history()) == 2


def test_migration_preserves_items(tmp_path):
    s = InventoryStore(legacy(tmp_path))
    got = [(i.sku, i.name, i.qty, float(i.price)) for i in s.list_items()]
    assert got == [("K9", "Kettle", 4, 19.5), ("M1", "Mug", 12, 3.25), ("P5", "Plate", 0, 6.0)]


def test_migration_preserves_history_and_timestamps(tmp_path):
    s = InventoryStore(legacy(tmp_path))
    got = [(m.sku, m.delta, m.reason, m.timestamp) for m in s.history()]
    want = [(h["sku"], h["delta"], h["reason"], h["timestamp"]) for h in LEGACY["history"]]
    assert got == want


def test_backup_and_sqlite_after_migration(tmp_path):
    p = legacy(tmp_path)
    original = p.read_text()
    InventoryStore(p)
    assert is_sqlite(p)
    bak = Path(str(p) + ".json.bak")
    assert bak.exists() and json.loads(bak.read_text()) == json.loads(original)


def test_no_double_migration(tmp_path):
    p = legacy(tmp_path)
    InventoryStore(p)
    s = InventoryStore(p)
    assert len(s.list_items()) == 3 and len(s.history()) == 4


def test_after_migration_changes_persist(tmp_path):
    p = legacy(tmp_path)
    InventoryStore(p).adjust("K9", -2, "sale")
    s = InventoryStore(p)
    assert s.get("K9").qty == 2 and s.history("K9")[-1].reason == "sale"


def test_cli_on_legacy_file(tmp_path):
    p = legacy(tmp_path)
    out = lines(cli(p, "list"))
    assert out == ["K9\tKettle\t4\t19.50", "M1\tMug\t12\t3.25", "P5\tPlate\t0\t6.00"]
    assert is_sqlite(p)

import shutil
from pathlib import Path

from inventory.models import Item
from inventory.store import InventoryStore

LEGACY = Path(__file__).parent / "data" / "legacy.json"


def is_sqlite(path):
    return Path(path).read_bytes()[:16] == b"SQLite format 3\x00"


def test_new_store_is_sqlite(tmp_path):
    path = tmp_path / "inv.db"
    InventoryStore(path).add_item(Item("A1", "Widget", 1, 2.5))
    assert is_sqlite(path)


def test_migrates_legacy_json(tmp_path):
    path = tmp_path / "legacy.json"
    shutil.copy(LEGACY, path)
    store = InventoryStore(path)
    assert [i.sku for i in store.list_items()] == ["K9", "M1"]
    assert len(store.history()) == 4
    assert is_sqlite(path)
    assert Path(str(path) + ".json.bak").exists()

import subprocess
import sys

import pytest

from inventory.errors import DuplicateSku, UnknownSku
from inventory.models import Item
from inventory.store import InventoryStore


def test_add_and_get(tmp_path):
    store = InventoryStore(tmp_path / "inv.json")
    store.add_item(Item("A1", "Widget", 5, 2.5))
    assert store.get("A1").name == "Widget"


def test_duplicate_rejected(tmp_path):
    store = InventoryStore(tmp_path / "inv.json")
    store.add_item(Item("A1", "Widget", 5, 2.5))
    with pytest.raises(DuplicateSku):
        store.add_item(Item("A1", "Other", 1, 1.0))


def test_remove_unknown(tmp_path):
    with pytest.raises(UnknownSku):
        InventoryStore(tmp_path / "inv.json").remove_item("NOPE")


def test_cli_list(tmp_path):
    db = str(tmp_path / "inv.json")
    run = lambda *a: subprocess.run([sys.executable, "-m", "inventory", "--db", db, *a], capture_output=True, text=True)
    assert run("add", "B2", "Bolt", "10", "0.25").returncode == 0
    out = run("list").stdout.strip()
    assert out == "B2\tBolt\t10\t0.25"

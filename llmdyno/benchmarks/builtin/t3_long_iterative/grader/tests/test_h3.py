import json

import pytest
from helpers import cli, lines

from inventory.models import Item
from inventory.store import InventoryStore


def mk(tmp_path):
    s = InventoryStore(tmp_path / "inv")
    s.add_item(Item("A1", "Blue Widget", 3, 2.25))
    s.add_item(Item("B2", "Bolt", 40, 0.5))
    s.add_item(Item("C3", "widget stand", 1, 10.5))
    s.add_item(Item("WX9", "Gasket", 1, 0.75))
    return s


def test_search_name_case_insensitive(tmp_path):
    s = mk(tmp_path)
    assert [i.sku for i in s.search("widget")] == ["A1", "C3"]


def test_search_sku_match(tmp_path):
    s = mk(tmp_path)
    assert [i.sku for i in s.search("wx")] == ["WX9"]
    assert [i.sku for i in s.search("bOlT")] == ["B2"]
    assert s.search("nothing-here") == []


def test_low_stock_ties_by_sku(tmp_path):
    s = mk(tmp_path)
    assert [i.sku for i in s.low_stock(3)] == ["C3", "WX9", "A1"]
    assert s.low_stock(0) == []


def test_total_value_rounded(tmp_path):
    s = InventoryStore(tmp_path / "inv")
    s.add_item(Item("A1", "x", 3, 0.1))
    assert float(s.total_value()) == pytest.approx(0.3, abs=1e-12)
    assert len(str(float(s.total_value()))) <= 4


def test_cli_search(tmp_path):
    db = tmp_path / "inv"
    cli(db, "add", "A1", "Blue Widget", 3, 2.25)
    cli(db, "add", "B2", "Bolt", 40, 0.5)
    assert lines(cli(db, "search", "WIDGET")) == ["A1\tBlue Widget\t3\t2.25"]


def test_cli_report_json(tmp_path):
    db = tmp_path / "inv"
    cli(db, "add", "B2", "Bolt", 40, 0.5)
    cli(db, "add", "A1", "Blue Widget", 3, 2.25)
    data = json.loads(cli(db, "report", "--format", "json").stdout)
    assert [i["sku"] for i in data["items"]] == ["A1", "B2"]
    first = data["items"][0]
    assert set(first) >= {"sku", "name", "qty", "price", "value"}
    assert float(first["value"]) == 6.75 and float(first["price"]) == 2.25
    assert float(data["total_value"]) == 26.75


def test_cli_report_csv(tmp_path):
    db = tmp_path / "inv"
    cli(db, "add", "B2", "Bolt", 40, 0.5)
    cli(db, "add", "A1", "Blue Widget", 3, 2.25)
    out = lines(cli(db, "report", "--format", "csv"))
    assert out == ["sku,name,qty,price,value", "A1,Blue Widget,3,2.25,6.75", "B2,Bolt,40,0.50,20.00"]

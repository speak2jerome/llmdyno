import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal

from ._mode import BACKEND, USE_DECIMAL
from .errors import DuplicateSku, InsufficientStock, InventoryError, UnknownSku
from .models import Item, Movement, money


def now():
    return datetime.now(timezone.utc).isoformat()


class InventoryStore:
    def __init__(self, path):
        self.path = str(path)
        self.items, self.hist = {}, []
        if BACKEND == "json":
            if os.path.exists(self.path):
                data = json.load(open(self.path))
                self.items = {d["sku"]: Item(**d) for d in data.get("items", [])}
                self.hist = [Movement(**h) for h in data.get("history", [])]
            else:
                self._save()
        else:
            if os.path.exists(self.path) and open(self.path, "rb").read(16) != b"SQLite format 3\x00":
                data = json.load(open(self.path))
                shutil.copy(self.path, self.path + ".json.bak")
                os.remove(self.path)
                self._con()
                self.items = {d["sku"]: Item(**d) for d in data.get("items", [])}
                self.hist = [Movement(**h) for h in data.get("history", [])]
                self._save()
            else:
                con = self._con()
                self.items = {r[0]: Item(*r) for r in con.execute("SELECT sku,name,qty,price FROM items")}
                self.hist = [Movement(*r) for r in con.execute("SELECT sku,delta,reason,ts FROM history ORDER BY id")]

    def _con(self):
        con = sqlite3.connect(self.path)
        con.execute("CREATE TABLE IF NOT EXISTS items (sku TEXT PRIMARY KEY, name TEXT, qty INTEGER, price TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY, sku TEXT, delta INTEGER, reason TEXT, ts TEXT)")
        return con

    def _save(self):
        if BACKEND == "json":
            data = {"items": [{"sku": i.sku, "name": i.name, "qty": i.qty, "price": float(i.price)} for i in self.list_items()],
                    "history": [m.__dict__ for m in self.hist]}
            json.dump(data, open(self.path, "w"))
            return
        con = self._con()
        con.execute("DELETE FROM items")
        con.execute("DELETE FROM history")
        con.executemany("INSERT INTO items VALUES (?,?,?,?)", [(i.sku, i.name, i.qty, str(i.price)) for i in self.items.values()])
        con.executemany("INSERT INTO history (sku,delta,reason,ts) VALUES (?,?,?,?)",
                        [(m.sku, m.delta, m.reason, m.timestamp) for m in self.hist])
        con.commit()
        con.close()

    def add_item(self, item):
        if item.sku in self.items:
            raise DuplicateSku(item.sku)
        self.items[item.sku] = item
        if item.qty > 0:
            self.hist.append(Movement(item.sku, item.qty, "initial", now()))
        self._save()

    def remove_item(self, sku):
        self.get(sku)
        del self.items[sku]
        self._save()

    def get(self, sku):
        if sku not in self.items:
            raise UnknownSku(sku)
        return self.items[sku]

    def list_items(self):
        return [self.items[k] for k in sorted(self.items)]

    def adjust(self, sku, delta, reason):
        item = self.get(sku)
        if item.qty + delta < 0:
            raise InsufficientStock(sku)
        item.qty += delta
        self.hist.append(Movement(sku, delta, reason, now()))
        self._save()
        return item

    def history(self, sku=None):
        return [m for m in self.hist if sku is None or m.sku == sku]

    def search(self, q):
        q = q.lower()
        return [i for i in self.list_items() if q in i.sku.lower() or q in i.name.lower()]

    def low_stock(self, threshold):
        return sorted([i for i in self.items.values() if i.qty <= threshold], key=lambda i: (i.qty, i.sku))

    def total_value(self):
        if USE_DECIMAL:
            return money(sum((i.price * i.qty for i in self.items.values()), Decimal("0")))
        return round(sum(i.qty * i.price for i in self.items.values()), 2)

    def undo_last_adjustment(self, sku=None):
        hist = self.history(sku)
        if not hist or hist[-1].reason == "initial" or hist[-1].reason.startswith("undo: "):
            raise InventoryError("nothing to undo")
        last = hist[-1]
        self.adjust(last.sku, -last.delta, f"undo: {last.reason}")
        return self.hist[-1]

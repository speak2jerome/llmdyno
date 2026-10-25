## Step 2: stock movements

- `models.py`: add dataclass `Movement(sku: str, delta: int, reason: str, timestamp: str)`. The timestamp is an ISO-8601 string.
- `InventoryStore.adjust(sku, delta: int, reason: str) -> Item`: change the quantity by `delta` and return the updated item.
  - Unknown SKU: raise `UnknownSku`.
  - If the result would be negative, raise `InsufficientStock` (a new subclass of `InventoryError` in `errors.py`) and change nothing.
  - Every successful adjustment is appended to the movement history.
- `add_item` records an initial movement with reason `"initial"` and delta equal to the item's qty, but only if qty > 0.
- `InventoryStore.history(sku=None) -> list[Movement]`: movements in chronological order, optionally filtered by SKU.
- Store the history in the same JSON file under the key `"history"`, as a list of `{"sku", "delta", "reason", "timestamp"}`.
- CLI:
  - `adjust SKU DELTA --reason TEXT` (`DELTA` may be negative, e.g. `adjust A1 -3 --reason sale`)
  - `history [SKU]`: prints one line per movement as `TIMESTAMP<TAB>SKU<TAB>DELTA<TAB>REASON`.

Visible tests: `tests/test_step2.py`. Everything from step 1 must keep working. When done, reply with a short summary.

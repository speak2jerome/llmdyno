## Step 3: search and reports

- `InventoryStore.search(query) -> list[Item]`: case-insensitive substring match on SKU or name, sorted by SKU.
- `InventoryStore.low_stock(threshold: int) -> list[Item]`: items with qty <= threshold, sorted by qty, then SKU.
- `InventoryStore.total_value()`: the sum of qty * price over all items, rounded to 2 decimals.
- CLI:
  - `search QUERY`: same output format as `list`.
  - `report --format json|csv`:
    - `json` prints `{"items": [{"sku", "name", "qty", "price", "value"}, ...], "total_value": X}`, with items sorted by SKU.
    - `csv` prints the header `sku,name,qty,price,value`, then one row per item sorted by SKU, with price and value formatted to 2 decimals.

Visible tests: `tests/test_step3.py`. Everything from steps 1 and 2 must keep working. When done, reply with a short summary.

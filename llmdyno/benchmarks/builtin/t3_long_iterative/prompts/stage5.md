## Step 5: bug report and a new feature

**Bug:** users report that `total_value()` returns values like `0.30000000000000004`, and that reports show rounding errors.

Switch money handling to `decimal.Decimal`:

- `Item.price` and `total_value()` must be `Decimal` values quantized to 2 decimal places with `ROUND_HALF_UP`.
- `Item` must still accept floats, ints or strings for `price`. Convert with `Decimal(str(value))`, then quantize, so `Item("A", "x", 1, 1.005).price == Decimal("1.01")`.
- In the JSON report, `price`, `value` and `total_value` must be strings with exactly 2 decimals (e.g. `"10.50"`). CSV output keeps 2 decimals.

**Feature:** `InventoryStore.undo_last_adjustment(sku=None) -> Movement`.

- Look only at the most recent movement, or the most recent movement for `sku` if one is given.
- If it is a normal adjustment, apply the opposite delta, record a new movement with reason `"undo: <original reason>"`, and return that new movement.
- If there is no movement, or the most recent one is an `"initial"` movement or is itself an undo, raise `InventoryError` and change nothing.

**CLI:** add `undo [SKU]`, which prints the new movement in the same format as `history`.

Visible tests: `tests/test_step5.py`. Everything from the previous steps must keep working. You may update older tests only where the float-to-Decimal change requires it; mention any such change in your final summary. When done, reply with a short summary.

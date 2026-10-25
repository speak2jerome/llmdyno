You are working in /workspace. Over several steps, we will build an inventory-management Python library with a command-line interface. Keep the public API stable between steps unless a step says otherwise.

## Step 1

Package `inventory/`:

- `inventory/models.py`: dataclass `Item(sku: str, name: str, qty: int, price: float)`.
- `inventory/errors.py`: exceptions `InventoryError` (the base class), `DuplicateSku` and `UnknownSku` (both subclasses of `InventoryError`).
- `inventory/store.py`: class `InventoryStore(path)`, which persists to a JSON file at `path` (create it if it is missing). The file format is exactly `{"items": [{"sku": str, "name": str, "qty": int, "price": number}, ...]}`.
  - `add_item(item)`: raise `DuplicateSku` if the SKU already exists.
  - `remove_item(sku)`: raise `UnknownSku` if it is missing.
  - `get(sku) -> Item`: raise `UnknownSku` if it is missing.
  - `list_items() -> list[Item]`: sorted by SKU.
  - Every change is saved immediately, so a new `InventoryStore` on the same path sees it.
- CLI, run as `python -m inventory --db PATH <command>`:
  - `add SKU NAME QTY PRICE`
  - `remove SKU`
  - `list`: prints one line per item as `SKU<TAB>NAME<TAB>QTY<TAB>PRICE`, with the price formatted to 2 decimals.
  - Exit code 0 on success. On an inventory error, exit code 1 with the error message on stderr.

Visible tests are in `tests/test_step1.py`. Make them pass, and add your own tests as you go. There is no internet access, so do not install packages. When the step is done, reply with a short summary.

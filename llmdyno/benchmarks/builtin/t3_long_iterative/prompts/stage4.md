## Step 4: change of requirements, storage moves from JSON to SQLite

- `InventoryStore(path)` now stores everything (items and movement history) in a SQLite database at `path`. New files must be SQLite databases.
- Migration: if `path` exists and is a JSON file written by the previous version (the format from steps 1 and 2), convert it in place when the store is opened:
  1. Keep a backup copy of the original JSON at `path + ".json.bak"`.
  2. Import all items and the movement history, keeping the original order and timestamps.
  3. From then on, `path` is a SQLite database.
- Opening an already-migrated SQLite file must not migrate again or duplicate any data.
- The public Python API and the CLI must not change, and all previous tests must still pass.

Visible tests: `tests/test_step4.py`, which uses the sample legacy file `tests/data/legacy.json`. When done, reply with a short summary.

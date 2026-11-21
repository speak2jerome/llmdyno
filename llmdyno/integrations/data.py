"""Tables as pandas or polars data frames, and Parquet files ("llmdyno[data]"; pandas alone: "llmdyno[pandas]")."""
from __future__ import annotations

from pathlib import Path
from typing import Union

from . import require

__all__ = ["frame", "to_parquet"]


def _flat(rows: list) -> list:
    """Nested dicts become dotted columns (usage.input), lists stay as they are."""
    out = []
    for r in rows:
        flat = {}
        for k, v in r.items():
            if isinstance(v, dict):
                for k2, v2 in v.items():
                    flat[f"{k}.{k2}"] = v2
            else:
                flat[k] = v
        out.append(flat)
    return out


def frame(rows: list, backend: str = "pandas"):
    """A list of row dicts as a pandas (default) or polars DataFrame."""
    rows = _flat(rows)
    if backend == "pandas":
        pd = require("pandas", "pandas", "to_pandas()")
        return pd.DataFrame(rows)
    if backend == "polars":
        pl = require("polars", "data", "to_polars()")
        return pl.from_dicts(rows, infer_schema_length=None) if rows else pl.DataFrame()
    raise ValueError(f"backend is 'pandas' or 'polars', not {backend!r}")


def to_parquet(rows: list, path: Union[str, Path]) -> Path:
    """Write row dicts to a Parquet file (pyarrow). Lists and nested values are kept as Parquet lists and structs."""
    pa = require("pyarrow", "data", "to_parquet()")
    pq = require("pyarrow.parquet", "data", "to_parquet()")
    path = Path(path).expanduser()
    pq.write_table(pa.Table.from_pylist(_flat(rows)), path)
    return path

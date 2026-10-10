"""Small helpers shared by the model builders."""

from __future__ import annotations

from pathlib import Path

import duckdb


def copy_to_parquet(con: duckdb.DuckDBPyConnection, select_sql: str, out: Path) -> int:
    """Write the result of `select_sql` to `out` atomically; return the row count."""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    con.execute(f"COPY ({select_sql}) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)")
    tmp.replace(out)
    return con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]


def clean_name(col: str) -> str:
    """SQL: undo StatsBomb's escaped apostrophes ("N''Golo", 'N"Gog' -> "N'Golo", "N'Gog")."""
    return f"replace(replace({col}, '''''', ''''), '\"', '''')"

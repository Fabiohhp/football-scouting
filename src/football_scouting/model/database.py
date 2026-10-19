"""The DuckDB database: views over every processed Parquet table (data/processed/scouting.duckdb).

Views keep the database tiny and always in sync with the Parquet files. Naming: StatsBomb and
link and profile tables keep their names (`events`, `player_map`, `profile_values`, ...);
Transfermarkt tables get a `tm_` prefix (`tm_players`, `tm_player_valuations`, ...).
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from football_scouting.config import Config

SOURCES = (("statsbomb", ""), ("links", ""), ("transfermarkt", "tm_"), ("profiles", ""))


def database_path(cfg: Config) -> Path:
    return cfg.paths.processed / "scouting.duckdb"


def table_files(cfg: Config) -> dict[str, Path]:
    """{view name: Parquet file} for every processed table."""
    return {
        f"{prefix}{f.stem}": f
        for source, prefix in SOURCES
        for f in sorted((cfg.paths.processed / source).glob("*.parquet"))
    }


def build_database(cfg: Config) -> list[str]:
    path = database_path(cfg)
    tmp = path.with_name(path.name + ".part")
    tmp.unlink(missing_ok=True)
    with duckdb.connect(str(tmp)) as con:
        for name, f in table_files(cfg).items():
            con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{f.resolve()}')")
    tmp.replace(path)
    return list(table_files(cfg))


def connect_readonly(cfg: Config) -> duckdb.DuckDBPyConnection:
    """Read-only connection to the database, for notebooks."""
    return duckdb.connect(str(database_path(cfg)), read_only=True)

"""Typed Parquet copies of the Transfermarkt tables (data/processed/transfermarkt/).

No filtering: the tables cover all dates. Keeping later seasons apart from 2015/16 features
is the job of the analyses (leakage rule in docs/DEVELOPMENT.md), not of this layer.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

import duckdb
import pandas as pd

from football_scouting.config import PROJECT_ROOT, Config
from football_scouting.ingest.transfermarkt import raw_dir
from football_scouting.model.io import copy_to_parquet

log = logging.getLogger(__name__)

# Columns read as TIMESTAMP that only carry a date.
DATE_COLUMNS = {"players": ("date_of_birth", "contract_expiration_date")}
DOB_OVERRIDES_PATH = PROJECT_ROOT / "config" / "date_of_birth_overrides.csv"


def processed_dir(cfg: Config) -> Path:
    return cfg.paths.processed / "transfermarkt"


def load_dob_overrides(path: Path = DOB_OVERRIDES_PATH) -> pd.DataFrame:
    with open(path, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if not r["tm_player_id"].startswith("#")]
    df = pd.DataFrame(rows, columns=["tm_player_id", "date_of_birth", "source"])
    return df.astype({"tm_player_id": "int64", "date_of_birth": "datetime64[s]"})


def fill_dates_of_birth(
    con: duckdb.DuckDBPyConnection, players_sql: str, overrides: pd.DataFrame
) -> str:
    """SQL for the players table with missing dates of birth taken from `overrides`.

    Fails if an override names an unknown player or one who already has a date of birth,
    so a stale override cannot silently replace Transfermarkt data.
    """
    con.register("dob_overrides", overrides)
    bad = con.execute(
        f"""
        SELECT o.tm_player_id, p.date_of_birth FROM dob_overrides o
        LEFT JOIN ({players_sql}) p ON p.player_id = o.tm_player_id
        WHERE p.player_id IS NULL OR p.date_of_birth IS NOT NULL
        """
    ).fetchall()
    if bad:
        raise ValueError(f"date of birth overrides for unknown or already dated players: {bad}")
    return (
        "SELECT p.* REPLACE (coalesce(p.date_of_birth, CAST(o.date_of_birth AS DATE)) "
        f"AS date_of_birth) FROM ({players_sql}) p "
        "LEFT JOIN dob_overrides o ON o.tm_player_id = p.player_id"
    )


def build_transfermarkt(con: duckdb.DuckDBPyConnection, cfg: Config) -> dict[str, int]:
    counts = {}
    for table in cfg.transfermarkt.tables:
        src = f"read_csv('{raw_dir(cfg)}/{table}.csv.gz', sample_size = -1)"
        casts = ", ".join(f"CAST({c} AS DATE) AS {c}" for c in DATE_COLUMNS.get(table, ()))
        select = f"SELECT * REPLACE ({casts}) FROM {src}" if casts else f"SELECT * FROM {src}"
        if table == "players":
            select = fill_dates_of_birth(con, select, load_dob_overrides())
        counts[table] = copy_to_parquet(con, select, processed_dir(cfg) / f"{table}.parquet")
        log.info("transfermarkt %s: %d rows", table, counts[table])
    return counts

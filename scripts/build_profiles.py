"""Player profiles (data/processed/profiles/), then the database views again.

Every compared player's profile statistics as recorded, adjusted (recording context,
possession), shrunk and as percentiles within the comparison group, with the elasticities,
reliabilities and recording factors behind them (`analysis.profiles`).

Usage: uv run python scripts/build_profiles.py
"""

from __future__ import annotations

import sys
from dataclasses import fields

import duckdb

from football_scouting.analysis.profiles import Profiles, build_profiles
from football_scouting.config import PROJECT_ROOT, load_config
from football_scouting.model.database import build_database, connect_readonly
from football_scouting.model.io import copy_to_parquet


def main() -> int:
    cfg = load_config()
    with connect_readonly(cfg) as con:
        profiles = build_profiles(con, cfg)
    out = cfg.paths.processed / "profiles"
    con = duckdb.connect()
    for field in fields(Profiles):
        path = out / f"profile_{field.name}.parquet"
        con.register("frame", getattr(profiles, field.name))
        n = copy_to_parquet(con, "SELECT * FROM frame", path)
        con.unregister("frame")
        print(f"{path.relative_to(PROJECT_ROOT)}: {n:,} rows")
    build_database(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())

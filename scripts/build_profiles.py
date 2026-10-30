"""Player profiles and styles (data/processed/profiles/), then the database views again.

Every compared player's profile statistics as recorded, adjusted (recording context,
possession), shrunk and as percentiles within the comparison group, with the elasticities,
reliabilities and recording factors behind them (`analysis.profiles`); and their style
descriptors and scores on their group's style axes, with the slopes, reliabilities and loadings
behind them (`analysis.roles.build_style`).

Usage: uv run python scripts/build_profiles.py
"""

from __future__ import annotations

import sys
from dataclasses import fields

import duckdb

from football_scouting.analysis.profiles import build_profiles
from football_scouting.analysis.roles import build_style
from football_scouting.config import PROJECT_ROOT, load_config
from football_scouting.model.database import build_database, connect_readonly
from football_scouting.model.io import copy_to_parquet


def main() -> int:
    cfg = load_config()
    with connect_readonly(cfg) as con:
        profiles = build_profiles(con, cfg)
        style = build_style(con, cfg, profiles.players)
    out = cfg.paths.processed / "profiles"
    con = duckdb.connect()
    for prefix, tables in (("profile", profiles), ("style", style)):
        for field in fields(tables):
            path = out / f"{prefix}_{field.name}.parquet"
            con.register("frame", getattr(tables, field.name))
            n = copy_to_parquet(con, "SELECT * FROM frame", path)
            con.unregister("frame")
            print(f"{path.relative_to(PROJECT_ROOT)}: {n:,} rows")
    build_database(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Build the processed StatsBomb and Transfermarkt tables (data/processed/).

Rebuilds every table from the interim/raw layers; deterministic, so re-running is safe.

Usage: uv run python scripts/build_model.py
"""

from __future__ import annotations

import logging
import sys

from football_scouting.config import load_config
from football_scouting.ingest.statsbomb_parquet import connect
from football_scouting.model.statsbomb_tables import StatsBombModel
from football_scouting.model.transfermarkt_tables import build_transfermarkt


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    con = connect(cfg)
    StatsBombModel(con, cfg).build_all()
    build_transfermarkt(con, cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Download the Transfermarkt tables listed in config/pipeline.yaml (gzipped CSVs).

Idempotent: tables already on disk with the size recorded in the manifest are skipped.

Usage: uv run python scripts/download_transfermarkt.py
"""

from __future__ import annotations

import logging
import sys

from football_scouting.config import load_config
from football_scouting.http import make_client
from football_scouting.ingest.transfermarkt import download_tables


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = load_config()
    with make_client(cfg.http) as client:
        manifest = download_tables(client, cfg)
    for table, entry in manifest.items():
        print(f"  {table:<18} {entry['bytes'] / 1024**2:>6.1f} MB  {entry['last_modified']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

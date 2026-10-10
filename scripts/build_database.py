"""Create data/processed/scouting.duckdb (one view per processed table).

Usage: uv run python scripts/build_database.py
"""

from __future__ import annotations

import sys

from football_scouting.config import PROJECT_ROOT, load_config
from football_scouting.model.database import build_database, database_path


def main() -> int:
    cfg = load_config()
    views = build_database(cfg)
    print(f"{database_path(cfg).relative_to(PROJECT_ROOT)}: {len(views)} views")
    return 0


if __name__ == "__main__":
    sys.exit(main())

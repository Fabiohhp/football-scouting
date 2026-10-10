"""Download StatsBomb raw JSON (events, lineups, 360 when present) for the configured seasons.

Idempotent and resumable: files already on disk with the size recorded in the repo are skipped,
every download is size-checked and written atomically. Re-run after any interruption.

Usage: uv run python scripts/download_statsbomb.py
"""

from __future__ import annotations

import logging
import sys

from football_scouting.config import load_config
from football_scouting.http import make_client
from football_scouting.ingest.statsbomb import (
    download_tasks,
    list_match_files,
    load_competitions,
    load_matches,
    match_file_tasks,
)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = load_config()

    with make_client(cfg.http) as client:
        load_competitions(client, cfg)
        match_ids = sorted(
            m["match_id"]
            for comp in cfg.statsbomb.competitions
            for m in load_matches(client, cfg, comp)
        )
        sizes = list_match_files(client, cfg)
        tasks = match_file_tasks(cfg, match_ids, sizes)
        summary = download_tasks(client, cfg, tasks)

    print(
        f"{len(match_ids)} matches, {len(tasks)} files: {summary.downloaded} downloaded "
        f"({summary.bytes_written / 1024**2:.0f} MB), {summary.skipped} already cached, "
        f"{len(summary.failed)} failed"
    )
    for url in summary.failed:
        print(f"  FAILED {url}")
    return 1 if summary.failed else 0


if __name__ == "__main__":
    sys.exit(main())

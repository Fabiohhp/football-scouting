"""Convert the cached StatsBomb raw JSON to Parquet (data/interim/statsbomb/).

Skips outputs that already exist; pass --force to rebuild everything (e.g. after moving the
pinned open-data commit). Runs integrity checks on the result and exits non-zero on failure.

Usage: uv run python scripts/convert_statsbomb.py [--force]
"""

from __future__ import annotations

import json
import logging
import sys

from football_scouting.config import load_config
from football_scouting.ingest.statsbomb import raw_dir
from football_scouting.ingest.statsbomb_parquet import (
    connect,
    copy_json_to_parquet,
    infer_columns,
    interim_dir,
    match_files,
    match_table_path,
)

log = logging.getLogger("convert_statsbomb")


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    force = "--force" in argv
    cfg = load_config()
    comps = cfg.statsbomb.competitions
    con = connect(cfg)
    out = interim_dir(cfg)

    match_lists = {
        comp: raw_dir(cfg) / "matches" / str(comp.competition_id) / f"{comp.season_id}.json"
        for comp in comps
    }
    match_ids = {
        comp: [m["match_id"] for m in json.loads(f.read_bytes())] for comp, f in match_lists.items()
    }

    for name, files in (
        ("competitions", [raw_dir(cfg) / "competitions.json"]),
        ("matches", list(match_lists.values())),
    ):
        dest = out / f"{name}.parquet"
        if dest.exists() and not force:
            log.info("%s: exists, skipped", dest.name)
            continue
        n = copy_json_to_parquet(con, files, infer_columns(con, files), dest)
        log.info("%s: %d rows", dest.name, n)

    all_ids = sorted(i for ids in match_ids.values() for i in ids)
    for directory in ("lineups", "events"):
        todo = [c for c in comps if force or not match_table_path(cfg, directory, c).exists()]
        if not todo:
            log.info("%s: all outputs exist, skipped", directory)
            continue
        log.info("%s: inferring schema over %d files", directory, len(all_ids))
        columns = infer_columns(con, match_files(cfg, directory, all_ids))
        for comp in todo:
            n = copy_json_to_parquet(
                con,
                match_files(cfg, directory, match_ids[comp]),
                columns,
                match_table_path(cfg, directory, comp),
                extra_select=f"{comp.competition_id} AS competition_id, "
                f"{comp.season_id} AS season_id, ",
                with_match_id=True,
            )
            log.info("%s %s: %d rows", directory, comp.name, n)

    return check(con, out, len(all_ids))


def check(con, out, n_matches: int) -> int:
    """Integrity checks on the interim tables; prints problems and returns an exit code."""
    problems = []
    events = f"read_parquet('{out}/events/*.parquet')"
    lineups = f"read_parquet('{out}/lineups/*.parquet')"
    matches = f"read_parquet('{out}/matches.parquet')"
    n_event_matches, n_events = con.execute(
        f"SELECT count(DISTINCT match_id), count(*) FROM {events}"
    ).fetchone()
    if n_event_matches != n_matches:
        problems.append(f"events cover {n_event_matches} matches, expected {n_matches}")
    gaps = con.execute(
        f"SELECT count(*) FROM (SELECT match_id FROM {events} GROUP BY match_id "
        f"HAVING min(index) <> 1 OR max(index) <> count(*) OR count(DISTINCT index) <> count(*))"
    ).fetchone()[0]
    if gaps:
        problems.append(f"{gaps} matches whose event index is not exactly 1..n")
    dup_ids = con.execute(f"SELECT count(*) - count(DISTINCT id) FROM {events}").fetchone()[0]
    if dup_ids:
        problems.append(f"{dup_ids} duplicated event ids")
    bad_lineups = con.execute(
        f"SELECT count(*) FROM (SELECT match_id FROM {lineups} GROUP BY match_id "
        f"HAVING count(*) <> 2)"
    ).fetchone()[0]
    if bad_lineups:
        problems.append(f"{bad_lineups} matches without exactly 2 lineup rows")
    orphans = con.execute(
        f"SELECT count(DISTINCT match_id) FROM {events} "
        f"WHERE match_id NOT IN (SELECT match_id FROM {matches})"
    ).fetchone()[0]
    if orphans:
        problems.append(f"{orphans} event match_ids not in matches")

    print(f"events: {n_events:,} rows over {n_event_matches} matches")
    for p in problems:
        print(f"PROBLEM: {p}")
    if not problems:
        print("Integrity checks passed.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

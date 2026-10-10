"""Deep check that the interim Parquet tables are a faithful copy of the raw StatsBomb JSON.

Re-reads every raw file with the standard `json` module (independent of DuckDB) and compares:
- key paths: every key path seen in the JSON exists as a (nested) column, and vice versa;
- row counts per match (events, lineups) and per file (competitions, matches);
- per-match sum of `shot.statsbomb_xg`, as a value round-trip check.

Usage: uv run python scripts/validate_statsbomb_parquet.py
"""

from __future__ import annotations

import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from football_scouting.config import load_config
from football_scouting.ingest.statsbomb import raw_dir
from football_scouting.ingest.statsbomb_parquet import (
    connect,
    interim_dir,
    json_key_paths,
    table_paths,
)

ADDED_COLUMNS = {"competition_id", "season_id", "match_id"}


def scan(path: Path) -> tuple[int, int, set[str], float]:
    """(match_id, rows, key paths, sum of shot xG) for one raw per-match file."""
    rows = json.loads(path.read_bytes())
    paths: set[str] = set()
    for row in rows:
        paths |= json_key_paths(row)
    xg = sum(r["shot"]["statsbomb_xg"] for r in rows if "shot" in r)
    return int(path.stem), len(rows), paths, xg


def compare_paths(name: str, json_paths: set[str], parquet_paths: set[str]) -> list[str]:
    problems = []
    missing = sorted(json_paths - parquet_paths)
    extra = sorted(parquet_paths - json_paths - ADDED_COLUMNS)
    if missing:
        problems.append(f"{name}: {len(missing)} JSON key paths without a column: {missing[:10]}")
    if extra:
        problems.append(f"{name}: {len(extra)} columns never seen in the JSON: {extra[:10]}")
    print(f"  {name:<13} {len(json_paths):>4} JSON key paths, {len(parquet_paths):>4} column paths")
    return problems


def main() -> int:
    cfg = load_config()
    con = connect(cfg)
    raw, out = raw_dir(cfg), interim_dir(cfg)
    problems: list[str] = []
    print("Key paths")

    for name, files in (
        ("competitions", [raw / "competitions.json"]),
        ("matches", sorted((raw / "matches").glob("*/*.json"))),
    ):
        rows = [r for f in files for r in json.loads(f.read_bytes())]
        json_paths = set().union(*(json_key_paths(r) for r in rows))
        parquet = f"{out}/{name}.parquet"
        problems += compare_paths(name, json_paths, table_paths(con, parquet))
        n = con.execute(f"SELECT count(*) FROM read_parquet('{parquet}')").fetchone()[0]
        if n != len(rows):
            problems.append(f"{name}: {n} Parquet rows vs {len(rows)} JSON rows")

    with ProcessPoolExecutor(max_workers=6) as pool:
        for directory in ("lineups", "events"):
            parquet = f"{out}/{directory}/*.parquet"
            match_ids = [
                r[0]
                for r in con.execute(
                    f"SELECT DISTINCT match_id FROM read_parquet('{parquet}')"
                ).fetchall()
            ]
            files = [raw / directory / f"{i}.json" for i in sorted(match_ids)]
            scans = list(pool.map(scan, files, chunksize=16))
            json_paths = set().union(*(s[2] for s in scans))
            problems += compare_paths(directory, json_paths, table_paths(con, parquet))

            xg_expr = "sum(shot.statsbomb_xg)" if directory == "events" else "0.0"
            counts = {
                m: (n, xg or 0.0)
                for m, n, xg in con.execute(
                    f"SELECT match_id, count(*), {xg_expr} FROM read_parquet('{parquet}') "
                    "GROUP BY match_id"
                ).fetchall()
            }
            bad_rows = [m for m, n, _, _ in scans if counts[m][0] != n]
            bad_xg = [
                m for m, _, _, xg in scans if not math.isclose(counts[m][1], xg, abs_tol=1e-9)
            ]
            if bad_rows:
                problems.append(f"{directory}: row count differs in {len(bad_rows)} matches")
            if directory == "events" and bad_xg:
                problems.append(f"events: shot xG sum differs in {len(bad_xg)} matches")
            print(f"  {directory:<13} {len(scans)} files compared (row counts, xG sums)")

    for p in problems:
        print(f"PROBLEM: {p}")
    print("Parquet matches the raw JSON." if not problems else "")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

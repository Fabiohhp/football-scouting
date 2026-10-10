"""Verify StatsBomb Open Data coverage for the configured seasons and estimate the download size.

Downloads only the small metadata files (competitions + match lists, cached under data/raw) and
reads file sizes from the GitHub git trees API. Writes a per-match inventory to
data/interim/statsbomb/inventory.csv.

Usage: uv run python scripts/verify_statsbomb.py
"""

from __future__ import annotations

import csv
import logging
import sys
from collections import Counter

from football_scouting.config import PROJECT_ROOT, load_config
from football_scouting.http import make_client
from football_scouting.ingest.statsbomb import (
    MATCH_FILE_DIRS,
    check_fixtures,
    list_match_files,
    load_competitions,
    load_matches,
    team_names,
    teams_in_every_match,
)

MB = 1024**2


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = load_config()
    sb = cfg.statsbomb
    problems: list[str] = []

    with make_client(cfg.http) as client:
        competitions = load_competitions(client, cfg)
        print(f"StatsBomb open-data @ {sb.ref}")
        print(f"competitions.json: {len(competitions)} competition-seasons\n")

        by_key = {(c["competition_id"], c["season_id"]): c for c in competitions}
        for comp in sb.competitions:
            row = by_key.get((comp.competition_id, comp.season_id))
            if row is None:
                problems.append(f"{comp.name}: ({comp.competition_id}, {comp.season_id}) missing")
                continue
            if row["season_name"] != sb.season_name:
                problems.append(f"{comp.name}: season_name is {row['season_name']!r}")
            print(
                f"  ({comp.competition_id:>2}, {comp.season_id}) {row['competition_name']:<15} "
                f"{row['season_name']}  gender={row['competition_gender']}  "
                f"match_available={row['match_available'][:10]}  "
                f"match_available_360={row['match_available_360']}"
            )

        matches = {comp.name: load_matches(client, cfg, comp) for comp in sb.competitions}
        files = list_match_files(client, cfg)

    print("\nMatches per league")
    header = (
        f"  {'league':<15} {'matches':>7} {'expect':>6} {'teams':>5}  {'first':<10} {'last':<10}"
        f" {'events':>6} {'lineup':>6} {'360':>4} {'events MB':>9} {'lineup MB':>9}"
    )
    print(header)
    inventory: list[dict[str, object]] = []
    totals: Counter[str] = Counter()
    pool_totals: Counter[str] = Counter()
    all_ids: Counter[int] = Counter()

    for comp in sb.competitions:
        ms = matches[comp.name]
        ids = [m["match_id"] for m in ms]
        all_ids.update(ids)
        dates = sorted(m["match_date"] for m in ms)
        teams = {t for m in ms for t in team_names(m)}
        have = {d: [i for i in ids if i in files[d]] for d in MATCH_FILE_DIRS}
        size = {d: sum(files[d][i] for i in have[d]) for d in MATCH_FILE_DIRS}
        print(
            f"  {comp.name:<15} {len(ms):>7} {comp.expected_matches or '-':>6} {len(teams):>5}"
            f"  {dates[0]:<10} {dates[-1]:<10} {len(have['events']):>6} {len(have['lineups']):>6}"
            f" {len(have['three-sixty']):>4}"
            f" {size['events'] / MB:>9.1f} {size['lineups'] / MB:>9.1f}"
        )
        if comp.expected_matches is not None and len(ms) != comp.expected_matches:
            problems.append(f"{comp.name}: {len(ms)} matches, expected {comp.expected_matches}")
        for d in ("events", "lineups"):
            if len(have[d]) != len(ms):
                problems.append(f"{comp.name}: {len(ms) - len(have[d])} matches without {d} file")

        target = pool_totals if comp.scouting_pool else Counter()
        for counter in (totals, target):
            counter["matches"] += len(ms)
            for d in MATCH_FILE_DIRS:
                counter[d] += size[d]

        for m in sorted(ms, key=lambda m: (m["match_date"], m["match_id"])):
            home, away = team_names(m)
            inventory.append(
                {
                    "competition": comp.name,
                    "competition_id": comp.competition_id,
                    "season_id": comp.season_id,
                    "match_id": m["match_id"],
                    "match_date": m["match_date"],
                    "match_week": m.get("match_week"),
                    "home_team": home,
                    "away_team": away,
                    "home_score": m["home_score"],
                    "away_score": m["away_score"],
                    "match_status": m["match_status"],
                    "data_version": m["metadata"].get("data_version"),
                    "events_bytes": files["events"].get(m["match_id"]),
                    "lineups_bytes": files["lineups"].get(m["match_id"]),
                    "three_sixty_bytes": files["three-sixty"].get(m["match_id"]),
                }
            )

    print("\nMetadata values per league")
    for comp in sb.competitions:
        ms = matches[comp.name]
        status = Counter(m["match_status"] for m in ms)
        versions = Counter(m["metadata"].get("data_version") for m in ms)
        shot_fid = Counter(m["metadata"].get("shot_fidelity_version") for m in ms)
        xy_fid = Counter(m["metadata"].get("xy_fidelity_version") for m in ms)
        stages = Counter(m["competition_stage"]["name"] for m in ms)
        weeks = Counter(m.get("match_week") for m in ms)
        print(
            f"  {comp.name:<15} status={dict(status)} data_version={dict(versions)} "
            f"shot_fidelity={dict(shot_fid)} xy_fidelity={dict(xy_fid)} stages={dict(stages)} "
            f"match_weeks={min(weeks)}-{max(weeks)}"
        )

    print("\nFixture completeness (full double round-robin between the teams present)")
    for comp in sb.competitions:
        ms = matches[comp.name]
        if not comp.scouting_pool:
            always = teams_in_every_match(ms)
            print(f"  {comp.name:<15} sample league; team(s) in every match: {sorted(always)}")
            continue
        check = check_fixtures(ms)
        n_expected = len(check.teams) * (len(check.teams) - 1)
        print(
            f"  {comp.name:<15} {len(check.teams)} teams -> {n_expected} fixtures; "
            f"missing={len(check.missing)} duplicated={len(check.duplicated)}"
        )
        for home, away in check.missing:
            print(f"      missing: {home} vs {away} (home vs away)")
        for home, away in check.duplicated:
            print(f"      duplicated: {home} vs {away}")
            problems.append(f"{comp.name}: duplicated fixture {home} vs {away}")

    dup_ids = [i for i, n in all_ids.items() if n > 1]
    if dup_ids:
        problems.append(f"match_id repeated across files: {dup_ids}")

    print("\nEstimated raw download (uncompressed JSON)")
    for label, c in (("all 5 competitions", totals), ("scouting pool (4 leagues)", pool_totals)):
        total = sum(c[d] for d in MATCH_FILE_DIRS)
        print(
            f"  {label:<26} {c['matches']:>5} matches  events {c['events'] / MB:>7.1f} MB  "
            f"lineups {c['lineups'] / MB:>5.1f} MB  360 {c['three-sixty'] / MB:>4.1f} MB  "
            f"total {total / MB:>7.1f} MB"
        )

    out = cfg.paths.interim / "statsbomb" / "inventory.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(inventory[0]))
        writer.writeheader()
        writer.writerows(inventory)
    print(f"\nInventory: {len(inventory)} matches -> {out.relative_to(PROJECT_ROOT)}")

    if problems:
        print("\nPROBLEMS")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

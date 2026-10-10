"""Link StatsBomb matches, teams and players to Transfermarkt (data/processed/links/).

Writes team_map, match_map, player_team_links and player_map as Parquet, a review CSV of the
links that are not high-confidence, and prints the match rate.

Usage: uv run python scripts/link_entities.py
"""

from __future__ import annotations

import logging
import sys

from football_scouting.config import PROJECT_ROOT, load_config
from football_scouting.ingest.statsbomb_parquet import connect
from football_scouting.model.entity_resolution import links_dir, resolve_players
from football_scouting.model.io import copy_to_parquet

REVIEW_COLUMNS = [
    "sb_player_id",
    "tm_player_id",
    "confidence",
    "method",
    "sb_name",
    "sb_nickname",
    "tm_name",
    "team_id",
    "competition_id",
    "sb_n_games",
    "tm_n_games",
    "both_games",
    "games_jaccard",
    "name_similarity",
    "margin",
    "sb_country",
    "tm_country",
    "tm_date_of_birth",
    "reason",
]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    con = connect(cfg)
    tables = resolve_players(con, cfg)
    out = links_dir(cfg)
    for name, df in tables.items():
        con.register(f"{name}_out", df)
        n = copy_to_parquet(con, f"SELECT * FROM {name}_out", out / f"{name}.parquet")
        logging.info("%s: %d rows", name, n)

    links = tables["player_team_links"]
    review = links[links["confidence"] != "high"].reindex(columns=REVIEW_COLUMNS)
    review.sort_values(["confidence", "games_jaccard"]).to_csv(
        out / "player_match_review.csv", index=False
    )

    sb = cfg.paths.processed / "statsbomb"
    con.register("player_map_out", tables["player_map"])
    rows = con.execute(
        f"""
        SELECT c.scouting_pool, count(DISTINCT ps.player_id) AS players,
               count(DISTINCT ps.player_id) FILTER (WHERE m.sb_player_id IS NOT NULL) AS linked,
               sum(ps.minutes) AS minutes,
               sum(ps.minutes) FILTER (WHERE m.sb_player_id IS NOT NULL) AS linked_minutes
        FROM read_parquet('{sb}/player_seasons.parquet') ps
        JOIN read_parquet('{sb}/competitions.parquet') c USING (competition_id, season_id)
        LEFT JOIN player_map_out m ON m.sb_player_id = ps.player_id
        WHERE ps.matches_played > 0
        GROUP BY ALL ORDER BY 1 DESC
        """
    ).fetchall()
    for pool, players, linked, minutes, linked_minutes in rows:
        label = "scouting pool" if pool else "Bundesliga sample"
        print(
            f"{label:<18} players linked {linked:,}/{players:,} ({100 * linked / players:.1f}%), "
            f"minutes covered {100 * linked_minutes / minutes:.2f}%"
        )
    print("confidence (players):", tables["player_map"]["confidence"].value_counts().to_dict())
    print(f"review file: {(out / 'player_match_review.csv').relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

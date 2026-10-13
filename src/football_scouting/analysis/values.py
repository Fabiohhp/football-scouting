"""Transfermarkt market values of the scouting pool's players.

Transfermarkt publishes values in batches (league by league, a few times a year), so a
player's value "at date X" is the latest valuation on or before X, and how old that valuation
is matters. Values dated after the back-test cutoff are outcomes: never use them as features.
"""

from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd


def pool_valuations(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Every valuation of a player who played in the scouting pool, oldest first.

    Columns: `player_id` (StatsBomb), `date`, `value` (euros) and `club`, the club at the
    valuation date. `club` comes from `current_club_name`: the valuation's `current_club_id`
    is often the player's 2026 club instead (see `docs/DEVELOPMENT.md`).
    """
    df = con.execute(
        """
        SELECT m.sb_player_id AS player_id, v.date, v.market_value_in_eur AS value,
               v.current_club_name AS club
        FROM tm_player_valuations v
        JOIN player_map m ON m.tm_player_id = v.player_id
        WHERE m.sb_player_id IN (
            SELECT ps.player_id
            FROM player_seasons ps JOIN competitions c USING (competition_id, season_id)
            WHERE c.scouting_pool AND ps.matches_played > 0)
        ORDER BY player_id, v.date
        """
    ).df()
    df["date"] = pd.to_datetime(df["date"])
    return df


def value_at(
    valuations: pd.DataFrame, when: date | str, *, max_age_days: int | None = None
) -> pd.DataFrame:
    """Each player's latest valuation on or before `when`, indexed by `player_id`.

    Adds `age_days`, the days between that valuation and `when`. With `max_age_days`, players
    whose latest valuation is older are left out (no longer valued).
    """
    when = pd.Timestamp(when)
    out = (
        valuations[valuations["date"] <= when]
        .sort_values(["player_id", "date"])
        .groupby("player_id")
        .last()
    )
    out["age_days"] = (when - out["date"]).dt.days
    if max_age_days is not None:
        out = out[out["age_days"] <= max_age_days]
    return out

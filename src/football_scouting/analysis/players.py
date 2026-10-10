"""Player-level season tables for the scouting pool (competitions with `scouting_pool: true`)."""

from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd

from football_scouting.config import Config


def group_minute_columns(cfg: Config) -> list[str]:
    """`player_seasons` columns with minutes per position group, in config order."""
    return [f"minutes_{g.code.lower()}" for g in cfg.position_groups]


def pool_player_seasons(
    con: duckdb.DuckDBPyConnection, cfg: Config, *, age_on: date
) -> pd.DataFrame:
    """One row per player who played in the scouting pool.

    Minutes are summed over every pool club, so a mid-season move (within or between pool
    leagues) gives a single row; minutes in competitions outside the pool are left out.
    `league` is the pool league where the player played most. `position_group` is the group
    with the most minutes (ties go to the first group in config order), `primary_share` is
    that group's share of the player's minutes and `comparison_group` is the group the
    player is compared within (config `comparison_groups`). `age` is in years on `age_on`,
    from the Transfermarkt date of birth (missing when Transfermarkt has none).
    """
    group_cols = group_minute_columns(cfg)
    group_sums = ", ".join(f"sum(ps.{c}) AS {c}" for c in group_cols)
    df = con.execute(
        f"""
        WITH pool AS (
            SELECT ps.*, c.competition_name
            FROM player_seasons ps JOIN competitions c USING (competition_id, season_id)
            WHERE c.scouting_pool AND ps.matches_played > 0)
        SELECT ps.player_id, any_value(p.player_name) AS player_name,
               count(*) AS n_teams, count(DISTINCT ps.competition_id) AS n_leagues,
               arg_max(ps.competition_name, ps.minutes) AS league,
               max(ps.minutes) AS max_team_minutes,
               sum(ps.matches_played) AS matches_played, sum(ps.starts) AS starts,
               sum(ps.minutes) AS minutes, {group_sums},
               any_value(tp.date_of_birth) AS date_of_birth
        FROM pool ps
        JOIN players p USING (player_id)
        LEFT JOIN player_map m ON m.sb_player_id = ps.player_id
        LEFT JOIN tm_players tp ON tp.player_id = m.tm_player_id
        GROUP BY ps.player_id
        ORDER BY ps.player_id
        """
    ).df()
    codes = [g.code for g in cfg.position_groups]
    by_group = df[group_cols].to_numpy()
    df["position_group"] = pd.Categorical(
        [codes[i] for i in by_group.argmax(axis=1)], categories=codes, ordered=True
    )
    df["primary_share"] = by_group.max(axis=1) / df["minutes"]
    df["comparison_group"] = pd.Categorical(
        df["position_group"].map(cfg.comparison_group_of()),
        categories=[g.code for g in cfg.comparison_groups],
        ordered=True,
    )
    dob = pd.to_datetime(df["date_of_birth"])
    df["age"] = (pd.Timestamp(age_on) - dob).dt.days / 365.25
    return df

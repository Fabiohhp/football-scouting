"""Per player-match event counts: the building block for per-90 statistics.

`player_match_counts` counts events for every player who played a pool match, next to the
time on the pitch from `player_matches`. Counts add up, so a season, half a season or any
random sample of matches is a sum of rows; `rates` then turns summed counts into per-90
rates and ratios.

Definitions (StatsBomb pitch, 120 x 80, the acting team attacks towards x = 120):
- open-play passes exclude throw-ins, free kicks, goal kicks, corners and kick-offs;
- the penalty box is x >= 102 and 18 <= y <= 62;
- non-penalty shots, xG and goals leave out penalties;
- touches are on-ball actions: passes, completed ball receipts, carries, dribbles, shots,
  miscontrols, dispossessions, successful ball recoveries, interceptions, clearances,
  blocks, 50/50s and shields.
"""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

# Per-90 rates: {column: label}.
PER_90 = {
    "passes": "Open-play passes",
    "crosses": "Open-play crosses",
    "key_passes": "Key passes (open play)",
    "passes_into_box": "Completed passes into the box",
    "shots": "Non-penalty shots",
    "xg": "Non-penalty xG",
    "goals": "Non-penalty goals",
    "dribbles": "Dribbles attempted",
    "touches_in_box": "Touches in the opposition box",
    "pressures": "Pressures",
    "tackles": "Tackles",
    "interceptions": "Interceptions",
    "recoveries": "Ball recoveries",
    "clearances": "Clearances",
    "blocks": "Blocks",
}
# Ratios: {column: (numerator, denominator, label)}.
RATIOS = {
    "pass_completion": ("passes_completed", "passes", "Open-play pass completion"),
    "dribble_success": ("dribbles_completed", "dribbles", "Dribble success"),
    "mean_x": ("sum_x", "touches", "Average touch position (x, towards goal)"),
    "mean_width": ("sum_width", "touches", "Average touch distance from the centre line"),
}
LABELS = PER_90 | {name: label for name, (_, _, label) in RATIOS.items()}
# Summed columns `rates` needs.
SUMMED = list(
    dict.fromkeys(["minutes", *PER_90, *(c for n, d, _ in RATIOS.values() for c in (n, d))])
)

OPEN_PLAY = "(pass_type IS NULL OR pass_type IN ('Recovery', 'Interception'))"
ON_BALL = (
    "Pass", "Ball Receipt*", "Carry", "Dribble", "Shot", "Miscontrol", "Dispossessed",
    "Ball Recovery", "Interception", "Clearance", "Block", "50/50", "Shield",
)  # fmt: skip


SOURCES = ("p", "s", "d", "pr", "da", "t")  # the CTEs below, one per event table


def in_box(x: str, y: str) -> str:
    return f"({x} >= 102 AND {y} BETWEEN 18 AND 62)"


def player_match_counts(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """One row per player and pool match played: minutes and event counts."""
    on_ball = ", ".join(f"'{t}'" for t in ON_BALL)
    joins = "\n".join(f"LEFT JOIN {a} USING (match_id, player_id)" for a in SOURCES)
    counts = con.execute(
        f"""
        WITH
        p AS (
            SELECT match_id, player_id,
                   count(*) FILTER (WHERE {OPEN_PLAY}) AS passes,
                   count(*) FILTER (WHERE {OPEN_PLAY} AND completed) AS passes_completed,
                   count(*) FILTER (WHERE {OPEN_PLAY} AND "cross") AS crosses,
                   count(*) FILTER (WHERE {OPEN_PLAY} AND (shot_assist OR goal_assist))
                       AS key_passes,
                   count(*) FILTER (WHERE {OPEN_PLAY} AND completed
                                    AND {in_box("end_x", "end_y")} AND NOT {in_box("x", "y")})
                       AS passes_into_box
            FROM passes GROUP BY ALL),
        s AS (
            SELECT match_id, player_id,
                   count(*) AS shots, sum(statsbomb_xg) AS xg,
                   count(*) FILTER (WHERE outcome = 'Goal') AS goals
            FROM shots WHERE shot_type <> 'Penalty' GROUP BY ALL),
        d AS (
            SELECT match_id, player_id, count(*) AS dribbles,
                   count(*) FILTER (WHERE outcome = 'Complete') AS dribbles_completed
            FROM dribbles GROUP BY ALL),
        pr AS (SELECT match_id, player_id, count(*) AS pressures FROM pressures GROUP BY ALL),
        da AS (
            SELECT match_id, player_id,
                   count(*) FILTER (WHERE action = 'Tackle') AS tackles,
                   count(*) FILTER (WHERE action = 'Interception') AS interceptions,
                   count(*) FILTER (WHERE action = 'Ball Recovery' AND outcome IS NULL)
                       AS recoveries,
                   count(*) FILTER (WHERE action = 'Clearance') AS clearances,
                   count(*) FILTER (WHERE action = 'Block') AS blocks
            FROM defensive_actions GROUP BY ALL),
        t AS (
            SELECT match_id, player_id, count(*) AS touches,
                   count(*) FILTER (WHERE {in_box("x", "y")}) AS touches_in_box,
                   sum(x) AS sum_x, sum(abs(y - 40)) AS sum_width
            FROM events
            WHERE type IN ({on_ball})
              AND event_id NOT IN (SELECT event_id FROM ball_receipts
                                   WHERE outcome = 'Incomplete')
              AND event_id NOT IN (SELECT event_id FROM ball_recoveries
                                   WHERE recovery_failure)
            GROUP BY ALL)
        SELECT pm.match_id, m.competition_id, m.match_date, pm.team_id, pm.player_id,
               pm.seconds_played / 60 AS minutes,
               {", ".join(f"{a}.* EXCLUDE (match_id, player_id)" for a in SOURCES)}
        FROM player_matches pm
        JOIN matches m USING (match_id)
        {joins}
        WHERE m.scouting_pool AND pm.played
        ORDER BY pm.match_id, pm.team_id, pm.player_id
        """
    ).df()
    # Players without a given event get 0; plain NumPy dtypes (not nullable Int64) downstream.
    for col in counts.columns[6:]:
        dtype = "int64" if pd.api.types.is_integer_dtype(counts[col]) else "float64"
        counts[col] = counts[col].fillna(0).astype(dtype)
    return counts


def rates(sums: pd.DataFrame) -> pd.DataFrame:
    """Per-90 rates and ratios from summed counts (needs `minutes` and the count columns).

    Ratios are NaN when the denominator is 0.
    """
    out = pd.DataFrame(index=sums.index)
    for col in PER_90:
        out[col] = sums[col] / sums["minutes"] * 90
    for col, (num, den, _) in RATIOS.items():
        out[col] = sums[num] / sums[den].replace(0, np.nan)
    return out

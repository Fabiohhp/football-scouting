"""Per player-match event counts: the building block for per-90 statistics.

`player_match_counts` counts events for every player who played a pool match, next to the
time on the pitch from `player_matches`. Counts add up, so a season, half a season or any
random sample of matches is a sum of rows; `rates` then turns summed counts into per-90
rates and ratios.

Definitions (StatsBomb pitch, 120 x 80 units of about a yard, the acting team attacks towards
x = 120; the goal's centre is (120, 40)):
- open-play passes exclude throw-ins, free kicks, goal kicks, corners and kick-offs;
- the penalty box is x >= 102 and 18 <= y <= 62; the final third is x >= 80;
- non-penalty shots, xG and goals leave out penalties; finishing is non-penalty goals minus
  xG per shot (0 = scores what the chances are worth);
- expected assists (xA) are the xG of the shots set up by a player's open-play passes;
- long passes travel 30 units or more;
- passes into the box, the final third and progressive passes count completed open-play
  passes; carries count every carry;
- progressive passes and carries follow three rules (`PROGRESSIVE_RULES`): "10y", at least 10
  units towards the goal line, passes starting beyond the defending 40% of the pitch (x >= 48)
  and carries ending beyond the halfway line (x >= 60); "zones", at least 30 m closer to the
  goal's centre within the own half, 15 m from the own half into the other, 10 m within the
  other half (Wyscout's rule, on a 105 m pitch); "25pct", ending at least 25% closer to the
  goal's centre;
- aerial duels are won (`aerial_won` on a pass, clearance, shot or miscontrol) or lost (a
  duel of type Aerial Lost); every match has as many of each;
- tackles count every tackle; tackles won are those won or successful; dribblers tackled is
  tackles won over tackles won plus times dribbled past;
- counterpressures are pressures within five seconds of the team losing the ball
  (`counterpress`);
- ball losses are miscontrols and dispossessions;
- touches are on-ball actions: passes, completed ball receipts, carries, dribbles, shots,
  miscontrols, dispossessions, successful ball recoveries, interceptions, clearances,
  blocks, 50/50s and shields;
- the height of defensive actions is the mean x of tackles, interceptions, ball recoveries,
  clearances and blocks.
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
    "xa": "Expected assists (xA, open play)",
    "through_balls": "Through balls",
    "long_passes": "Long passes (30+ yards)",
    "switches": "Switches of play",
    "passes_into_final_third": "Completed passes into the final third",
    "progressive_passes_10y": "Progressive passes (10 yards)",
    "progressive_passes_zones": "Progressive passes (zones)",
    "progressive_passes_25pct": "Progressive passes (25% closer)",
    "carries_into_final_third": "Carries into the final third",
    "carries_into_box": "Carries into the box",
    "progressive_carries_10y": "Progressive carries (10 yards)",
    "progressive_carries_zones": "Progressive carries (zones)",
    "progressive_carries_25pct": "Progressive carries (25% closer)",
    "receipts_in_box": "Passes received in the box",
    "fouls_won": "Fouls won",
    "aerial_duels": "Aerial duels",
    "dribbled_past": "Times dribbled past",
    "counterpressures": "Counterpressures",
    "pressures_final_third": "Pressures in the final third",
}
# Ratios: {column: (numerator, denominator, label)}.
RATIOS = {
    "pass_completion": ("passes_completed", "passes", "Open-play pass completion"),
    "dribble_success": ("dribbles_completed", "dribbles", "Dribble success"),
    "xg_per_shot": ("xg", "shots", "Non-penalty xG per shot"),
    "finishing": ("goals_minus_xg", "shots", "Finishing: non-penalty goals minus xG per shot"),
    "mean_x": ("sum_x", "touches", "Average touch position (x, towards goal)"),
    "mean_width": ("sum_width", "touches", "Average touch distance from the centre line"),
    "long_pass_completion": ("long_passes_completed", "long_passes", "Long pass completion"),
    "cross_completion": ("crosses_completed", "crosses", "Cross completion"),
    "aerial_win_rate": ("aerials_won", "aerial_duels", "Aerial duels won"),
    "dribblers_tackled": ("tackles_won", "dribbler_duels", "Dribblers tackled"),
    "ball_losses_per_touch": ("ball_losses", "touches", "Ball losses per touch"),
    "defence_height": ("sum_defence_x", "defensive_actions", "Height of defensive actions (x)"),
}
LABELS = PER_90 | {name: label for name, (_, _, label) in RATIOS.items()}
# Summed columns `rates` needs.
SUMMED = list(
    dict.fromkeys(["minutes", *PER_90, *(c for n, d, _ in RATIOS.values() for c in (n, d))])
)
# Every rate and ratio by what it describes.
FAMILIES = {
    "Shooting": ["shots", "xg", "goals", "xg_per_shot", "finishing", "touches_in_box",
                 "receipts_in_box"],
    "Chance creation": ["key_passes", "xa", "passes_into_box", "through_balls", "crosses",
                        "cross_completion"],
    "Passing and progression": ["passes", "pass_completion", "long_passes",
                                "long_pass_completion", "switches", "passes_into_final_third",
                                "progressive_passes_10y", "progressive_passes_zones",
                                "progressive_passes_25pct"],
    "Carrying and ball security": ["dribbles", "dribble_success", "carries_into_final_third",
                                   "carries_into_box", "progressive_carries_10y",
                                   "progressive_carries_zones", "progressive_carries_25pct",
                                   "fouls_won", "ball_losses_per_touch"],
    "Defending": ["pressures", "counterpressures", "pressures_final_third", "tackles",
                  "dribblers_tackled", "dribbled_past", "interceptions", "recoveries",
                  "clearances", "blocks"],
    "Aerial duels": ["aerial_duels", "aerial_win_rate"],
    "Position": ["mean_x", "mean_width", "defence_height"],
}  # fmt: skip
# Rates where a lower number is the better one.
LOWER_IS_BETTER = ("dribbled_past", "ball_losses_per_touch")

OPEN_PLAY = "(pass_type IS NULL OR pass_type IN ('Recovery', 'Interception'))"
ON_BALL = (
    "Pass", "Ball Receipt*", "Carry", "Dribble", "Shot", "Miscontrol", "Dispossessed",
    "Ball Recovery", "Interception", "Clearance", "Block", "50/50", "Shield",
)  # fmt: skip
TACKLE_WON = ("Won", "Success In Play", "Success Out")
PROGRESSIVE_RULES = ("10y", "zones", "25pct")
UNITS_PER_METRE = 120 / 105  # pitch length in StatsBomb units over a 105 m pitch

# The CTEs below, one per event table or family of events.
SOURCES = ("p", "xa", "s", "d", "c", "r", "pr", "da", "dp", "aw", "al", "bl", "fw", "t")


def in_box(x: str, y: str) -> str:
    return f"({x} >= 102 AND {y} BETWEEN 18 AND 62)"


def progressive(rule: str, kind: str) -> str:
    """SQL condition: a pass or carry (`kind`) from (x, y) to (end_x, end_y) is progressive."""
    start = "sqrt((120 - x) ** 2 + (40 - y) ** 2)"
    end = "sqrt((120 - end_x) ** 2 + (40 - end_y) ** 2)"
    if rule == "10y":
        where = "x >= 48" if kind == "pass" else "end_x >= 60"
        return f"({where} AND end_x - x >= 10)"
    if rule == "zones":
        gain, m = f"({start} - {end})", UNITS_PER_METRE
        return (
            f"(CASE WHEN x < 60 AND end_x < 60 THEN {gain} >= {30 * m}"
            f" WHEN x < 60 THEN {gain} >= {15 * m}"
            f" WHEN end_x >= 60 THEN {gain} >= {10 * m} ELSE false END)"
        )
    if rule == "25pct":
        return f"({end} <= 0.75 * {start})"
    raise ValueError(f"unknown rule {rule!r}")


def player_match_counts(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """One row per player and pool match played: minutes and event counts."""
    on_ball = ", ".join(f"'{t}'" for t in ON_BALL)
    tackle_won = ", ".join(f"'{o}'" for o in TACKLE_WON)
    box, end_box = in_box("x", "y"), in_box("end_x", "end_y")
    prog_passes = ",\n".join(
        f"count(*) FILTER (WHERE {OPEN_PLAY} AND completed AND {progressive(r, 'pass')})"
        f" AS progressive_passes_{r}"
        for r in PROGRESSIVE_RULES
    )
    prog_carries = ",\n".join(
        f"count(*) FILTER (WHERE {progressive(r, 'carry')}) AS progressive_carries_{r}"
        for r in PROGRESSIVE_RULES
    )
    joins = "\n".join(f"LEFT JOIN {a} USING (match_id, player_id)" for a in SOURCES)
    counts = con.execute(
        f"""
        WITH
        p AS (
            SELECT match_id, player_id,
                   count(*) FILTER (WHERE {OPEN_PLAY}) AS passes,
                   count(*) FILTER (WHERE {OPEN_PLAY} AND completed) AS passes_completed,
                   count(*) FILTER (WHERE {OPEN_PLAY} AND "cross") AS crosses,
                   count(*) FILTER (WHERE {OPEN_PLAY} AND "cross" AND completed)
                       AS crosses_completed,
                   count(*) FILTER (WHERE {OPEN_PLAY} AND (shot_assist OR goal_assist))
                       AS key_passes,
                   count(*) FILTER (WHERE {OPEN_PLAY} AND through_ball) AS through_balls,
                   count(*) FILTER (WHERE {OPEN_PLAY} AND "switch") AS switches,
                   count(*) FILTER (WHERE {OPEN_PLAY} AND length >= 30) AS long_passes,
                   count(*) FILTER (WHERE {OPEN_PLAY} AND length >= 30 AND completed)
                       AS long_passes_completed,
                   count(*) FILTER (WHERE {OPEN_PLAY} AND completed
                                    AND {end_box} AND NOT {box})
                       AS passes_into_box,
                   count(*) FILTER (WHERE {OPEN_PLAY} AND completed AND x < 80 AND end_x >= 80)
                       AS passes_into_final_third,
                   {prog_passes}
            FROM passes GROUP BY ALL),
        xa AS (
            SELECT p.match_id, p.player_id, sum(s.statsbomb_xg) AS xa
            FROM shots s JOIN passes p ON p.event_id = s.key_pass_id
            WHERE s.shot_type <> 'Penalty' AND {OPEN_PLAY} GROUP BY ALL),
        s AS (
            SELECT match_id, player_id,
                   count(*) AS shots, sum(statsbomb_xg) AS xg,
                   count(*) FILTER (WHERE outcome = 'Goal') AS goals,
                   count(*) FILTER (WHERE outcome = 'Goal') - sum(statsbomb_xg) AS goals_minus_xg
            FROM shots WHERE shot_type <> 'Penalty' GROUP BY ALL),
        d AS (
            SELECT match_id, player_id, count(*) AS dribbles,
                   count(*) FILTER (WHERE outcome = 'Complete') AS dribbles_completed
            FROM dribbles GROUP BY ALL),
        c AS (
            SELECT match_id, player_id,
                   count(*) FILTER (WHERE x < 80 AND end_x >= 80) AS carries_into_final_third,
                   count(*) FILTER (WHERE {end_box} AND NOT {box}) AS carries_into_box,
                   {prog_carries}
            FROM carries GROUP BY ALL),
        r AS (
            SELECT match_id, player_id, count(*) FILTER (WHERE {box}) AS receipts_in_box
            FROM ball_receipts WHERE outcome IS NULL GROUP BY ALL),
        pr AS (
            SELECT match_id, player_id, count(*) AS pressures,
                   count(*) FILTER (WHERE counterpress) AS counterpressures,
                   count(*) FILTER (WHERE x >= 80) AS pressures_final_third
            FROM pressures GROUP BY ALL),
        da AS (
            SELECT match_id, player_id,
                   count(*) FILTER (WHERE action = 'Tackle') AS tackles,
                   count(*) FILTER (WHERE action = 'Tackle' AND outcome IN ({tackle_won}))
                       AS tackles_won,
                   count(*) FILTER (WHERE action = 'Interception') AS interceptions,
                   count(*) FILTER (WHERE action = 'Ball Recovery' AND outcome IS NULL)
                       AS recoveries,
                   count(*) FILTER (WHERE action = 'Clearance') AS clearances,
                   count(*) FILTER (WHERE action = 'Block') AS blocks,
                   count(*) FILTER (WHERE action IN ('Tackle', 'Interception', 'Ball Recovery',
                                                     'Clearance', 'Block'))
                       AS defensive_actions,
                   sum(x) FILTER (WHERE action IN ('Tackle', 'Interception', 'Ball Recovery',
                                                   'Clearance', 'Block'))
                       AS sum_defence_x
            FROM defensive_actions GROUP BY ALL),
        dp AS (SELECT match_id, player_id, count(*) AS dribbled_past FROM dribbled_past
               GROUP BY ALL),
        aw AS (
            SELECT match_id, player_id, count(*) AS aerials_won
            FROM (SELECT match_id, player_id FROM passes WHERE aerial_won
                  UNION ALL SELECT match_id, player_id FROM clearances WHERE aerial_won
                  UNION ALL SELECT match_id, player_id FROM shots WHERE aerial_won
                  UNION ALL SELECT match_id, player_id FROM miscontrols WHERE aerial_won)
            GROUP BY ALL),
        al AS (
            SELECT match_id, player_id, count(*) AS aerials_lost FROM duels
            WHERE duel_type = 'Aerial Lost' GROUP BY ALL),
        bl AS (
            SELECT match_id, player_id, count(*) AS ball_losses
            FROM (SELECT match_id, player_id FROM miscontrols
                  UNION ALL SELECT match_id, player_id FROM dispossessions)
            GROUP BY ALL),
        fw AS (SELECT match_id, player_id, count(*) AS fouls_won FROM fouls_won GROUP BY ALL),
        t AS (
            SELECT match_id, player_id, count(*) AS touches,
                   count(*) FILTER (WHERE {box}) AS touches_in_box,
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
    counts["aerial_duels"] = counts["aerials_won"] + counts["aerials_lost"]
    counts["dribbler_duels"] = counts["tackles_won"] + counts["dribbled_past"]
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

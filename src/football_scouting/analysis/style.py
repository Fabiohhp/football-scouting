"""Style: which role a player plays, read from what they do and where.

The profiles (`analysis.profiles`) compare how well players play the role of their comparison
group, in volumes per 90. The descriptors here describe the role itself, as shares and places,
so that a descriptor does not grow with how much a player is involved: where a player touches
the ball, what they do with it, how they pass, with which foot, and how they defend.

Definitions (StatsBomb pitch; touches, open-play passes and defensive actions as in
`analysis.metrics`):
- where: `touch_height`, the mean x of touches; `touch_width`, their mean distance from the
  centre line, left and right alike; `spread_length` and `spread_width`, the standard deviation
  of touches along and across the pitch within each match, pooled over the matches summed (a
  player who changes flank or position between matches does not spread wider for it);
  `defence_height`; `box_share`, touches in the opposition box per touch;
- with the ball, per touch: open-play passes (`pass_share`), dribbles, non-penalty shots and the
  distance carried (`carry_distance`, in yards); crosses per open-play pass;
- passing, per open-play pass: the ease (`pass_ease`, the mean expected completion of
  `analysis.xpass`), the mean length, and the shares long (30+ yards), high, forward (more
  forward than sideways), backward, switches and through balls;
- foot: `left_foot_share` of the open-play passes played with a foot, and `inside_foot_share` of
  those played from the wide channels (y < 18 or y > 62, outside the width of the box) with the
  foot nearer the centre (the right foot on the left);
- without the ball: pressures per pressure or defensive action (`press_share`), tackles and
  clearances plus blocks per defensive action, counterpressures and pressures in the final third
  per pressure, aerial duels per touch or aerial duel lost (`aerial_share`).

`player_match_style` gives the sums behind them that `metrics.player_match_counts` lacks, and
`descriptors` turns any sum of rows into the descriptors, so that split halves and recording
contexts work as for the profiles. A style describes the role of a player's comparison group:
`group_share` gives the share of each match a player spent in a position of their group, and
only the matches with at least `IN_GROUP` of it are summed (a centre-back's matches at
full-back describe another role). The shares of defensive actions are built from their parts,
so that counts rescaled for the recording context (`profiles.rescale`) carry through.
`touch_map` gives where a player touches the ball, as shares of a grid of zones, each match
mirrored to the same side.

A descriptor's dependence on possession is measured within players (`possession_slopes`: a
weighted least-squares slope of each match's value on the team's share of possession while the
player was on the pitch, with a fixed effect per player and the descriptor's denominator as
weight) and `adjust` puts it on an even share.
"""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

from football_scouting.analysis.metrics import OPEN_PLAY, TOUCH
from football_scouting.analysis.possession import REFERENCE_SHARE
from football_scouting.analysis.profiles import KEYS, XPASS_SUMS
from football_scouting.config import Config

DEFENDING = ("tackles", "interceptions", "recoveries", "clearances", "blocks")
IN_GROUP = 0.5  # a match describes a player's style with this share of it in their group
WIDE = "(y < 18 OR y > 62)"  # outside the width of the box
# Ratio descriptors: {name: (numerator, denominator, label)}; `defending`, `engagements`,
# `clearances_blocks` and `involvements` are built from their parts by `descriptors`.
RATIOS = {
    "touch_height": ("sum_x", "touches", "Touch height (mean x)"),
    "touch_width": ("sum_width", "touches", "Touch width (from the centre line)"),
    "defence_height": ("sum_defence_x", "defensive_actions", "Height of defensive actions (x)"),
    "box_share": ("touches_in_box", "touches", "Touches in the box, per touch"),
    "pass_share": ("passes", "touches", "Open-play passes per touch"),
    "carry_distance": ("carry_distance", "touches", "Distance carried per touch (yards)"),
    "dribble_share": ("dribbles", "touches", "Dribbles per touch"),
    "shot_share": ("shots", "touches", "Shots per touch"),
    "cross_share": ("crosses", "passes", "Crosses per pass"),
    "pass_ease": (XPASS_SUMS["expected"], XPASS_SUMS["passes"], "Pass ease (expected completion)"),
    "pass_length": ("pass_length", "passes", "Pass length (yards)"),
    "long_share": ("long_passes", "passes", "Long passes per pass"),
    "high_share": ("high_passes", "passes", "High passes per pass"),
    "forward_share": ("forward_passes", "passes", "Forward passes per pass"),
    "backward_share": ("backward_passes", "passes", "Backward passes per pass"),
    "switch_share": ("switches", "passes", "Switches per pass"),
    "through_share": ("through_balls", "passes", "Through balls per pass"),
    "left_foot_share": ("left_foot_passes", "foot_passes", "Left foot share"),
    "inside_foot_share": ("inside_foot_passes", "wide_foot_passes", "Inside foot share, wide"),
    "press_share": ("pressures", "engagements", "Pressures per engagement"),
    "tackle_share": ("tackles", "defending", "Tackles per defensive action"),
    "clearance_share": ("clearances_blocks", "defending", "Clearances and blocks per action"),
    "counterpress_share": ("counterpressures", "pressures", "Counterpressures per pressure"),
    "high_press_share": (
        "pressures_final_third",
        "pressures",
        "Final-third pressures per pressure",
    ),
    "aerial_share": ("aerial_duels", "involvements", "Aerial duels per touch"),
}
# Spreads: {name: (sum of squared deviations from each match's mean, label)}, over touches.
SPREADS = {
    "spread_length": ("within_x", "Spread of touches along the pitch"),
    "spread_width": ("within_y", "Spread of touches across the pitch"),
}
LABELS = {k: v[-1] for k, v in (RATIOS | SPREADS).items()}
FAMILIES = {
    "Where": ["touch_height", "touch_width", "spread_length", "spread_width", "defence_height",
              "box_share"],
    "With the ball": ["pass_share", "carry_distance", "dribble_share", "shot_share",
                      "cross_share"],
    "Passing": ["pass_ease", "pass_length", "long_share", "high_share", "forward_share",
                "backward_share", "switch_share", "through_share"],
    "Foot": ["left_foot_share", "inside_foot_share"],
    "Without the ball": ["press_share", "tackle_share", "clearance_share", "counterpress_share",
                         "high_press_share", "aerial_share"],
}  # fmt: skip
NAMES = [m for ms in FAMILIES.values() for m in ms]
_BUILT = {
    "defending": DEFENDING,
    "engagements": ("pressures", *DEFENDING),
    "clearances_blocks": ("clearances", "blocks"),
    "involvements": ("touches", "aerials_lost"),
}
# The columns `descriptors` reads from summed rows.
SUMMED = list(
    dict.fromkeys(
        c
        for c in [*(c for n, d, _ in RATIOS.values() for c in (n, d)), "touches"]
        + [c for c, _ in SPREADS.values()]
        + [c for parts in _BUILT.values() for c in parts]
        if c not in _BUILT
    )
)


def player_match_style(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """One row per player and pool match played (`profiles.KEYS`): the sums behind the
    descriptors that `metrics.player_match_counts` lacks."""
    style = con.execute(f"""
        WITH
        t AS (
            SELECT match_id, team_id, player_id, var_pop(x) * count(*) AS within_x,
                   var_pop(y) * count(*) AS within_y
            FROM events WHERE {TOUCH} GROUP BY ALL),
        p AS (
            SELECT match_id, team_id, player_id, sum(length) AS pass_length,
                   count(*) FILTER (WHERE end_x - x > abs(end_y - y)) AS forward_passes,
                   count(*) FILTER (WHERE x - end_x > abs(end_y - y)) AS backward_passes,
                   count(*) FILTER (WHERE height = 'High Pass') AS high_passes,
                   count(*) FILTER (WHERE body_part = 'Left Foot') AS left_foot_passes,
                   count(*) FILTER (WHERE body_part IN ('Left Foot', 'Right Foot'))
                       AS foot_passes,
                   count(*) FILTER (WHERE body_part IN ('Left Foot', 'Right Foot') AND {WIDE})
                       AS wide_foot_passes,
                   count(*) FILTER (WHERE (y < 18 AND body_part = 'Right Foot')
                                       OR (y > 62 AND body_part = 'Left Foot'))
                       AS inside_foot_passes
            FROM passes WHERE {OPEN_PLAY} GROUP BY ALL),
        c AS (
            SELECT match_id, team_id, player_id,
                   sum(sqrt((end_x - x) ** 2 + (end_y - y) ** 2)) AS carry_distance
            FROM carries GROUP BY ALL)
        SELECT pm.match_id, pm.team_id, pm.player_id,
               t.* EXCLUDE (match_id, team_id, player_id),
               p.* EXCLUDE (match_id, team_id, player_id),
               c.* EXCLUDE (match_id, team_id, player_id)
        FROM player_matches pm
        JOIN matches m USING (match_id)
        LEFT JOIN t USING (match_id, team_id, player_id)
        LEFT JOIN p USING (match_id, team_id, player_id)
        LEFT JOIN c USING (match_id, team_id, player_id)
        WHERE m.scouting_pool AND pm.played
        ORDER BY pm.match_id, pm.team_id, pm.player_id
    """).df()
    for col in style.columns.drop(KEYS):
        integer = pd.api.types.is_integer_dtype(style[col])
        style[col] = style[col].fillna(0).astype("int64" if integer else "float64")
    return style


def group_share(con: duckdb.DuckDBPyConnection, cfg: Config, groups: pd.Series) -> pd.DataFrame:
    """One row per player and pool match played (`profiles.KEYS`): `group_share`, the share of
    the player's time in the match spent in a position of their comparison group (`groups`:
    player id to comparison group code), from `player_positions`."""
    positions = con.execute("""
        SELECT match_id, team_id, player_id, position_group, sum(seconds) AS seconds
        FROM player_positions JOIN matches USING (match_id)
        WHERE scouting_pool GROUP BY ALL
    """).df()
    own = positions.position_group.map(cfg.comparison_group_of()) == positions.player_id.map(groups)
    seconds = positions.assign(own=positions.seconds.where(own, 0.0)).groupby(KEYS)
    share = seconds.own.sum() / seconds.seconds.sum()
    return share.rename("group_share").reset_index()


def touch_map(
    con: duckdb.DuckDBPyConnection, played: pd.DataFrame, *, zone: float = 5.0
) -> pd.DataFrame:
    """Where each player touches the ball in the matches of `played` (`match_id`, `player_id`):
    one row per player, one column per zone of `zone` yards (`row` across the pitch from y = 0,
    `col` along it from x = 0), the share of their touches in it.

    Each match is mirrored across the pitch (y to 80.1 - y) when the player's touches lean to
    y < 40.05 in it, so that every match leans to the same side (the right of a team attacking
    towards x = 120): a side is not a style, and a player who changes flank keeps one map.
    """
    cols, rows = round(120 / zone), round(80 / zone)
    con.register("touch_map_played", played[["match_id", "player_id"]].drop_duplicates())
    counts = con.execute(
        f"""
        WITH t AS (
            SELECT match_id, player_id, x, y
            FROM events JOIN touch_map_played USING (match_id, player_id)
            WHERE {TOUCH}),
        side AS (SELECT match_id, player_id, avg(y) < 40.05 AS mirror FROM t GROUP BY ALL)
        SELECT player_id,
               least(floor(CASE WHEN mirror THEN 80.1 - y ELSE y END / $zone), $rows - 1)::INT
                   AS row,
               least(floor(x / $zone), $cols - 1)::INT AS col,
               count(*) AS n
        FROM t JOIN side USING (match_id, player_id)
        GROUP BY ALL
        """,
        {"zone": zone, "rows": rows, "cols": cols},
    ).df()
    con.unregister("touch_map_played")
    zones = pd.MultiIndex.from_product([range(rows), range(cols)], names=["row", "col"])
    out = counts.pivot_table(index="player_id", columns=["row", "col"], values="n", aggfunc="sum")
    out = out.reindex(columns=zones, fill_value=0).fillna(0.0)
    return out.div(out.sum(axis=1), axis=0)


def _built(sums: pd.DataFrame) -> pd.DataFrame:
    """`sums` with the denominators built from their parts (`_BUILT`)."""
    return sums.assign(**{k: sums[list(parts)].sum(axis=1) for k, parts in _BUILT.items()})


def descriptors(sums: pd.DataFrame) -> pd.DataFrame:
    """The descriptors from summed rows (`SUMMED` columns); NaN when a denominator is 0."""
    s = _built(sums)
    out = pd.DataFrame(
        {k: s[num] / s[den].replace(0, np.nan) for k, (num, den, _) in RATIOS.items()},
        index=sums.index,
    )
    touches = s["touches"].replace(0, np.nan)
    for k, (squares, _) in SPREADS.items():
        out[k] = np.sqrt((s[squares] / touches).clip(lower=0))
    return out[NAMES]


def weights(sums: pd.DataFrame) -> pd.DataFrame:
    """Each descriptor's denominator in summed rows: the weight of a row's value."""
    s = _built(sums)
    out = pd.DataFrame({k: s[den] for k, (_, den, _) in RATIOS.items()}, index=sums.index)
    for k in SPREADS:
        out[k] = s["touches"]
    return out[NAMES].astype(float)


def possession_slopes(rows: pd.DataFrame, groups: pd.Series) -> pd.DataFrame:
    """How much each descriptor moves with the team's share of possession, within players.

    `rows` has one row per player and match with the `SUMMED` columns and `own_seconds` and
    `opp_seconds` (`possession.player_possession`); `groups` maps the players fitted on to their
    comparison group. One row per group, one column per descriptor: the weighted least-squares
    slope of each match's value on the share, with a fixed effect per player and the
    descriptor's denominator as weight (a slope of 0.1 is 0.01 per 10 points of possession).
    """
    rows = rows[rows.player_id.isin(groups.index)]
    values, w = descriptors(rows), weights(rows)
    share = rows.own_seconds / (rows.own_seconds + rows.opp_seconds)
    out = {}
    for g, ids in rows.player_id.groupby(rows.player_id.map(groups)):
        slopes = {}
        for m in NAMES:
            d = pd.DataFrame({"player": ids, "w": w.loc[ids.index, m], "x": share.loc[ids.index],
                              "y": values.loc[ids.index, m]})  # fmt: skip
            d = d[d.w > 0].dropna()
            if d.empty:
                slopes[m] = np.nan
                continue
            for c in ("x", "y"):
                total = (d[c] * d.w).groupby(d.player).transform("sum")
                d[c] = d[c] - total / d.w.groupby(d.player).transform("sum")
            slopes[m] = float((d.w * d.x * d.y).sum() / (d.w * d.x**2).sum())
        out[g] = slopes
    return pd.DataFrame(out).T[NAMES].rename_axis("comparison_group")


def adjust(
    values: pd.DataFrame, share: pd.Series, groups: pd.Series, slopes: pd.DataFrame
) -> pd.DataFrame:
    """`values` (descriptors) on an even share of possession: less each group's slope times the
    distance of `share` from it. `share` and `groups` are aligned with `values`; descriptors
    without a slope (a missing one counts as 0) are left as they are."""
    columns = [m for m in values.columns if m in slopes.columns]
    slope = slopes.reindex(groups.to_numpy())[columns].fillna(0.0).to_numpy()
    out = values.copy()
    out[columns] = values[columns] - slope * (share.to_numpy() - REFERENCE_SHARE)[:, None]
    return out

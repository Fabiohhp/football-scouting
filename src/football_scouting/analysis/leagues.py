"""How much of a number the league explains: the test behind pooling the leagues.

`eta_squared` is the share of the variation explained by a label (0 = none, 1 = all).
`league_effect` asks the same of players once their comparison group is accounted for: the
partial η² of league in a linear model with group and league dummies, and how far each league
sits from the average within the same group, in % of the average group mean. `team_effect`
asks it of the team, adjusted for chance: with 80 teams and one to three players per team and
group, teams "explain" about 7% of any number even when it has nothing to do with them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def eta_squared(values: pd.Series, labels: pd.Series) -> float:
    """Share of the variation in `values` explained by the means of `labels`."""
    between = values.groupby(labels).transform("mean")
    return ((between - values.mean()) ** 2).sum() / ((values - values.mean()) ** 2).sum()


def league_effect(
    d: pd.DataFrame, metric: str, *, league: str = "league", group: str = "group"
) -> dict[str, float]:
    """Partial η² of league given group, and each league's gap within group (%).

    One row per player in `d`; rows with a missing `metric` are left out.
    """
    d = d[[metric, league, group]].dropna()
    rss, _ = _residuals(d[metric], d[group], d[league])
    within = d[metric] - d.groupby(group)[metric].transform("mean")
    pct = within.groupby(d[league]).mean() / d.groupby(group)[metric].mean().mean() * 100
    return {"partial η²": (rss[0] - rss[1]) / rss[0], **pct.to_dict()}


def team_effect(d: pd.DataFrame, metric: str, *, team: str = "team", group: str = "group") -> float:
    """Share of the variation within comparison group that the team explains, beyond chance.

    The partial η² of team given group, adjusted for the number of teams as R² is for the
    number of predictors: 1 - (RSS with teams / its df) / (RSS with groups only / its df).
    About 0 when teams explain no more than chance; the team includes its league. One row per
    player in `d`; rows with a missing `metric` are left out.
    """
    d = d[[metric, team, group]].dropna()
    (rss_group, rss_team), (df_group, df_team) = _residuals(d[metric], d[group], d[team])
    return 1 - (rss_team / df_team) / (rss_group / df_group)


def _residuals(
    values: pd.Series, groups: pd.Series, labels: pd.Series
) -> tuple[tuple[float, float], tuple[int, int]]:
    """Residual sums of squares and degrees of freedom: group dummies, then group + label."""
    y = values.to_numpy(float)
    groups_only = pd.get_dummies(groups).to_numpy(float)
    with_labels = np.hstack([groups_only, pd.get_dummies(labels, drop_first=True).to_numpy(float)])
    rss, dfs = [], []
    for x in (groups_only, with_labels):
        rss.append(((y - x @ np.linalg.lstsq(x, y, rcond=None)[0]) ** 2).sum())
        dfs.append(len(y) - np.linalg.matrix_rank(x))
    return (rss[0], rss[1]), (dfs[0], dfs[1])

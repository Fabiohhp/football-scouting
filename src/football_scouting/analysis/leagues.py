"""How much of a number the league explains: the test behind pooling the leagues.

`eta_squared` is the share of the variation explained by a label (0 = none, 1 = all).
`league_effect` asks the same of players once their comparison group is accounted for: the
partial η² of league in a linear model with group and league dummies, and how far each league
sits from the average within the same group, in % of the average group mean.
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
    y = d[metric].to_numpy(float)
    groups_only = pd.get_dummies(d[group]).to_numpy(float)
    with_league = np.hstack(
        [groups_only, pd.get_dummies(d[league], drop_first=True).to_numpy(float)]
    )
    rss = [
        ((y - x @ np.linalg.lstsq(x, y, rcond=None)[0]) ** 2).sum()
        for x in (groups_only, with_league)
    ]
    within = d[metric] - d.groupby(group)[metric].transform("mean")
    pct = within.groupby(d[league]).mean() / d.groupby(group)[metric].mean().mean() * 100
    return {"partial η²": (rss[0] - rss[1]) / rss[0], **pct.to_dict()}

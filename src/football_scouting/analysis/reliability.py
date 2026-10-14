"""How many minutes before a per-90 number reflects the player rather than chance.

Split-half reliability with random match samples: for each draw, every player's matches are
shuffled and dealt alternately into two halves; each half then takes matches in that order
until it holds at least M minutes. Across players who reach M minutes in both halves, the
correlation between the two halves' rates estimates the reliability of a rate measured over
M minutes. Rates are centred within each player's context (e.g. comparison group and league)
first, so the correlation measures differences between comparable players, not between roles.

The budget can be another count than minutes: for a per-shot ratio such as finishing, each
half takes matches until it holds at least M shots, and K is then in shots.

Random samples rather than first vs second half of the season: a chronological split mixes
noise with real change (form, injuries, new coach, transfers).

Reliability follows r(M) = M / (M + K) closely (the Spearman-Brown form): K is the number of
minutes at which a rate is half signal, half noise, and M / (M + K) is also the weight an
empirical-Bayes estimate gives a player's own rate against the group mean.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

from football_scouting.analysis.metrics import SUMMED, rates


def split_half_reliability(
    counts: pd.DataFrame,
    context: pd.Series,
    metrics: Sequence[str],
    minutes: Sequence[float],
    *,
    draws: int = 50,
    seed: int = 2016,
    budget: str = "minutes",
) -> pd.DataFrame:
    """One row per draw and target: players used, mean budget per half, r per metric.

    `counts` has one row per player and match (`player_id` and the `SUMMED` columns, as from
    `player_match_counts`); `context` maps player_id to the label rates are centred within.
    `minutes` are the targets, in units of the `budget` column (minutes unless set).
    """
    rng = np.random.default_rng(seed)
    rows = []
    for draw in range(draws):
        d = counts.assign(key=rng.random(len(counts))).sort_values(["player_id", "key"])
        d["half"] = d.groupby("player_id").cumcount() % 2
        d["cum"] = d.groupby(["player_id", "half"])[budget].cumsum()
        for target in minutes:
            # Matches each half needs to reach the target, in shuffled order.
            sums = d[d["cum"] - d[budget] < target].groupby(["player_id", "half"])
            sums = sums[SUMMED].sum()
            per_half = sums[budget].unstack("half")
            ok = per_half.index[per_half.ge(target).all(axis=1)]
            r = rates(sums.loc[sums.index.get_level_values("player_id").isin(ok)])
            ctx = context.reindex(r.index.get_level_values("player_id")).to_numpy()
            half = r.index.get_level_values("half").to_numpy()
            centred = r[list(metrics)] - r[list(metrics)].groupby([ctx, half]).transform("mean")
            a, b = centred.xs(0, level="half"), centred.xs(1, level="half")
            row = {
                "draw": draw,
                "target": target,
                "players": len(ok),
                budget: per_half.loc[ok].to_numpy().mean(),
            }
            rows.append(row | {m: a[m].corr(b[m]) for m in metrics})
    return pd.DataFrame(rows)


def stabilisation_minutes(
    curve: pd.DataFrame, metrics: Sequence[str], *, budget: str = "minutes"
) -> pd.Series:
    """K per metric, fitting r = M / (M + K) to the mean curve (`budget` vs r)."""
    mean = curve.groupby("target")[[budget, *metrics]].mean()
    out = {}
    for m in metrics:
        (k,), _ = curve_fit(lambda x, k: x / (x + k), mean[budget], mean[m], p0=[500.0])
        out[m] = k
    return pd.Series(out, name="K")


def minutes_for(reliability: float, k: pd.Series) -> pd.Series:
    """Minutes of data needed to reach `reliability`, from K."""
    return k * reliability / (1 - reliability)

"""The recruitment back-test: did the players a ranking put first do better than players of their
age?

A ranking (the gap of `analysis.market`, or a baseline such as minutes or value) picks the top
share, or a set number, of each comparison group (`pick_weights`); the pick is judged by its
players' mean outcome
(`analysis.outcomes`; `pick_means` for several rankings at once), set against other rankings'
picks of the same size. Ties at the edge of a pick (round values, teammates sharing their team's
strength) share the places left, which is the pick a random tie-break would make on average.
`lexicographic` orders by several keys, the later ones breaking the earlier ones' ties.
`chance` gives the mean of every pick of a set number from a pool: where a single pick of that
size stands against picking at random (notebook 08, section 5).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from itertools import combinations

import numpy as np
import pandas as pd


def pick_weights(
    key: pd.Series, groups: pd.Series, share: float | None = None, places: int | None = None
) -> pd.Series:
    """Each row's weight in a pick of the top of its group by `key` (higher first).

    A group of n rows has round(`share` × n) places, or `places` places (all n rows when fewer):
    rows above the edge weigh 1, rows below 0, and the rows tied at the edge share the places
    left equally. Give `share` or `places`, not both. `key` has no missing values.
    """
    if (share is None) == (places is None):
        raise ValueError("give either share or places")
    weights = pd.Series(0.0, index=key.index)
    for _, k in key.groupby(groups, observed=True):
        n = round(share * len(k)) if places is None else min(places, len(k))
        if n == 0:
            continue
        edge = k.nlargest(n).iloc[-1]
        above, tied = k.index[k > edge], k.index[k == edge]
        weights[above] = 1.0
        weights[tied] = (n - len(above)) / len(tied)
    return weights


def lexicographic(*keys: pd.Series) -> pd.Series:
    """A key (higher first) that orders rows by the first of `keys`, then the next, and so on;
    rows equal on every key stay tied."""
    frame = pd.concat(keys, axis=1, keys=range(len(keys)))
    return frame.apply(tuple, axis=1).rank(method="dense")


def pick_mean(values: pd.Series, weights: pd.Series) -> float:
    """The mean of `values` over a pick (`pick_weights`)."""
    return float(np.average(values, weights=weights))


def pick_means(
    data: pd.DataFrame,
    keys: Mapping[str, Callable[[pd.DataFrame], pd.Series]],
    outcome: str,
    share: float | None = None,
    groups: str = "comparison_group",
    places: int | None = None,
) -> pd.Series:
    """The mean `outcome` of each ranking's pick of the top `share` (or `places`) of each group:
    `keys` maps a name to a function of `data` that returns the ranking's key, so that a resample
    of `data` (`market.team_bootstrap`, rows repeated) is ranked afresh."""
    data = data.reset_index(drop=True)
    return pd.Series(
        {
            name: pick_mean(
                data[outcome], pick_weights(key(data), data[groups], share=share, places=places)
            )
            for name, key in keys.items()
        }
    )


def chance(values: pd.Series, n: int) -> np.ndarray:
    """The mean of `values` over every pick of `n` of them, each pick equally likely: the means
    picking `n` at random would give."""
    picks = np.array(list(combinations(values.to_numpy(dtype=float), n)))
    return picks.mean(axis=1)

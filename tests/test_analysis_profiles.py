import numpy as np
import pandas as pd
import pytest

from football_scouting.analysis.metrics import SUMMED
from football_scouting.analysis.profiles import (
    adjusted_rates,
    compared_players,
    percentiles,
    recording_context,
    recording_factors,
    rescale,
    shrink,
)
from football_scouting.config import load_config

CFG = load_config()  # 900 minutes, or 450 under 23; the Premier League changes on 2015-12-28


def test_compared_players_follow_the_minutes_rules():
    players = pd.DataFrame(
        [
            (1, "CB", 900, 30.0),  # in
            (2, "CB", 899, 30.0),  # short of 900
            (3, "FB", 450, 22.9),  # in, young
            (4, "FB", 449, 20.0),  # short of 450
            (5, "CF", 600, 23.0),  # not under 23
            (6, "CM", 600, np.nan),  # no date of birth: not known to be under 23
            (7, "GK", 3000, 28.0),  # no profile
        ],
        columns=["player_id", "comparison_group", "minutes", "age"],
    )
    out = compared_players(players, CFG).set_index("player_id")
    assert out.index.tolist() == [1, 3]
    assert out.young.tolist() == [False, True]


def test_recording_context_splits_the_changed_league():
    counts = pd.DataFrame({
        "competition_id": [2, 2, 11],
        "match_date": pd.to_datetime(["2015-12-27", "2015-12-28", "2016-01-10"]),
    })  # fmt: skip
    assert recording_context(counts, CFG).tolist() == [
        "Premier League before 2015-12-28", "Premier League from 2015-12-28", "La Liga",
    ]  # fmt: skip


def test_recording_factors_bring_each_context_to_the_group_rate():
    counts = pd.DataFrame({
        "player_id": [1, 1, 2, 3],
        "minutes": [90.0, 90.0, 90.0, 90.0],
        "interceptions": [2, 2, 8, 5],  # contexts A, A, B for the group; player 3 has none
    })  # fmt: skip
    context = pd.Series(["A", "A", "B", "B"])
    groups = pd.Series({1: "CB", 2: "CB"})
    factors = recording_factors(counts, groups, context, ("interceptions",))
    # Group rate: 12 per 270 minutes = 4 per 90; context A 2 per 90, B 8 per 90.
    assert factors.set_index("context").factor.to_dict() == pytest.approx({"A": 2.0, "B": 0.5})
    out = rescale(counts, groups, context, factors)
    assert out.interceptions.tolist() == pytest.approx([4, 4, 4, 5])  # player 3 as recorded


def test_adjusted_rates_use_each_groups_elasticity():
    sums = pd.DataFrame(0.0, index=[1, 2], columns=[*SUMMED, "own_seconds", "opp_seconds"])
    sums[["minutes", "passes", "tackles", "own_seconds", "opp_seconds"]] = [90, 60, 3, 60, 40]
    beta = pd.DataFrame(
        [("CB", "passes", 1.0), ("CB", "tackles", 1.0), ("FB", "passes", 0.0)],
        columns=["comparison_group", "statistic", "elasticity"],
    )
    out = adjusted_rates(sums, pd.Series(["CB", "FB"], index=[1, 2]), beta)
    assert out.passes.tolist() == pytest.approx([50, 60])  # 60% of the ball, elasticity 1 and 0
    assert out.tackles.tolist() == pytest.approx([3.75, 3])  # on the opponent's 40%; FB: none


def test_shrink_pulls_towards_the_minutes_weighted_mean():
    values = pd.DataFrame({
        "comparison_group": "CB", "statistic": "passes",
        "minutes": [900.0, 2700.0, 600.0], "adjusted": [30.0, 50.0, np.nan],
    })  # fmt: skip
    statistics = pd.DataFrame({"comparison_group": ["CB"], "statistic": ["passes"], "k": [900.0]})
    out = shrink(values, statistics)
    assert out.group_mean.tolist() == pytest.approx([45, 45, 45])  # (30 x 900 + 50 x 2700) / 3600
    assert out.weight.tolist() == pytest.approx([0.5, 0.75, 0])
    assert out.shrunk.tolist() == pytest.approx([37.5, 48.75, 45])


def test_percentiles_put_the_best_at_100():
    values = pd.DataFrame({
        "comparison_group": "CB",
        "statistic": ["passes"] * 4 + ["ball_losses_per_touch"] * 2,
        "shrunk": [1, 2, 2, 3, 0.1, 0.2],
    })  # fmt: skip
    assert percentiles(values).tolist() == [25, 62.5, 62.5, 100, 100, 50]

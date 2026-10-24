import numpy as np
import pandas as pd
import pytest

from football_scouting.analysis.metrics import SUMMED
from football_scouting.analysis.profiles import (
    VALUE_SUMS,
    adjusted_rates,
    compared_players,
    percentiles,
    possession_effects,
    profile_rates,
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


def sums_with_values() -> pd.DataFrame:
    """Two players, 90 minutes each, their teams with 60% and 40% of the ball."""
    sums = pd.DataFrame(
        0.0, index=[1, 2], columns=[*SUMMED, "own_seconds", "opp_seconds", *VALUE_SUMS]
    )
    sums[["minutes", "own_seconds", "opp_seconds"]] = [[90, 60, 40], [90, 40, 60]]
    sums[["xt", "xpass_passes", "xpass_completed", "xpass_expected"]] = [
        [0.2, 50, 42, 40.0], [0.1, 20, 15, 16.0],
    ]  # fmt: skip
    return sums


def test_profile_rates_add_the_possession_value_numbers():
    r = profile_rates(sums_with_values())
    assert r.xt.tolist() == pytest.approx([0.2, 0.1])  # per 90
    assert r.completion_above_expected.tolist() == pytest.approx([0.04, -0.05])
    assert "xt" not in profile_rates(sums_with_values().drop(columns="xt"))


def test_adjusted_rates_put_xt_and_completion_above_expected_on_an_even_share():
    effects = pd.DataFrame({
        "comparison_group": "CM", "statistic": ["xt", "completion_above_expected"],
        "elasticity": [2.0, np.nan], "slope": [np.nan, 0.1],
    })  # fmt: skip
    out = adjusted_rates(sums_with_values(), pd.Series("CM", index=[1, 2]), effects)
    assert out.xt.tolist() == pytest.approx([0.2 * (5 / 6) ** 2, 0.1 * (5 / 4) ** 2])
    # Less 0.1 x (share - 0.5): one point less at 60% of the ball, one more at 40%.
    assert out.completion_above_expected.tolist() == pytest.approx([0.03, -0.04])


def test_possession_effects_fit_the_slope_of_completion_above_expected_within_players():
    rng = np.random.default_rng(3)
    n = 400
    player = np.repeat(np.arange(20), n // 20)
    share = rng.uniform(0.3, 0.7, n)
    passes = rng.integers(20, 60, n).astype(float)
    above = 0.05 * (player % 3) + 0.1 * (share - 0.5)  # each player's own level, then the slope
    counts = pd.DataFrame({
        "player_id": player, "minutes": 90.0, "own_seconds": share, "opp_seconds": 1 - share,
        "xt": rng.poisson(10 * share), "xpass_passes": passes,
        "xpass_completed": 0.8 * passes + above * passes, "xpass_expected": 0.8 * passes,
    })  # fmt: skip
    groups = pd.Series("CM", index=np.arange(20))
    out = possession_effects(
        counts, groups, {"CM": ("xt", "completion_above_expected", "xg_per_shot")}
    )
    out = out.set_index("statistic")
    assert out.index.tolist() == ["xt", "completion_above_expected"]  # a ratio has none
    assert out.loc["completion_above_expected", "slope"] == pytest.approx(0.1)
    assert out.loc["xt", "elasticity"] == pytest.approx(1, abs=0.15)  # counts in proportion
    assert out.side.tolist() == ["with", "with"]


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

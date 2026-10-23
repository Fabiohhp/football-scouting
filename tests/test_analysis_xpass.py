import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

from football_scouting.analysis.xpass import (
    FEATURES,
    LEAKS,
    adjust_above_expected,
    completion_rates,
    expected_completion,
    match_folds,
    player_match_passes,
    possession_slope,
)


def test_features_leave_the_leaks_out():
    assert not set(FEATURES) & set(LEAKS)


def test_folds_keep_each_match_together():
    match_id = pd.Series(np.repeat(np.arange(23), 4))
    fold = match_folds(match_id, k=5)
    assert pd.Series(fold).groupby(match_id).nunique().eq(1).all()
    assert sorted(pd.Series(fold).groupby(match_id).first().value_counts()) == [4, 4, 5, 5, 5]
    assert (match_folds(match_id, k=5) == fold).all()  # the same deal every time


def passes(n_matches=40, per_match=50, seed=0):
    """Passes from the own half are completed 90% of the time, from the other half 60%."""
    rng = np.random.default_rng(seed)
    n = n_matches * per_match
    x = rng.uniform(0, 120, n)
    return pd.DataFrame(
        {
            "match_id": np.repeat(np.arange(n_matches), per_match),
            "x": x,
            "completed": rng.random(n) < np.where(x < 60, 0.9, 0.6),
        }
    )


def test_expected_completion_comes_from_other_matches():
    p = passes()
    model = LogisticRegression
    before = expected_completion(p, ["x"], model=model)
    assert ((before > 0) & (before < 1)).all()
    assert before[p.x < 30].mean() > before[p.x > 90].mean()
    # A match's own outcomes never reach the model that scores it.
    flipped = p.assign(completed=np.where(p.match_id == 7, ~p.completed, p.completed))
    after = expected_completion(flipped, ["x"], model=model)
    own = (p.match_id == 7).to_numpy()
    assert after[own] == pytest.approx(before[own])
    assert not np.allclose(after[~own], before[~own])


def test_player_sums_and_rates():
    p = pd.DataFrame(
        {
            "match_id": [1, 1, 1, 2],
            "team_id": [10, 10, 10, 10],
            "player_id": [5, 5, 6, 5],
            "completed": [True, False, True, True],
        }
    )
    sums = player_match_passes(p, np.array([0.9, 0.5, 0.8, 0.7]))
    assert sums.passes.tolist() == [2, 1, 1]
    assert sums.completed.tolist() == [1, 1, 1]
    assert sums.expected.tolist() == pytest.approx([1.4, 0.8, 0.7])
    rates = completion_rates(sums)
    assert rates.completion.tolist() == pytest.approx([0.5, 1.0, 1.0])
    assert rates.expected.tolist() == pytest.approx([0.7, 0.8, 0.7])
    assert rates.above_expected.tolist() == pytest.approx([-0.2, 0.2, 0.3])


def test_possession_slope_is_within_players():
    # Better players at teams with more of the ball (a between-player slope of about 0.6),
    # each completing 0.1 more per unit of share from match to match.
    rng = np.random.default_rng(1)
    players = np.repeat(np.arange(30), 20)
    skill = np.linspace(-0.05, 0.05, 30)[players]
    share = 0.5 + 10 * skill + rng.uniform(-0.1, 0.1, len(players))
    passes = rng.integers(20, 60, len(players))
    above = skill + 0.1 * (share - 0.5)
    sums = pd.DataFrame(
        {"player_id": players, "passes": passes, "completed": above * passes, "expected": 0.0}
    )
    assert possession_slope(sums, pd.Series(share)) == pytest.approx(0.1)
    adjusted = adjust_above_expected(pd.Series(above), pd.Series(share), 0.1)
    assert adjusted.to_numpy() == pytest.approx(skill)

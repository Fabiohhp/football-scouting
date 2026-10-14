import numpy as np
import pandas as pd
import pytest

from football_scouting.analysis.metrics import SUMMED
from football_scouting.analysis.reliability import (
    minutes_for,
    split_half_reliability,
    stabilisation_minutes,
)


def synthetic_counts(true_rates: np.ndarray, matches: int = 30, seed: int = 0) -> pd.DataFrame:
    """Full 90-minute matches with Poisson shot counts at each player's true rate."""
    rng = np.random.default_rng(seed)
    n = len(true_rates)
    df = pd.DataFrame(0, index=range(n * matches), columns=SUMMED)
    df["player_id"] = np.repeat(np.arange(n), matches)
    df["minutes"] = 90.0
    df["shots"] = rng.poisson(np.repeat(true_rates, matches))
    return df


def test_reliability_matches_theory():
    # Rates uniform on [0.5, 4]: K = 90 * mean / variance = 90 * 2.25 / (3.5**2 / 12) = 198.
    true_rates = np.random.default_rng(1).uniform(0.5, 4, 600)
    counts = synthetic_counts(true_rates)
    context = pd.Series("all", index=np.arange(len(true_rates)))
    curve = split_half_reliability(counts, context, ["shots"], [180, 450, 900], draws=5)
    k = stabilisation_minutes(curve, ["shots"])["shots"]
    assert k == pytest.approx(198, rel=0.2)
    assert minutes_for(0.5, pd.Series([k]))[0] == pytest.approx(k)


def test_no_signal_gives_no_reliability():
    counts = synthetic_counts(np.full(600, 2.0))
    context = pd.Series("all", index=np.arange(600))
    curve = split_half_reliability(counts, context, ["shots"], [450, 900], draws=5)
    assert curve["shots"].abs().mean() < 0.05
    assert (curve["players"] == 600).all()


def test_reliability_in_shots_for_a_per_shot_ratio():
    # Conversion uniform on [0.05, 0.25] at 0.1 xG per shot: finishing = goals / shots - 0.1,
    # K = E[p(1 - p)] / Var(p) = 0.124167 / 0.003333 = 37 shots.
    rng = np.random.default_rng(2)
    n, matches = 600, 30
    conversion = np.repeat(rng.uniform(0.05, 0.25, n), matches)
    counts = synthetic_counts(np.full(n, 3.0), matches, seed=3)
    counts["goals"] = rng.binomial(counts["shots"], conversion)
    counts["xg"] = counts["shots"] * 0.1
    counts["goals_minus_xg"] = counts["goals"] - counts["xg"]
    context = pd.Series("all", index=np.arange(n))
    curve = split_half_reliability(
        counts, context, ["finishing"], [10, 20, 40], draws=5, budget="shots"
    )
    assert curve["shots"].ge(10).all()  # mean shots per half, at least the target
    k = stabilisation_minutes(curve, ["finishing"], budget="shots")["finishing"]
    assert k == pytest.approx(37, rel=0.25)

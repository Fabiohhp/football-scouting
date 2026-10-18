import numpy as np
import pandas as pd
import pytest

from football_scouting.analysis.leagues import eta_squared, league_effect, team_effect


def test_eta_squared_is_the_share_explained_by_the_label():
    labels = pd.Series(["a", "a", "b", "b"])
    assert eta_squared(pd.Series([1.0, 1.0, 3.0, 3.0]), labels) == pytest.approx(1.0)
    assert eta_squared(pd.Series([1.0, 3.0, 1.0, 3.0]), labels) == pytest.approx(0.0)


def test_league_effect_within_comparison_group():
    # Two groups (means 10 and 20), two leagues: A one unit above its group, B one below.
    d = pd.DataFrame(
        {
            "group": ["g1", "g1", "g2", "g2"] * 2,
            "league": ["A", "B"] * 4,
            "rate": [11.0, 9.0, 21.0, 19.0] * 2,
        }
    )
    out = league_effect(d, "rate")
    assert out["partial η²"] == pytest.approx(1.0)  # league explains all that group leaves
    assert out["A"] == pytest.approx(100 / 15) and out["B"] == pytest.approx(-100 / 15)

    # The group alone explains the rate: league adds nothing.
    noise = np.array([0.5, 0.5, -0.5, -0.5, -0.5, -0.5, 0.5, 0.5])  # 0 per league in each group
    d["rate"] = np.where(d.group == "g1", 10.0, 20.0) + noise
    assert league_effect(d, "rate")["partial η²"] == pytest.approx(0.0, abs=1e-12)


def test_league_effect_skips_missing_values():
    d = pd.DataFrame(
        {"group": ["g"] * 4, "league": ["A", "A", "B", "B"], "rate": [1.0, np.nan, 3.0, 3.0]}
    )
    assert league_effect(d, "rate")["A"] == pytest.approx(-400 / 7)  # (1 - 7/3) / (7/3)


def test_team_effect_is_adjusted_for_chance():
    # 60 teams with two players in each of two groups.
    rng = np.random.default_rng(0)
    d = pd.DataFrame({"team": np.repeat(np.arange(60), 4), "group": ["g1", "g1", "g2", "g2"] * 60})
    strength = rng.normal(size=60)
    d["shared"] = 5 * (d.group == "g2") + np.repeat(strength, 4) + rng.normal(size=len(d))
    d["unrelated"] = 5 * (d.group == "g2") + rng.normal(size=len(d))
    # Team variance 1, player variance 1: the team explains half of what the group leaves.
    assert team_effect(d, "shared") == pytest.approx(0.5, abs=0.1)
    assert team_effect(d, "unrelated") == pytest.approx(0.0, abs=0.06)

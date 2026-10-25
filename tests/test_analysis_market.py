import duckdb
import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LinearRegression

from football_scouting.analysis.market import (
    out_of_fold,
    partial,
    profile_matrix,
    team_bootstrap,
    team_folds,
    team_strength,
    value_model,
)


def test_team_strength_counts_points_and_goal_difference_per_match():
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE matches AS SELECT * FROM (VALUES "
        "(1, 2, 2, 0, true), (2, 1, 1, 1, true), (1, 3, 0, 5, false)) "
        "t(home_team_id, away_team_id, home_score, away_score, scouting_pool)"
    )
    out = team_strength(con).set_index("team_id")
    assert out.matches.tolist() == [2, 2]  # the match outside the pool is left out
    assert out.points.tolist() == [2.0, 0.5]
    assert out.goal_difference.tolist() == [1.0, -1.0]


def test_profile_matrix_standardises_within_the_group_in_profile_order():
    values = pd.DataFrame(
        {
            "player_id": [1, 1, 2, 2, 3, 3, 9],
            "comparison_group": ["CB"] * 6 + ["CF"],
            "statistic": ["tackles", "passes"] * 3 + ["xg"],
            "shrunk": [1.0, 10.0, 2.0, 20.0, 3.0, 60.0, 0.5],
        }
    )
    out = profile_matrix(values, "CB", ["passes", "tackles"])
    assert out.columns.tolist() == ["passes", "tackles"] and out.index.tolist() == [1, 2, 3]
    assert out.tackles.tolist() == pytest.approx([-1.0, 0.0, 1.0])
    assert out.mean().abs().max() < 1e-12 and np.allclose(out.std(), 1.0)


def test_value_model_fits_a_curve_in_age_and_straight_lines_in_the_rest():
    rng = np.random.default_rng(0)
    X = pd.DataFrame({"age": rng.uniform(18, 36, 400), "minutes": rng.uniform(0, 3, 400)})
    y = 1 + 0.5 * X.minutes - 0.02 * (X.age - 26) ** 2 + rng.normal(0, 0.01, 400)
    model = value_model(["age", "minutes"]).fit(X, y)
    assert model.score(X, y) > 0.99


def test_team_folds_keep_a_teams_players_together():
    teams = np.repeat(np.arange(12), 3)
    folds = team_folds(teams, 4, seed=1)
    assert all(len(set(folds[teams == t])) == 1 for t in range(12))
    assert np.bincount(folds).tolist() == [9, 9, 9, 9]  # three teams each
    assert (folds == team_folds(teams, 4, seed=1)).all()
    assert (folds != team_folds(teams, 4, seed=2)).any()


class SeenTeams:
    """Predicts 1 for a row whose team it was fitted on, 0 otherwise."""

    def fit(self, X, y):
        self.teams = set(X.team)
        return self

    def predict(self, X):
        return X.team.isin(self.teams).astype(float).to_numpy()


def test_out_of_fold_never_predicts_a_player_with_a_model_that_saw_the_team():
    X = pd.DataFrame({"team": np.repeat(np.arange(10), 4)})
    y = np.arange(40.0)
    r2, predictions = out_of_fold(SeenTeams, X, y, X.team, n_folds=5, repeats=3)
    assert (predictions == 0).all() and len(r2) == 3


def test_out_of_fold_r2_is_measured_on_the_held_out_rows():
    rng = np.random.default_rng(0)
    X = pd.DataFrame({"x": rng.normal(size=200)})
    y = 2 * X.x + rng.normal(0, 1, 200)
    r2, predictions = out_of_fold(LinearRegression, X, y, np.arange(200) // 4, repeats=2)
    assert 0.7 < r2.mean() < 0.85  # about 4 / 5 explained
    assert np.corrcoef(predictions, X.x)[0, 1] > 0.99


def test_team_bootstrap_draws_whole_teams():
    teams = np.array([7, 7, 7, 8, 9, 9])
    size = {7: 3, 8: 1, 9: 2}

    def sizes(rows):
        counts = pd.Series(teams[rows]).value_counts()
        whole = all(n % size[t] == 0 for t, n in counts.items())
        return pd.Series({"rows": len(rows), "whole": whole})

    out = team_bootstrap(sizes, teams, draws=50, seed=0)
    assert len(out) == 50 and out.whole.all()
    assert out.rows.between(3, 9).all() and out.rows.nunique() > 1


def test_partial_moves_one_column_with_the_others_at_their_mean():
    X = pd.DataFrame({"a": [0.0, 1.0, 2.0, 3.0], "b": [1.0, 1.0, 3.0, 3.0]})
    model = LinearRegression().fit(X, 1 + 2 * X.a - X.b)
    assert partial(model, X, "a", [0.0, 10.0]) == pytest.approx([1 - 2.0, 1 + 20 - 2.0])

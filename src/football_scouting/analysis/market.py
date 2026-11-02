"""What the market paid for: the profiled players' values on the back-test's market view.

A club deciding on `backtest.market_view` (30 June 2016) could see each player's 2015/16
season and their Transfermarkt value (`values.value_at`). `market_players` puts the two side by
side, one row per profiled player, with the strength of the player's team (`team_strength`:
points and goal difference per match in its league). Later values are outcomes and never enter
this module.

Values are modelled on the log scale, one comparison group at a time, by a ridge regression
(`value_model`): age through a cubic spline, the other columns as they are, all standardised,
the penalty chosen by cross-validation on the training rows. `out_of_fold` checks a model on
players it was not fitted on, with folds that keep a team's players together (`team_folds`), so
that no player is predicted by a model that saw a teammate; `team_bootstrap` resamples whole
teams for intervals. `partial` reads a fitted model one column at a time, the others at their
mean.

A player's gap (`gap`, notebook 04) is the model's out-of-sample prediction of their log value less
the log of their value: positive for a player valued below what their age, minutes, league, team
and profile would have fetched. The back-test reads the gap within team first (the model with the
team's goal difference per match); without it, the gap across teams.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import duckdb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import RidgeCV
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import SplineTransformer, StandardScaler

from football_scouting.analysis.values import pool_valuations, value_at
from football_scouting.config import Config

ALPHAS = np.logspace(-2, 3, 26)
TEAM = ("points", "goal_difference")


def team_strength(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """One row per team of the scouting pool: `matches`, and `points` and `goal_difference` per
    match."""
    return con.execute("""
        WITH sides AS (
            SELECT home_team_id AS team_id, home_score - away_score AS goal_difference
            FROM matches WHERE scouting_pool
            UNION ALL
            SELECT away_team_id, away_score - home_score
            FROM matches WHERE scouting_pool)
        SELECT team_id, count(*) AS matches,
               avg(CASE WHEN goal_difference > 0 THEN 3 WHEN goal_difference = 0 THEN 1
                        ELSE 0 END) AS points,
               avg(goal_difference) AS goal_difference
        FROM sides
        GROUP BY team_id
        ORDER BY team_id
    """).df()


def market_players(con: duckdb.DuckDBPyConnection, cfg: Config) -> pd.DataFrame:
    """One row per profiled player (`profile_players`) with what a club could see on the market
    view.

    Adds `team_id`, the pool team the player played the most minutes for; `team_points` and
    `team_goal_difference`, per match, of the player's pool teams weighted by their minutes in
    each; and the latest valuation on `backtest.market_view`: `value` (euros), `value_date`,
    `value_age_days` and `club`, the club at that valuation.
    """
    players = con.sql("SELECT * FROM profile_players").df()
    stints = con.execute("""
        SELECT ps.player_id, ps.team_id, ps.minutes
        FROM player_seasons ps JOIN competitions c USING (competition_id, season_id)
        WHERE c.scouting_pool AND ps.matches_played > 0
    """).df()
    stints = stints[stints.player_id.isin(players.player_id)].merge(team_strength(con))
    share = stints.minutes / stints.groupby("player_id").minutes.transform("sum")
    team = stints[list(TEAM)].mul(share, axis=0).groupby(stints.player_id).sum().add_prefix("team_")
    team.insert(0, "team_id", stints.set_index("team_id").groupby("player_id").minutes.idxmax())
    value = value_at(pool_valuations(con), cfg.backtest.market_view)
    value = value.rename(columns={"date": "value_date", "age_days": "value_age_days"})
    value = value[["value", "value_date", "value_age_days", "club"]]
    return players.join(team, on="player_id").join(value, on="player_id")


def profile_matrix(
    values: pd.DataFrame, group: str, statistics: Sequence[str], column: str = "shrunk"
) -> pd.DataFrame:
    """The group's players (index `player_id`) by profile statistic, in the order given: `column`
    of `profile_values`, standardised within the group (mean 0, standard deviation 1)."""
    d = values[values.comparison_group == group].pivot(
        index="player_id", columns="statistic", values=column
    )[list(statistics)]
    return (d - d.mean()) / d.std()


def value_model(columns: Sequence[str], spline: Sequence[str] = ("age",)) -> Pipeline:
    """Ridge regression on `columns`: those in `spline` through a cubic spline with four knots,
    the rest as they are, all standardised; the penalty chosen among `ALPHAS` by leave-one-out
    cross-validation on the training rows."""
    curved = [c for c in columns if c in spline]
    straight = [c for c in columns if c not in spline]
    transform = ColumnTransformer(
        [(c, SplineTransformer(n_knots=4, degree=3), [c]) for c in curved]
        + [("as_is", "passthrough", straight)]
    )
    return make_pipeline(transform, StandardScaler(), RidgeCV(alphas=ALPHAS))


def team_folds(teams: Sequence, n_folds: int, seed: int = 0) -> np.ndarray:
    """A fold (0 to `n_folds` - 1) for each row, every row of a team in the same fold: the teams
    are shuffled and dealt to the folds in turn."""
    teams = np.asarray(teams)
    unique = np.unique(teams)
    order = np.random.default_rng(seed).permutation(len(unique))
    fold_of = dict(zip(unique[order], np.arange(len(unique)) % n_folds, strict=True))
    return np.array([fold_of[t] for t in teams])


def out_of_fold(
    make: Callable[[], object],
    X: pd.DataFrame,
    y: Sequence[float],
    teams: Sequence,
    *,
    n_folds: int = 10,
    repeats: int = 20,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Every row predicted by a model (`make()`, fitted on the other folds) that never saw its
    team, over `repeats` random splits of the teams (`team_folds`).

    Returns the R² of each repeat and each row's prediction averaged over the repeats.
    """
    y = np.asarray(y, float)
    predictions = np.empty((repeats, len(y)))
    for r in range(repeats):
        folds = team_folds(teams, n_folds, seed + r)
        for k in range(n_folds):
            test = folds == k
            model = make().fit(X[~test], y[~test])
            predictions[r, test] = model.predict(X[test])
    r2 = 1 - ((predictions - y) ** 2).sum(axis=1) / ((y - y.mean()) ** 2).sum()
    return r2, predictions.mean(axis=0)


def gap(
    players: pd.DataFrame, profile: pd.DataFrame, leagues: Sequence[str], *, team: bool = True
) -> pd.Series:
    """The gap of a comparison group's players: the rows of `profile` (`profile_matrix`; no
    columns for a model without the profile), indexed by `player_id`.

    `players` are rows of `market_players` indexed by `player_id`. The model (`value_model`) reads
    age, minutes, a 0/1 column for each of `leagues` but the first, the team's goal difference per
    match (with `team`) and the profile; each player is predicted out of sample (`out_of_fold`,
    teams held out). Returns the prediction less the log of the player's value.
    """
    rows = players.loc[profile.index]
    X = rows[["age", "minutes"]].assign(
        **{name: (rows.league == name).astype(float) for name in leagues[1:]}
    )
    if team:
        X["team_goal_difference"] = rows.team_goal_difference
    X = X.join(profile)
    y = np.log(rows.value)
    columns = list(X.columns)
    _, predicted = out_of_fold(lambda: value_model(columns), X, y, rows.team_id)
    return pd.Series(predicted - y.to_numpy(), index=profile.index, name="gap")


def team_bootstrap(
    statistic: Callable[[np.ndarray], pd.Series], teams: Sequence, draws: int = 200, seed: int = 0
) -> pd.DataFrame:
    """`statistic(rows)` on `draws` resamples, one row each: as many teams as there are, drawn
    with replacement, each bringing all its rows (positions in `teams`)."""
    teams = np.asarray(teams)
    rows_of = [np.flatnonzero(teams == t) for t in np.unique(teams)]
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(draws):
        picked = rng.integers(len(rows_of), size=len(rows_of))
        out.append(statistic(np.concatenate([rows_of[i] for i in picked])))
    return pd.DataFrame(out)


def partial(model: Pipeline, X: pd.DataFrame, column: str, values: Sequence[float]) -> np.ndarray:
    """The model's prediction with `column` set to each of `values`, the other columns at their
    mean in `X`."""
    grid = pd.DataFrame(np.tile(X.mean().to_numpy(), (len(values), 1)), columns=X.columns)
    grid[column] = values
    return model.predict(grid)

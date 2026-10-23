"""Expected pass completion (xPass): the chance that an open-play pass reaches a teammate.

A gradient-boosted classifier (scikit-learn's `HistGradientBoostingClassifier`) on what is known
when the pass is played (`FEATURES`): where it starts, its direction, its height and the body
part, whether the passer is under pressure, the kinds of pass recorded whatever the outcome
(cross, through ball, cut-back), whether it follows an aerial duel won, a recovery or an
interception, and the phase of play.

Left out because they give the outcome away (`LEAKS`): an incomplete pass ends where the
opponent cut it out, not where it was aimed (`next_opponent_action`), so its end location and
length describe the interception; a switch of play is flagged only when the ball crossed 40
yards, so an intercepted switch is not flagged as one. Also left out: who passes (role, team,
league), so that the expected completion depends on the pass alone.

Passes are those of open play (`metrics.OPEN_PLAY`), without injury clearances, by every player.
`expected_completion` scores each pass with a model fitted on other matches (cross-fitting over
`match_folds`), so that no pass is predicted by a model that saw its match.
`player_match_passes` sums passes, completions and expected completions per player and match;
`completion_rates` turns any sum of its rows into completion, expected completion and
completion above expected (completions less expected completions, per pass).

`possession_slope` measures how much completion above expected rises with the team's share of
possession within players, and `adjust_above_expected` puts it on an even share.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from football_scouting.analysis.metrics import OPEN_PLAY
from football_scouting.analysis.xt import POOL

KEYS = ["match_id", "team_id", "player_id"]
CATEGORICAL = ("height", "body_part", "pass_type", "play_pattern")
FLAGS = ("under_pressure", "cross", "through_ball", "cut_back", "aerial_won")
FEATURES = ("x", "y", "angle", *CATEGORICAL, *FLAGS)
LEAKS = ("end_x", "end_y", "length", "switch")
# The opponent's actions that can end a pass: where the ball was won, blocked or cleared.
CUT_OUT = ("Interception", "Ball Recovery", "Clearance", "Block", "Goal Keeper")


def load_passes(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Open-play passes of the scouting pool, in match order, with `FEATURES`, `LEAKS` and
    `completed`.

    Categorical features as pandas categories (`body_part` "None" when not recorded, which is
    after an aerial duel won; `pass_type` "Regular" for passes that are not a recovery or an
    interception), flags as 0 or 1.
    """
    flags = ", ".join(f'coalesce("{f}", FALSE)::INT AS "{f}"' for f in (*FLAGS, "switch"))
    passes = con.execute(f"""
        SELECT match_id, event_index, team_id, player_id, x, y, angle, height,
               coalesce(body_part, 'None') AS body_part,
               coalesce(pass_type, 'Regular') AS pass_type, play_pattern, {flags},
               end_x, end_y, length, completed
        FROM passes
        WHERE {POOL} AND {OPEN_PLAY} AND outcome IS DISTINCT FROM 'Injury Clearance'
        ORDER BY match_id, event_index
    """).df()
    return passes.astype(dict.fromkeys(CATEGORICAL, "category"))


def next_opponent_action(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Every open-play pass of the pool with the opponent's next action that can end a pass.

    One row per pass (`match_id`, `event_index`, `completed`, `end_x`, `end_y`): the type of
    the opponent's next action in `CUT_OUT` (null when there is none before the end of the
    match), how many events later it comes (`gap`) and its location seen by the passing team
    (`opp_x`, `opp_y`).
    """
    passes = con.execute(f"""
        SELECT match_id, event_index, team_id, end_x, end_y, completed
        FROM passes
        WHERE {POOL} AND {OPEN_PLAY} AND outcome IS DISTINCT FROM 'Injury Clearance'
    """).df()
    cut_out = ", ".join(f"'{t}'" for t in CUT_OUT)
    actions = con.execute(f"""
        SELECT e.match_id, e.event_index AS next_index, e.type AS next_type,
               120.1 - e.x AS opp_x, 80.1 - e.y AS opp_y,
               CASE WHEN e.team_id = m.home_team_id THEN m.away_team_id
                    ELSE m.home_team_id END AS team_id
        FROM events e JOIN matches m USING (match_id)
        WHERE m.scouting_pool AND e.type IN ({cut_out})
    """).df()
    out = pd.merge_asof(
        passes.sort_values("event_index"),
        actions.sort_values("next_index"),
        left_on="event_index",
        right_on="next_index",
        by=["match_id", "team_id"],
        direction="forward",
        allow_exact_matches=False,
    )
    out["gap"] = out.next_index - out.event_index
    columns = ["match_id", "event_index", "completed", "end_x", "end_y"]
    return out[[*columns, "next_type", "gap", "opp_x", "opp_y"]].sort_values(columns[:2])


def match_folds(match_id: pd.Series, k: int = 5, seed: int = 2016) -> np.ndarray:
    """Fold of each row: the matches dealt at random into `k` folds of (almost) equal size."""
    matches = np.sort(match_id.unique())
    order = np.random.default_rng(seed).permutation(matches)
    fold = pd.Series(np.arange(len(order)) % k, index=order)
    return fold.reindex(match_id).to_numpy()


def classifier() -> HistGradientBoostingClassifier:
    """The model: 300 trees of up to 63 leaves, categorical features from their dtype."""
    return HistGradientBoostingClassifier(
        max_iter=300,
        max_leaf_nodes=63,
        early_stopping=False,
        categorical_features="from_dtype",
        random_state=0,
    )


def expected_completion(
    passes: pd.DataFrame,
    features: Sequence[str] = FEATURES,
    *,
    k: int = 5,
    seed: int = 2016,
    model: Callable[[], object] = classifier,
) -> np.ndarray:
    """The chance each pass is completed, from a model fitted on the other folds' matches.

    `passes` has `match_id`, `completed` and the `features`; `model` makes an unfitted
    scikit-learn classifier.
    """
    x = passes[list(features)]
    y = passes["completed"].to_numpy(bool)
    fold = match_folds(passes["match_id"], k, seed)
    out = np.empty(len(passes))
    for f in range(k):
        test = fold == f
        out[test] = model().fit(x[~test], y[~test]).predict_proba(x[test])[:, 1]
    return out


def player_match_passes(passes: pd.DataFrame, expected: np.ndarray) -> pd.DataFrame:
    """One row per player and match with a pass: `passes`, `completed` and `expected`."""
    d = passes[KEYS].assign(passes=1, completed=passes["completed"].astype(int), expected=expected)
    return d.groupby(KEYS)[["passes", "completed", "expected"]].sum().reset_index()


def completion_rates(sums: pd.DataFrame) -> pd.DataFrame:
    """From summed `player_match_passes` columns: `completion`, `expected` (the mean expected
    completion of the passes, their ease) and `above_expected` (completions less expected
    completions, per pass)."""
    return pd.DataFrame(
        {
            "completion": sums["completed"] / sums["passes"],
            "expected": sums["expected"] / sums["passes"],
            "above_expected": (sums["completed"] - sums["expected"]) / sums["passes"],
        },
        index=sums.index,
    )


def possession_slope(sums: pd.DataFrame, share: pd.Series) -> float:
    """How much completion above expected rises with the team's share of possession, within
    players.

    Weighted least squares of each row's completion above expected on `share` (aligned with
    `sums`), with a fixed effect per `player_id` and the passes as weights; rows without a pass
    are left out. A slope of 0.1 is one percentage point of completion per 10 points of
    possession.
    """
    d = pd.DataFrame(
        {
            "player": sums["player_id"],
            "w": sums["passes"],
            "x": share,
            "y": (sums["completed"] - sums["expected"]) / sums["passes"],
        }
    )
    d = d[d.w > 0].dropna()
    for c in ("x", "y"):
        mean = (d[c] * d.w).groupby(d.player).transform("sum") / d.w.groupby(d.player).transform(
            "sum"
        )
        d[c] = d[c] - mean
    return float((d.w * d.x * d.y).sum() / (d.w * d.x**2).sum())


def adjust_above_expected(above: pd.Series, share: pd.Series, slope: float) -> pd.Series:
    """Completion above expected on an even share of possession: less `slope` x (share - 0.5)."""
    return above - slope * (share - 0.5)

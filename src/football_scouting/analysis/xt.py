"""Expected threat (xT): what having the ball in each zone of the pitch is worth.

Karun Singh's model (2018). The pitch is cut into a grid of zones. From each zone a team shoots,
moves the ball (a pass or a carry) or, optionally, loses it; xT of a zone is the value of the
shots taken there plus the xT of the zones its successful moves reach, each in proportion to
how often it happens:

    xT(z) = R(z) / N(z) + sum_z' S(z, z') / N(z) * xT(z')

N(z) counts the zone's actions, R(z) sums the value of its shots (xG, or goals) and S(z, z')
counts its successful moves into z'. A failed move, or a loss, ends the chain with nothing, so
xT(z) is the expected value of the shot the possession leads to before the ball is given away.
The equations are solved by iteration from zero.

Only open play counts: passes in open play (`metrics.OPEN_PLAY`, without injury clearances),
carries and open-play shots. The value a set piece creates comes from the routine, not from
the zone it starts in. Dribbles move the ball through the carry recorded next to them.

`chain_outcomes` gives what the model predicts, observed: for every event, the value of the
next open-play shot by the same team before the opponent's next action on the ball, a set
piece or the end of the half (0 when there is none). It checks a map fitted on some matches
against what happened in others.
"""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

from football_scouting.analysis.metrics import ON_BALL, OPEN_PLAY

LENGTH, WIDTH = 120.0, 80.0  # StatsBomb pitch units
SHOT_VALUES = ("xg", "goal")
# Ball losses besides failed dribbles: tackled without attempting a dribble, a bad touch.
LOSSES = "type IN ('Dispossessed', 'Miscontrol')"
POOL = "match_id IN (SELECT match_id FROM matches WHERE scouting_pool)"


def zones(x: np.ndarray, y: np.ndarray, nx: int, ny: int) -> np.ndarray:
    """Flat zone index (row across the pitch times `nx` plus column along it) of each spot.

    Spots outside the pitch (a pass's end out of play) fall in the nearest edge zone.
    """
    ix = np.clip(np.floor(np.asarray(x, float) / (LENGTH / nx)), 0, nx - 1).astype(int)
    iy = np.clip(np.floor(np.asarray(y, float) / (WIDTH / ny)), 0, ny - 1).astype(int)
    return iy * nx + ix


def load_actions(con: duckdb.DuckDBPyConnection, *, losses: bool = False) -> pd.DataFrame:
    """Open-play actions of the scouting pool, in match order.

    One row per action: `kind` is "move" (open-play pass or carry; `success` when a pass is
    completed, always for a carry), "shot" (open play; `xg` and `goal`) or, with `losses`,
    "loss" (dispossessed, miscontrol, failed dribble); `type` is the event type.
    """
    columns = "match_id, event_index, team_id, player_id, x, y"
    loss_rows = f"""
        UNION ALL
        SELECT {columns}, 'loss', type, NULL, NULL, FALSE, NULL, NULL
        FROM events WHERE {POOL} AND {LOSSES}
        UNION ALL
        SELECT {columns}, 'loss', 'Dribble', NULL, NULL, FALSE, NULL, NULL
        FROM dribbles WHERE {POOL} AND outcome = 'Incomplete'
    """
    return con.execute(f"""
        SELECT {columns}, 'move' AS kind, 'Pass' AS type, end_x, end_y, completed AS success,
               NULL::DOUBLE AS xg, NULL::BOOLEAN AS goal
        FROM passes
        WHERE {POOL} AND {OPEN_PLAY} AND outcome IS DISTINCT FROM 'Injury Clearance'
        UNION ALL
        SELECT {columns}, 'move', 'Carry', end_x, end_y, TRUE, NULL, NULL
        FROM carries WHERE {POOL}
        UNION ALL
        SELECT {columns}, 'shot', 'Shot', NULL, NULL, NULL, statsbomb_xg, outcome = 'Goal'
        FROM shots WHERE {POOL} AND shot_type = 'Open Play'
        {loss_rows if losses else ""}
        ORDER BY match_id, event_index
    """).df()


def fit(
    actions: pd.DataFrame,
    nx: int,
    ny: int,
    *,
    shot_value: str = "xg",
    tol: float = 1e-10,
    max_iter: int = 10_000,
) -> np.ndarray:
    """xT of every zone, as an array of `ny` rows (across the pitch) by `nx` columns."""
    if shot_value not in SHOT_VALUES:
        raise ValueError(f"shot_value must be one of {SHOT_VALUES}")
    n = nx * ny
    start = zones(actions.x, actions.y, nx, ny)
    count = np.bincount(start, minlength=n).astype(float)
    shot = (actions.kind == "shot").to_numpy()
    value = actions.loc[shot, shot_value].astype(float).to_numpy()
    reward = np.bincount(start[shot], weights=value, minlength=n)
    moved = _succeeded(actions)
    end = zones(actions.end_x[moved], actions.end_y[moved], nx, ny)
    moves = np.bincount(start[moved] * n + end, minlength=n * n).reshape(n, n)
    seen = count > 0
    r = np.where(seen, reward / np.where(seen, count, 1), 0.0)
    p = np.where(seen[:, None], moves / np.where(seen, count, 1)[:, None], 0.0)
    xt = np.zeros(n)
    for _ in range(max_iter):
        new = r + p @ xt
        if np.max(np.abs(new - xt)) < tol:
            return new.reshape(ny, nx)
        xt = new
    raise RuntimeError(f"xT did not converge in {max_iter} iterations")


def value_at(xt: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """xT of the zone of each spot."""
    ny, nx = xt.shape
    return xt.ravel()[zones(x, y, nx, ny)]


def move_credit(xt: np.ndarray, actions: pd.DataFrame) -> np.ndarray:
    """xT gained by each move, xT(end) - xT(start); NaN for other actions and failed moves."""
    moved = _succeeded(actions)
    gain = value_at(xt, actions.end_x.fillna(0), actions.end_y.fillna(0)) - value_at(
        xt, actions.x, actions.y
    )
    return np.where(moved, gain, np.nan)


def _succeeded(actions: pd.DataFrame) -> np.ndarray:
    return ((actions.kind == "move") & actions.success.fillna(False)).to_numpy(bool)


def chain_outcomes(con: duckdb.DuckDBPyConnection, shot_value: str = "xg") -> pd.DataFrame:
    """Every on-ball event of the pool with the value of the open-play shot its chain leads to.

    A team's chain runs until the opponent's next action on the ball (or their goalkeeper's), a
    set piece (a set-piece pass or a shot from one) or the end of the half. An event's
    `outcome` is the value (`shot_value`) of the first open-play shot by the event's team at or
    after it within the chain, 0 when there is none.
    """
    if shot_value not in SHOT_VALUES:
        raise ValueError(f"shot_value must be one of {SHOT_VALUES}")
    types = ", ".join(f"'{t}'" for t in [*ON_BALL, "Goal Keeper"] if t != "Ball Receipt*")
    ev = con.execute(f"""
        SELECT e.match_id, e.event_index, e.period, e.team_id,
               (p.pass_type IS NOT NULL AND p.pass_type NOT IN ('Recovery', 'Interception'))
               OR (s.shot_type IS NOT NULL AND s.shot_type <> 'Open Play') AS set_piece,
               CASE WHEN s.shot_type = 'Open Play' THEN s.statsbomb_xg END AS xg,
               CASE WHEN s.shot_type = 'Open Play' THEN (s.outcome = 'Goal')::DOUBLE END AS goal
        FROM events e
        LEFT JOIN passes p USING (event_id)
        LEFT JOIN shots s USING (event_id)
        WHERE e.{POOL} AND e.type IN ({types})
        ORDER BY e.match_id, e.event_index
    """).df()
    return ev[["match_id", "event_index", "team_id"]].assign(outcome=_chain_outcome(ev, shot_value))


def _chain_outcome(ev: pd.DataFrame, shot_value: str) -> np.ndarray:
    """`chain_outcomes` on events sorted by match and event index (match_id, period, team_id,
    set_piece and the shot value columns)."""
    by_match = ev.groupby("match_id", sort=False)
    new_half = ev.period.ne(by_match.period.shift())
    breaks = (ev.set_piece | new_half).astype(int).groupby(ev.match_id, sort=False).cumsum()
    # Rows of the other team so far: two rows of a team share a chain when nothing breaks it
    # and the opponent has not touched the ball in between.
    others = by_match.cumcount() - ev.groupby(["match_id", "team_id"], sort=False).cumcount()
    chain = breaks + others
    shot = ev[shot_value].astype(float)
    nxt = shot.groupby([ev.match_id, ev.team_id, chain], sort=False).bfill()
    return nxt.fillna(0.0).to_numpy()

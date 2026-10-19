"""Possession: how long each team has the ball, and how much a player's counts depend on it.

A team's possession is the time it has the ball. The time from each event to the next, within
a period, is credited to the event's possession team (StatsBomb's `possession_team_id`, the
team in control of the ball), with gaps capped at `GAP_CAP_SECONDS` so that stoppages count
little. A player's possession is their team's share of that time while they are on the pitch:
a substitute who comes on at 0-1 plays a different match from the starter they replace.

Each per-90 statistic happens either with the ball (passes, carries, shots: the team's own
possession) or without it (pressures, tackles, interceptions, recoveries, clearances: the
opponent's), `SIDE`. Aerial duels are contested and listed without the ball: for centre-backs
most come from the opponent's long balls.

How much a count depends on possession is measured within players, from the same player's
matches with more or less of the ball, so that better players in better teams do not pass for
an effect of possession: Poisson regression with a fixed effect per player (the conditional
likelihood, in which the player effects drop out), minutes as exposure and the log of the
share of possession on the statistic's side as the one covariate. The slope is an elasticity:
beta = 1 means the count is proportional to the time on that side, beta = 0 that it does not
depend on it. A player's rate is then adjusted to a share of `REFERENCE_SHARE` with
rate * (REFERENCE_SHARE / share) ** beta.
"""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

from football_scouting.analysis.metrics import PER_90

GAP_CAP_SECONDS = 10.0
REFERENCE_SHARE = 0.5  # every match's possession adds up to 1 between the two teams

WITHOUT_BALL = (
    "pressures", "counterpressures", "pressures_final_third", "tackles", "interceptions",
    "recoveries", "clearances", "blocks", "dribbled_past", "aerial_duels",
)  # fmt: skip
# {per-90 statistic: "with" (the team's own possession) or "without" (the opponent's)}.
SIDE = {m: "without" if m in WITHOUT_BALL else "with" for m in PER_90}


def _credited_time(cap: float) -> str:
    """SQL: one row per pool event with the seconds credited to its possession team."""
    return f"""
        SELECT match_id, player_id, team_id, possession_team_id, match_seconds, event_index,
               coalesce(least(greatest(lead(match_seconds) OVER (
                   PARTITION BY match_id, period ORDER BY match_seconds, event_index
               ) - match_seconds, 0), {cap}), 0) AS secs  -- 0 for a period's last event
        FROM events
        WHERE match_id IN (SELECT match_id FROM matches WHERE scouting_pool)
    """


def team_possession(
    con: duckdb.DuckDBPyConnection, *, cap: float = GAP_CAP_SECONDS
) -> pd.DataFrame:
    """One row per pool match and team: seconds with the ball and the share of the match's."""
    out = con.execute(
        f"""
        SELECT match_id, possession_team_id AS team_id, sum(secs) AS seconds
        FROM ({_credited_time(cap)})
        GROUP BY ALL ORDER BY match_id, team_id
        """
    ).df()
    out["share"] = out["seconds"] / out.groupby("match_id")["seconds"].transform("sum")
    return out


def player_possession(
    con: duckdb.DuckDBPyConnection, *, cap: float = GAP_CAP_SECONDS
) -> pd.DataFrame:
    """One row per player and pool match played: seconds of possession while on the pitch.

    `own_seconds` and `opp_seconds` are the player's team's and the opponent's time with the
    ball between `on_seconds` and `off_seconds`; `self_own_seconds` and `self_opp_seconds` the
    part credited at the player's own events (to measure possession without the player).
    """
    return con.execute(
        f"""
        WITH e AS ({_credited_time(cap)}),
        clock AS (  -- the two teams' time with the ball up to each moment of the match
            SELECT match_id, match_seconds, max(home) AS home, max(away) AS away
            FROM (
                SELECT e.match_id, e.match_seconds,
                       sum(CASE WHEN possession_team_id = m.home_team_id THEN secs ELSE 0 END)
                           OVER w AS home,
                       sum(CASE WHEN possession_team_id = m.away_team_id THEN secs ELSE 0 END)
                           OVER w AS away
                FROM e JOIN matches m USING (match_id)
                WINDOW w AS (PARTITION BY e.match_id ORDER BY e.match_seconds, e.event_index
                             ROWS UNBOUNDED PRECEDING))
            GROUP BY ALL),
        self AS (
            SELECT match_id, player_id,
                   sum(secs) FILTER (WHERE possession_team_id = team_id) AS self_own_seconds,
                   sum(secs) FILTER (WHERE possession_team_id <> team_id) AS self_opp_seconds
            FROM e WHERE player_id IS NOT NULL GROUP BY ALL)
        SELECT pm.match_id, pm.team_id, pm.player_id,
               CASE WHEN pm.team_id = m.home_team_id THEN b.home - coalesce(a.home, 0)
                    ELSE b.away - coalesce(a.away, 0) END AS own_seconds,
               CASE WHEN pm.team_id = m.home_team_id THEN b.away - coalesce(a.away, 0)
                    ELSE b.home - coalesce(a.home, 0) END AS opp_seconds,
               coalesce(self.self_own_seconds, 0) AS self_own_seconds,
               coalesce(self.self_opp_seconds, 0) AS self_opp_seconds
        FROM player_matches pm
        JOIN matches m USING (match_id)
        ASOF LEFT JOIN clock a ON pm.match_id = a.match_id AND pm.on_seconds > a.match_seconds
        ASOF LEFT JOIN clock b ON pm.match_id = b.match_id AND pm.off_seconds >= b.match_seconds
        LEFT JOIN self USING (match_id, player_id)
        WHERE m.scouting_pool AND pm.played
        ORDER BY pm.match_id, pm.team_id, pm.player_id
        """
    ).df()


def elasticity(
    d: pd.DataFrame, count: str, share: str, *, exposure: str = "minutes", unit: str = "player_id"
) -> tuple[float, float]:
    """Within-`unit` elasticity of `count` to `share`, and its standard error.

    Poisson regression of `count` on log(`share`) with a fixed effect per unit and log
    `exposure` as offset, fitted by its conditional likelihood (Newton's method). The standard
    error is robust and clustered by unit. Rows with a share of 0 or no exposure are left out.
    """
    d = d[(d[exposure] > 0) & (d[share] > 0)]
    y = d[count].to_numpy(float)
    x = np.log(d[share].to_numpy(float))
    offset = np.log(d[exposure].to_numpy(float))
    g = pd.factorize(d[unit])[0]
    total = np.bincount(g, y)

    def fit(beta: float) -> tuple[np.ndarray, float]:
        """Each unit's expected mean of x, and the information about beta."""
        w = np.exp(offset + beta * x)
        p = w / np.bincount(g, w)[g]  # each row's share of its unit's expected count
        xbar = np.bincount(g, p * x)
        return xbar, float((total * (np.bincount(g, p * x * x) - xbar**2)).sum())

    beta = 0.0
    for _ in range(100):
        xbar, info = fit(beta)
        score = float((y * (x - xbar[g])).sum())
        step = score / info
        beta += step
        if abs(step) < 1e-10:
            break
    xbar, info = fit(beta)
    per_unit = np.bincount(g, y * (x - xbar[g]))
    return beta, float(np.sqrt((per_unit**2).sum()) / info)


def adjust(
    rate: pd.Series | np.ndarray, share: pd.Series | np.ndarray, beta: float
) -> pd.Series | np.ndarray:
    """A rate at `REFERENCE_SHARE` of possession on its side, from the rate at `share`."""
    return rate * (REFERENCE_SHARE / share) ** beta


def adjust_rates(
    r: pd.DataFrame, share: pd.Series, beta: pd.Series | dict[str, float]
) -> pd.DataFrame:
    """`r` with each per-90 column in `beta` adjusted to an even share, by its elasticity.

    `share` is each row's team's own share of possession; statistics without the ball are
    adjusted on the opponent's share, 1 - `share`.
    """
    out = r.copy()
    for m, b in dict(beta).items():
        if m in out:
            out[m] = adjust(out[m], share if SIDE[m] == "with" else 1 - share, b)
    return out

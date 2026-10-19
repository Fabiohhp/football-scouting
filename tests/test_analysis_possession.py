import duckdb
import numpy as np
import pandas as pd
import pytest

from football_scouting.analysis.metrics import PER_90
from football_scouting.analysis.possession import (
    SIDE,
    adjust,
    adjust_rates,
    elasticity,
    player_possession,
    team_possession,
)

# Match 1: home team 1, away team 2. (event_index, period, match_seconds, possession team,
# acting team, player); the time to the next event in the period goes to the possession team.
EVENTS = [
    (1, 1, 0, 1, 1, 10),  # 4 s home
    (2, 1, 4, 1, 1, 12),  # 30 s to the next event, capped at 10: home
    (3, 1, 34, 2, 2, 20),  # 6 s away
    (4, 1, 40, 2, 1, 10),  # a home player's pressure in the away team's possession: 2 s away
    (5, 1, 42, 2, 2, 20),  # last event of the period: 0 s
    (6, 2, 45, 1, 1, 11),  # 5 s home
    (7, 2, 50, 2, 2, 20),  # 3 s away
    (8, 2, 53, 2, 2, 20),  # last event: 0 s
]
# (team, player, played, on, off): 12 is replaced by 11 at 44 s; 13 stays on the bench.
PLAYERS = [
    (1, 10, True, 0, 60),
    (1, 11, True, 44, 60),
    (1, 12, True, 0, 44),
    (1, 13, False, None, None),
    (2, 20, True, 0, 60),
]


@pytest.fixture
def con():
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE matches AS SELECT * FROM (VALUES (1, true, 1, 2), (2, false, 1, 2)) "
        "t(match_id, scouting_pool, home_team_id, away_team_id)"
    )
    events = pd.DataFrame(
        EVENTS,
        columns=["event_index", "period", "match_seconds", "possession_team_id", "team_id",
                 "player_id"],
    ).assign(match_id=1)  # fmt: skip
    events = pd.concat([events, events.assign(match_id=2)])  # outside the pool
    players = pd.DataFrame(
        PLAYERS, columns=["team_id", "player_id", "played", "on_seconds", "off_seconds"]
    ).assign(match_id=1)
    for name, table in {"events": events, "player_matches": players}.items():
        con.register("frame", table)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM frame")
        con.unregister("frame")
    return con


def test_team_possession_caps_stoppages(con):
    out = team_possession(con).set_index("team_id")
    assert out["seconds"].to_dict() == {1: 19, 2: 11}
    assert out.loc[1, "share"] == pytest.approx(19 / 30)


def test_player_possession_counts_time_on_the_pitch(con):
    out = player_possession(con).set_index("player_id")
    assert list(out.index) == [10, 11, 12, 20]
    cols = ["own_seconds", "opp_seconds", "self_own_seconds", "self_opp_seconds"]
    assert out.loc[10, cols].tolist() == [19, 11, 4, 2]
    assert out.loc[11, cols].tolist() == [5, 3, 5, 0]  # from 44 s: events 6 and 7
    assert out.loc[12, cols].tolist() == [14, 8, 10, 0]  # up to 44 s: events 1 to 5
    assert out.loc[20, cols].tolist() == [11, 19, 9, 0]


def synthetic(beta: float, seed: int = 0) -> pd.DataFrame:
    """Players whose quality rises with their team's possession, 30 matches each."""
    rng = np.random.default_rng(seed)
    n, matches = 400, 30
    team_share = rng.uniform(0.35, 0.65, n)
    quality = np.log(3) + 4 * (team_share - 0.5) + rng.normal(0, 0.2, n)
    d = pd.DataFrame({"player_id": np.repeat(np.arange(n), matches)})
    d["minutes"] = rng.uniform(20, 95, len(d))
    d["share"] = np.clip(np.repeat(team_share, matches) + rng.normal(0, 0.08, len(d)), 0.1, 0.9)
    mean = np.exp(np.repeat(quality, matches)) * d.minutes / 90 * (d.share / 0.5) ** beta
    d["count"] = rng.poisson(mean)
    return d


@pytest.mark.parametrize("beta", [0.0, 1.0])
def test_elasticity_is_measured_within_players(beta):
    d = synthetic(beta)
    estimate, se = elasticity(d, "count", "share")
    assert estimate == pytest.approx(beta, abs=4 * se)
    assert se < 0.05
    # Between players, quality follows possession: a pooled slope would find an effect.
    pooled = np.polyfit(np.log(d.share), np.log((d["count"] + 0.5) / d.minutes), 1)[0]
    assert pooled > beta + 0.2


def test_adjust_to_an_even_share():
    assert adjust(2.0, 0.5, 1.3) == pytest.approx(2.0)
    assert adjust(3.0, 0.6, 1.0) == pytest.approx(2.5)  # proportional to the time on its side
    assert adjust(3.0, 0.6, 0.0) == pytest.approx(3.0)


def test_every_per_90_statistic_has_a_side():
    assert sorted(SIDE) == sorted(PER_90)
    assert SIDE["passes"] == "with" and SIDE["tackles"] == "without"


def test_adjust_rates_uses_the_side_of_each_statistic():
    r = pd.DataFrame({"passes": [60.0, 40.0], "tackles": [2.0, 3.0], "pass_completion": [0.9, 0.8]})
    share = pd.Series([0.6, 0.4])
    out = adjust_rates(r, share, {"passes": 1.0, "tackles": 1.0})
    assert out["passes"].tolist() == pytest.approx([50.0, 50.0])
    assert out["tackles"].tolist() == pytest.approx([2.5, 2.5])  # on the opponent's share
    assert out["pass_completion"].tolist() == [0.9, 0.8]  # no elasticity given: unchanged

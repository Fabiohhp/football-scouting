"""The team sums cover every pool match from both sides and reconcile with the player counts.
Run with `make dq`."""

import numpy as np
import pandas as pd
import pytest

from football_scouting.analysis.metrics import player_match_counts
from football_scouting.analysis.teams import (
    INFO,
    KEYS,
    PLAYER_KEYS,
    numbers,
    pass_network,
    player_match_sums,
    team_match_sums,
    without,
)
from football_scouting.config import load_config
from football_scouting.model.database import connect_readonly, database_path

pytestmark = pytest.mark.data
CFG = load_config()


@pytest.fixture(scope="module")
def con():
    if not database_path(CFG).exists():
        pytest.skip("database not built (run `make model`)")
    return connect_readonly(CFG)


@pytest.fixture(scope="module")
def players(con):
    return player_match_sums(con, pass_ease=False)


@pytest.fixture(scope="module")
def sums(con, players):
    return team_match_sums(con, players)


def test_every_pool_match_has_both_teams(con, sums):
    matches = con.execute("SELECT count(*) FROM matches WHERE scouting_pool").fetchone()[0]
    assert len(sums) == 2 * matches and not sums.duplicated(KEYS).any()
    assert sums.groupby("team_id").size().between(37, 38).all() and sums.team_id.nunique() == 80


def test_the_opponent_counts_are_the_opponents_own(sums):
    opponent = sums.set_index(["match_id", "team_id"]).loc[
        list(zip(sums.match_id, sums.opponent_id, strict=True))
    ]
    for column in ("passes_own60", "passes_final_third", "seconds"):
        assert np.allclose(sums[f"opp_{column}"], opponent[column])


def test_team_counts_add_up_the_players_counts(con, sums):
    players = player_match_counts(con).groupby(KEYS)[["passes", "tackles", "pressures"]].sum()
    joined = sums.join(players, on=KEYS, rsuffix="_players")
    for column in ("passes", "tackles", "pressures"):
        assert (joined[column] == joined[f"{column}_players"]).all(), column


def test_player_rows_are_unique_and_in_their_teams_pool_matches(players, sums):
    assert not players.duplicated(PLAYER_KEYS).any()
    assert pd.MultiIndex.from_frame(players[KEYS]).isin(pd.MultiIndex.from_frame(sums[KEYS])).all()


def test_a_team_without_all_its_players_keeps_only_the_counts_no_player_makes(players, sums):
    team = sums.groupby("team_id").sum(numeric_only=True)
    left = without(team, players.groupby("team_id").sum(numeric_only=True))
    counted = players.columns.drop(INFO, errors="ignore")
    assert np.allclose(left[counted], 0)
    for column in ("possessions", "seconds", "opp_passes_own60"):
        assert (left[column] == team[column]).all()


def test_every_teams_numbers_are_in_range(sums):
    season = numbers(sums.groupby("team_id").sum(numeric_only=True))
    shares = season.drop(columns=["ppda", "defence_height", "passes_per_possession", "tempo",
                                  "directness"])  # fmt: skip
    assert season.notna().all().all() and ((shares > 0) & (shares < 1)).all().all()
    assert (season.ppda > 0).all() and season.defence_height.between(0, 120).all()
    pair = sums.groupby("match_id").seconds.sum()
    assert np.allclose(sums.seconds + sums.opp_seconds, sums.match_id.map(pair))


def test_a_pass_network_has_the_eleven_positions_of_the_formation(con):
    team = con.execute("SELECT team_id FROM teams WHERE team_name = 'Barcelona'").fetchone()[0]
    network = pass_network(con, team)
    assert network.formation == "4-3-3" and network.share > 0.9
    assert len(network.nodes) == 11 and network.nodes.x.between(0, 120).all()
    assert network.edges.a.isin(network.nodes.index).all()
    assert network.edges.b.isin(network.nodes.index).all()
    assert (network.edges.a < network.edges.b).all() and (network.edges.passes > 0).all()
    # completed passes between the eleven are fewer than the passes they play
    assert network.edges.passes.sum() < network.nodes.passes.sum()

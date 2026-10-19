"""Possession time reconciles between teams and players. Run with `make dq`."""

import numpy as np
import pytest

from football_scouting.analysis.possession import player_possession, team_possession
from football_scouting.config import load_config
from football_scouting.model.database import connect_readonly, database_path

pytestmark = pytest.mark.data
CFG = load_config()


@pytest.fixture(scope="module")
def con():
    if not database_path(CFG).exists():
        pytest.skip("database not built (run `make model`)")
    return connect_readonly(CFG)


def test_two_teams_share_every_match(con):
    teams = team_possession(con)
    per_match = teams.groupby("match_id")
    assert (per_match.size() == 2).all()
    assert np.allclose(per_match.share.sum(), 1)
    durations = con.sql(
        "SELECT match_id, duration_seconds FROM matches WHERE scouting_pool"
    ).df().set_index("match_id").duration_seconds
    assert (per_match.seconds.sum() <= durations.reindex(per_match.seconds.sum().index)).all()


def test_a_whole_match_on_the_pitch_sees_all_of_it(con):
    """A player on from kick-off to the end sees their team's and the opponent's whole time."""
    players = player_possession(con).merge(
        con.sql(
            "SELECT match_id, player_id, on_seconds, off_seconds, match_end_seconds "
            "FROM player_matches WHERE played"
        ).df(),
        on=["match_id", "player_id"],
    )
    whole = players[(players.on_seconds == 0) & (players.off_seconds == players.match_end_seconds)]
    teams = team_possession(con)
    total = teams.groupby("match_id").seconds.sum()
    whole = whole.merge(teams, on=["match_id", "team_id"])
    assert len(whole) > 20_000
    assert np.allclose(whole.own_seconds, whole.seconds)
    assert np.allclose(whole.own_seconds + whole.opp_seconds, whole.match_id.map(total))
    assert (players.self_own_seconds <= players.own_seconds + 1e-9).all()

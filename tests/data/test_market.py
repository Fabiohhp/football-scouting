"""The market's view of the profiled players. Run with `make dq`."""

import pandas as pd
import pytest

from football_scouting.analysis.market import market_players, team_strength
from football_scouting.config import load_config
from football_scouting.model.database import connect_readonly, database_path

pytestmark = pytest.mark.data
CFG = load_config()


@pytest.fixture(scope="module")
def con():
    if not database_path(CFG).exists():
        pytest.skip("database not built (run `make model`)")
    return connect_readonly(CFG)


def test_team_strength_adds_up_over_each_match(con):
    teams = team_strength(con)
    pool = con.sql(
        "SELECT count(*) FROM teams JOIN competitions USING (competition_id, season_id) "
        "WHERE scouting_pool"
    )
    assert len(teams) == pool.fetchone()[0]
    assert (teams.goal_difference * teams.matches).sum() == pytest.approx(0)
    assert teams.points.between(0, 3).all()


def test_every_profiled_player_has_a_value_and_a_team_on_the_market_view(con):
    players = market_players(con, CFG)
    profiled = con.sql("SELECT player_id FROM profile_players").df().player_id
    assert sorted(players.player_id) == sorted(profiled) and players.player_id.is_unique
    assert players[["value", "team_id", "team_goal_difference"]].notna().all().all()
    assert (players.value_date <= pd.Timestamp(CFG.backtest.market_view)).all()
    stints = con.sql(
        "SELECT player_id, team_id, minutes FROM player_seasons ps "
        "JOIN competitions c USING (competition_id, season_id) "
        "WHERE c.scouting_pool AND ps.matches_played > 0"
    ).df()
    most = stints.loc[stints.groupby("player_id").minutes.idxmax()].set_index("player_id")
    assert (players.set_index("player_id").team_id == most.team_id.reindex(players.player_id)).all()
    one_team = players[players.player_id.map(stints.player_id.value_counts()) == 1]
    strength = team_strength(con).set_index("team_id")
    assert one_team.team_goal_difference.to_numpy() == pytest.approx(
        strength.goal_difference.reindex(one_team.team_id).to_numpy()
    )

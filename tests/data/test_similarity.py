"""The players the similarity search reads. Run with `make dq`."""

import pytest

from football_scouting.analysis.market import market_players
from football_scouting.analysis.roles import style_matches
from football_scouting.analysis.similarity import search_players
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
def who(con):
    market = market_players(con, CFG).set_index("player_id")
    return search_players(con, CFG, market, style_matches(con, CFG, market.comparison_group))


def test_every_profiled_player_has_a_row_with_what_the_search_reads(con, who):
    profiled = con.sql("SELECT count(*) FROM profile_players").fetchone()[0]
    assert len(who) == profiled and who.index.is_unique
    assert who.drop(columns=["list", "side", "line"]).notna().all().all()
    assert who.left_foot.between(0, 1).all()
    assert set(who.side.dropna()) == {"Left", "Right"}


def test_the_lists_follow_minutes_in_the_groups_positions_and_age(who):
    regulars = who["list"] == "Regulars"
    assert (regulars == (who.minutes >= CFG.compared.minutes)).all()
    young = who[who["list"] == "Young"]
    assert (young.age < CFG.compared.young_age).all()
    assert young.minutes.between(CFG.compared.young_minutes, CFG.compared.minutes).all()


def test_lines_belong_to_the_groups_with_several(who):
    with_lines = who.group.isin(["CM", "AMW", "CF"])
    assert who.line[with_lines].notna().all() and who.line[~with_lines].isna().all()
    assert who.teams.map(len).between(1, 3).all()

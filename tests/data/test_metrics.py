"""Player-match counts reconcile with the event tables. Run with `make dq`."""

import pytest

from football_scouting.analysis.metrics import player_match_counts
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
def counts(con):
    return player_match_counts(con)


def pool_total(con, sql: str) -> float:
    return con.execute(f"{sql} AND match_id IN (SELECT match_id FROM matches WHERE scouting_pool)"
                       ).fetchone()[0]  # fmt: skip


def test_one_row_per_player_match_played(con, counts):
    assert not counts.duplicated(["match_id", "player_id"]).any()
    played = pool_total(con, "SELECT count(*) FROM player_matches WHERE played")
    assert len(counts) == played


def test_counts_reconcile_with_event_tables(con, counts):
    """Every counted event belongs to a player who played (no event is lost in the join)."""
    expected = {
        "shots": "SELECT count(*) FROM shots WHERE shot_type <> 'Penalty'",
        "xg": "SELECT sum(statsbomb_xg) FROM shots WHERE shot_type <> 'Penalty'",
        "pressures": "SELECT count(*) FROM pressures WHERE true",
        "dribbles": "SELECT count(*) FROM dribbles WHERE true",
        "tackles": "SELECT count(*) FROM defensive_actions WHERE action = 'Tackle'",
    }
    for col, sql in expected.items():
        assert counts[col].sum() == pytest.approx(pool_total(con, sql)), col


def test_minutes_match_player_seasons(con, counts):
    seasons = con.execute(
        "SELECT sum(minutes) FROM player_seasons JOIN competitions USING (competition_id) "
        "WHERE scouting_pool"
    ).fetchone()[0]
    assert counts["minutes"].sum() == pytest.approx(seasons)

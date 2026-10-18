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


POOL = "match_id IN (SELECT match_id FROM matches WHERE scouting_pool)"


def pool_total(con, sql: str) -> float:
    return con.execute(f"{sql} AND {POOL}").fetchone()[0]


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
        "counterpressures": "SELECT count(*) FROM pressures WHERE counterpress",
        "dribbled_past": "SELECT count(*) FROM dribbled_past WHERE true",
        "aerials_lost": "SELECT count(*) FROM duels WHERE duel_type = 'Aerial Lost'",
        "fouls_won": "SELECT count(*) FROM fouls_won WHERE true",
        "ball_losses": "SELECT count(*) FROM (SELECT match_id FROM miscontrols "
        "UNION ALL SELECT match_id FROM dispossessions) WHERE true",
        "xa": "SELECT sum(statsbomb_xg) FROM shots WHERE key_pass_id IN "
        "(SELECT event_id FROM passes WHERE pass_type IS NULL "
        "OR pass_type IN ('Recovery', 'Interception'))",
    }
    for col, sql in expected.items():
        assert counts[col].sum() == pytest.approx(pool_total(con, sql)), col


def test_minutes_match_player_seasons(con, counts):
    seasons = con.execute(
        "SELECT sum(minutes) FROM player_seasons JOIN competitions USING (competition_id) "
        "WHERE scouting_pool"
    ).fetchone()[0]
    assert counts["minutes"].sum() == pytest.approx(seasons)


def test_every_aerial_duel_has_a_winner_and_a_loser(counts):
    """StatsBomb records an aerial duel as won on the winner's action and lost on a duel."""
    per_match = counts.groupby("match_id")[["aerials_won", "aerials_lost"]].sum()
    assert (per_match.aerials_won == per_match.aerials_lost).all()

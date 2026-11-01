"""The back-test's outcomes for the profiled players. Run with `make dq`."""

import pytest

from football_scouting.analysis.outcomes import (
    LEVELS,
    club_ids,
    club_leagues,
    coaches,
    first_half_clubs,
    league_share,
    player_outcomes,
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
def outcomes(con):
    return player_outcomes(con, CFG)


def test_every_profiled_player_has_an_outcome_at_every_horizon(con, outcomes):
    profiled = con.sql("SELECT count(*) FROM profile_players").fetchone()[0]
    assert len(outcomes) == profiled * len(CFG.backtest.horizons)
    assert not outcomes.duplicated(["player_id", "horizon"]).any()
    assert outcomes.base.notna().all() and outcomes.band.notna().all()
    assert (outcomes.growth.isna() == ~outcomes.still_valued).all()
    assert (outcomes.excess.isna() == ~outcomes.still_valued).all()


def test_no_longer_valued_players_score_lowest_in_their_band(outcomes):
    assert outcomes.score.between(0, 100, inclusive="right").all()
    for _, d in outcomes.groupby(["horizon", "band"], observed=True):
        assert d.score.mean() == pytest.approx(50 + 50 / len(d))
        if (~d.still_valued).any():
            assert d.score[~d.still_valued].max() < d.score[d.still_valued].min()


def test_levels_follow_the_minutes(outcomes):
    assert set(outcomes.level) == set(LEVELS)
    assert (outcomes.big_five_minutes <= outcomes.league_minutes).all()
    valued = outcomes[outcomes.still_valued]
    assert ((valued.level == "big five") == valued.league.isin(CFG.backtest.big_five)).all()
    assert ((valued.level == "no league minutes") == (valued.league_minutes == 0)).all()


def test_club_names_on_valuations_find_their_clubs(con):
    names = club_ids(con)
    full = con.sql("SELECT club_id, name FROM tm_clubs").df().set_index("club_id").name
    assert full[names["AS Roma"]] == "Associazione Sportiva Roma"
    assert full[names["SS Lazio"]] == "Società Sportiva Lazio S.p.A."
    assert "Los Angeles Galaxy" not in names.index  # MLS is outside the covered leagues


def test_a_club_plays_one_league_a_season(con):
    leagues = club_leagues(con)
    assert not leagues.duplicated(["club_id", "season"]).any()


def test_a_player_has_one_first_half_club_and_a_share_of_its_league_minutes(con):
    clubs = first_half_clubs(con, 2016)
    assert not clubs.player_id.duplicated().any()
    assert set(clubs.source) == {"appearances", "transfer"}
    assert (clubs.source == "appearances").mean() > 0.9
    share = league_share(con, 2016, clubs)
    covered = share.notna()  # clubs outside the covered leagues have no league matches on record
    assert covered.mean() > 0.9 and share[covered].between(0, 1).all()
    assert (share[covered] > 0).mean() > 0.8  # most played league matches for that club


def test_coaches_follow_the_change_of_season(con):
    names = con.sql("SELECT club_id, name FROM tm_clubs").df().set_index("name").club_id
    coach = coaches(con, 2016)
    city = coach.loc[names["Manchester City"]]
    assert (city.before, city.after) == ("Manuel Pellegrini", "Pep Guardiola")
    leagues = club_leagues(con).pivot(index="club_id", columns="season", values="league")
    both = leagues.index[leagues[[2015, 2016]].notna().all(axis=1)]  # in a league both seasons
    assert len(both) > 200 and coach.loc[both].notna().all().all()

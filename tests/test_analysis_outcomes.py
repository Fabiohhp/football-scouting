from datetime import date

import duckdb
import numpy as np
import pandas as pd
import pytest

from football_scouting.analysis.outcomes import (
    age_band,
    career,
    club_ids,
    club_leagues,
    coaches,
    excess_growth,
    first_half_clubs,
    growth_score,
    league_share,
    season_clubs,
    value_growth,
)
from football_scouting.config import BacktestConfig

BT = BacktestConfig(
    market_view=date(2016, 6, 30),
    outcome_base=date(2016, 8, 1),
    horizons=(date(2017, 8, 31), date(2019, 8, 31)),
    still_valued_days=365,
    primary_horizon=date(2019, 8, 31),
    age_bands=(21, 23),
    big_five=("GB1", "ES1"),
    regular_minutes=900,
    champions_league="CL",
)

VALUATIONS = pd.DataFrame(
    {
        "player_id": [1, 1, 1, 2, 2],
        "date": pd.to_datetime(
            ["2016-07-15", "2017-06-01", "2019-06-01", "2016-02-09", "2017-01-10"]
        ),
        "value": [1_000_000, 2_000_000, 4_000_000, 500_000, 250_000],
        "club": ["A", "A", "B", "C", "C"],
    }
)


def test_value_growth_from_the_base_value_until_a_player_is_no_longer_valued():
    out = value_growth(VALUATIONS, BT).set_index(["player_id", "horizon"])
    assert len(out) == 4
    first = out.loc[(1, pd.Timestamp("2019-08-31"))]
    assert first.base == 1_000_000 and first.club == "B"
    assert first.growth == pytest.approx(np.log(4))
    second = out.loc[(2, pd.Timestamp("2019-08-31"))]  # last valued in January 2017
    assert not second.still_valued and np.isnan(second.growth) and second.value == 250_000
    assert out.loc[(2, pd.Timestamp("2017-08-31"))].growth == pytest.approx(np.log(0.5))


def test_age_bands_start_at_each_age():
    bands = age_band(pd.Series([18.0, 20.99, 21.0, 22.9, 23.0, 36.0]), (21, 23))
    assert bands.tolist() == [
        "under 21",
        "under 21",
        "21-22",
        "21-22",
        "23 and over",
        "23 and over",
    ]


def test_growth_score_ranks_within_groups_with_no_longer_valued_at_the_bottom():
    growth = pd.Series([0.5, -1.0, np.nan, np.nan, 2.0, 0.0])
    group = pd.Series(["a", "a", "a", "a", "b", "b"])
    score = growth_score(growth, group)
    assert score.tolist() == pytest.approx([100, 75, 37.5, 37.5, 100, 50])  # ranks 1 and 2 shared


def test_excess_growth_takes_out_the_age_curve():
    rng = np.random.default_rng(0)
    age = pd.Series(rng.uniform(18, 36, 500))
    noise = rng.normal(0, 0.05, 500)
    growth = pd.Series(1.5 - 0.1 * (age - 18) + noise)
    growth[:10] = np.nan
    out = excess_growth(growth, age)
    assert out[:10].isna().all()
    assert np.corrcoef(out[10:], noise[10:])[0, 1] > 0.95


def test_career_reads_the_season_before_each_horizon():
    growth = value_growth(VALUATIONS, BT)
    minutes = pd.DataFrame(
        {
            "player_id": [1, 1, 1, 1, 2],
            "season": [2016, 2016, 2016, 2018, 2016],
            "competition_id": ["GB1", "TR1", "CL", "TR1", "FAC"],
            "type": [
                "domestic_league",
                "domestic_league",
                "international_cup",
                "domestic_league",
                "domestic_cup",
            ],
            "minutes": [400, 900, 180, 2000, 90],
        }
    )
    out = career(growth, minutes, BT).set_index(["player_id", "horizon"])
    first = out.loc[(1, pd.Timestamp("2017-08-31"))]  # the 2016/17 season
    assert (first.league_minutes, first.big_five_minutes, first.champions_league_minutes) == (
        1300, 400, 180,
    )  # fmt: skip
    assert first.league == "TR1" and first.level == "other covered league"
    assert out.loc[(1, pd.Timestamp("2019-08-31"))].league == "TR1"  # the 2018/19 season
    assert out.loc[(2, pd.Timestamp("2017-08-31"))].level == "no league minutes"  # a cup only
    assert out.loc[(2, pd.Timestamp("2019-08-31"))].level == "no longer valued"


def test_club_names_go_to_the_club_their_players_played_for():
    con = duckdb.connect()
    tables = {
        "tm_competitions": pd.DataFrame(
            {"competition_id": ["IT1", "CIT"], "type": ["domestic_league", "domestic_cup"]}
        ),
        "tm_games": pd.DataFrame(
            {
                "game_id": [1, 2, 3],
                "competition_id": ["IT1", "CIT", "IT1"],
                "season": [2017, 2017, 2018],
                "home_club_id": [12, 12, 99],
                "away_club_id": [99, 99, 12],
            }
        ),
        # players 1 to 3 played for Roma in 2017/18, player 4 joined from a club outside the leagues
        "tm_appearances": pd.DataFrame(
            {"player_id": [1, 2, 3, 4, 3], "game_id": [1, 1, 1, 1, 2], "player_club_id": [12] * 5}
        ),
        "tm_player_valuations": pd.DataFrame(
            {
                "player_id": [1, 2, 3, 4, 1],
                "date": pd.to_datetime(
                    ["2017-10-01", "2018-02-01", "2018-06-01", "2017-07-01", "2016-10-01"]
                ),
                "current_club_name": ["AS Roma", "AS Roma", "AS Roma", "LA Galaxy", "AS Roma"],
            }
        ),
    }
    for name, table in tables.items():
        con.register(name, table)
    assert club_ids(con, min_players=2).to_dict() == {"AS Roma": 12}  # one LA Galaxy voter
    assert club_ids(con, min_players=4).empty
    assert club_leagues(con).to_dict("list") == {
        "club_id": [12, 12, 99, 99], "season": [2017, 2018, 2017, 2018], "league": ["IT1"] * 4,
    }  # fmt: skip


def test_a_players_club_in_a_season_is_the_one_they_played_most_for():
    con = duckdb.connect()
    tables = {
        "player_map": pd.DataFrame({"sb_player_id": [101, 102], "tm_player_id": [1, 2]}),
        "tm_games": pd.DataFrame({"game_id": [1, 2, 3, 4], "season": [2015, 2015, 2016, 2016]}),
        # player 1: 90 minutes at club 12 and 120 at club 30 in 2015; player 2: a tie in 2016
        "tm_appearances": pd.DataFrame(
            {
                "player_id": [1, 1, 1, 1, 2, 2],
                "game_id": [1, 2, 2, 3, 3, 4],
                "player_club_id": [12, 30, 30, 30, 40, 31],
                "minutes_played": [90, 60, 60, 90, 45, 45],
            }
        ),
    }
    for name, table in tables.items():
        con.register(name, table)
    assert season_clubs(con).to_dict("list") == {
        "player_id": [101, 101, 102], "season": [2015, 2016, 2016], "club_id": [30, 30, 31],
        "minutes": [120, 90, 45],
    }  # fmt: skip


def test_a_players_first_half_club_comes_from_appearances_then_transfers():
    con = duckdb.connect()
    tables = {
        "player_map": pd.DataFrame({"sb_player_id": [101, 102, 103], "tm_player_id": [1, 2, 3]}),
        # player 1: more minutes at club 30 by December, club 12 from January
        "tm_appearances": pd.DataFrame(
            {
                "player_id": [1, 1, 1, 1],
                "player_club_id": [30, 30, 12, 12],
                "date": pd.to_datetime(["2016-08-20", "2016-11-02", "2016-09-01", "2017-02-01"]),
                "minutes_played": [90, 90, 120, 90],
            }
        ),
        # player 1's transfer is ignored; player 2 went out on loan after a loan's end; player 3
        # moved in January
        "tm_transfers": pd.DataFrame(
            {
                "player_id": [1, 2, 2, 3],
                "transfer_date": pd.to_datetime(
                    ["2016-07-01", "2016-06-30", "2016-08-12", "2017-01-15"]
                ),
                "to_club_id": [77, 40, 41, 50],
            }
        ),
    }
    for name, table in tables.items():
        con.register(name, table)
    assert first_half_clubs(con, 2016).to_dict("list") == {
        "player_id": [101, 102], "club_id": [30, 41], "source": ["appearances", "transfer"],
    }  # fmt: skip


def test_league_share_is_of_the_clubs_league_minutes_with_zero_for_none():
    con = duckdb.connect()
    tables = {
        "player_map": pd.DataFrame({"sb_player_id": [101], "tm_player_id": [1]}),
        "tm_competitions": pd.DataFrame(
            {"competition_id": ["IT1", "CIT"], "type": ["domestic_league", "domestic_cup"]}
        ),
        "tm_games": pd.DataFrame(
            {
                "game_id": [1, 2, 3, 4],
                "competition_id": ["IT1", "IT1", "CIT", "IT1"],
                "season": [2016, 2016, 2016, 2015],
                "home_club_id": [12, 99, 12, 12],
                "away_club_id": [99, 12, 99, 99],
            }
        ),
        # 90 + 45 league minutes in 2016/17, the cup and 2015/16 left out
        "tm_appearances": pd.DataFrame(
            {
                "player_id": [1, 1, 1, 1],
                "game_id": [1, 2, 3, 4],
                "player_club_id": [12] * 4,
                "minutes_played": [90, 45, 90, 90],
            }
        ),
    }
    for name, table in tables.items():
        con.register(name, table)
    pairs = pd.DataFrame({"player_id": [101, 101], "club_id": [12, 99]}, index=[5, 6])
    share = league_share(con, 2016, pairs)
    assert share.to_dict() == {5: pytest.approx(135 / 180), 6: 0.0}


def test_coaches_at_the_end_of_one_season_and_the_start_of_the_next():
    con = duckdb.connect()
    con.register(
        "tm_competitions",
        pd.DataFrame({"competition_id": ["GB1", "CGB"], "type": ["domestic_league", "cup"]}),
    )
    con.register(
        "tm_games",
        pd.DataFrame(
            {
                "competition_id": ["GB1", "GB1", "GB1", "CGB", "GB1"],
                "season": [2015, 2015, 2016, 2016, 2016],
                "date": pd.to_datetime(
                    ["2016-03-01", "2016-05-15", "2016-08-13", "2016-08-01", "2016-08-20"]
                ),
                "home_club_id": [281, 99, 281, 281, 99],
                "away_club_id": [99, 281, 99, 99, 281],
                "home_club_manager_name": ["Pellegrini", "A", "Guardiola", "Cup", "A"],
                "away_club_manager_name": ["B", "Pellegrini", "A", "A", "Guardiola"],
            }
        ),
    )
    assert coaches(con, 2016).to_dict("index") == {
        99: {"before": "A", "after": "A"}, 281: {"before": "Pellegrini", "after": "Guardiola"},
    }  # fmt: skip

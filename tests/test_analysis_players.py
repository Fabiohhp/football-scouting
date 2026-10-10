from datetime import date

import duckdb
import pandas as pd
import pytest

from football_scouting.analysis.players import group_minute_columns, pool_player_seasons
from football_scouting.config import load_config

CFG = load_config()
PL, SA, BL = 2, 12, 9

# player, competition, matches played, starts, minutes by group
SEASONS = [
    (1, PL, 5, 3, {"CM": 300}),  # moves from the Premier League to Serie A in January
    (1, SA, 12, 10, {"W": 900}),
    (2, SA, 20, 20, {"CF": 1500}),
    (2, BL, 5, 5, {"CF": 500}),  # Bundesliga is outside the pool
    (3, PL, 0, 0, {}),  # unused substitute
    (4, PL, 10, 10, {"CB": 400, "FB": 400}),  # tie: CB comes first in config order
]


@pytest.fixture
def con():
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE competitions AS SELECT * FROM (VALUES "
        "(2, 27, 'Premier League', true), (12, 27, 'Serie A', true), "
        "(9, 27, '1. Bundesliga', false)) "
        "t(competition_id, season_id, competition_name, scouting_pool)"
    )
    cols = group_minute_columns(CFG)
    rows = []
    for player, comp, played, starts, mins in SEASONS:
        by_group = {f"minutes_{g.lower()}": m for g, m in mins.items()}
        rows.append(
            {"player_id": player, "team_id": comp * 100 + player, "competition_id": comp,
             "season_id": 27, "matches_played": played, "starts": starts,
             "minutes": float(sum(mins.values()))}
            | {c: float(by_group.get(c, 0)) for c in cols}
        )  # fmt: skip
    seasons = pd.DataFrame(rows)  # noqa: F841 (read by DuckDB below)
    con.execute("CREATE TABLE player_seasons AS SELECT * FROM seasons")
    con.execute(
        "CREATE TABLE players AS SELECT * FROM (VALUES (1, 'A'), (2, 'B'), (3, 'C'), (4, 'D')) "
        "t(player_id, player_name)"
    )
    con.execute(
        "CREATE TABLE player_map AS SELECT * FROM (VALUES (1, 11), (2, 12), (4, 14)) "
        "t(sb_player_id, tm_player_id)"
    )
    con.execute(
        "CREATE TABLE tm_players AS SELECT * FROM (VALUES "
        "(11, DATE '1990-06-30'), (12, NULL::DATE), (14, DATE '1996-01-01')) "
        "t(player_id, date_of_birth)"
    )
    return con


def test_one_row_per_pool_player_with_minutes_summed_over_pool_clubs(con):
    out = pool_player_seasons(con, CFG, age_on=date(2016, 6, 30)).set_index("player_id")
    assert list(out.index) == [1, 2, 4]  # unused substitute dropped
    assert out.loc[1, "minutes"] == 1200 and out.loc[1, "n_teams"] == 2
    assert out.loc[1, "n_leagues"] == 2 and out.loc[1, "league"] == "Serie A"
    assert out.loc[1, "max_team_minutes"] == 900
    assert out.loc[2, "minutes"] == 1500 and out.loc[2, "n_teams"] == 1  # Bundesliga left out


def test_primary_position_group_and_share(con):
    out = pool_player_seasons(con, CFG, age_on=date(2016, 6, 30)).set_index("player_id")
    assert out.loc[1, "position_group"] == "W"
    assert out.loc[1, "comparison_group"] == "AMW"
    assert out.loc[1, "primary_share"] == pytest.approx(0.75)
    assert out.loc[4, "position_group"] == "CB"
    assert out.loc[4, "primary_share"] == pytest.approx(0.5)


def test_age_on_date(con):
    out = pool_player_seasons(con, CFG, age_on=date(2016, 6, 30)).set_index("player_id")
    assert out.loc[1, "age"] == pytest.approx(26.0, abs=0.01)
    assert pd.isna(out.loc[2, "age"])

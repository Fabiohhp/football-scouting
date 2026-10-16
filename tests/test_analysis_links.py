import pandas as pd

from football_scouting.analysis.links import side_by_side


def test_side_by_side_keeps_the_games_both_sources_record_for_each_pair():
    sb = pd.DataFrame(
        {
            "match_id": [1, 2, 1],
            "game_id": [10, 20, 10],
            "team_id": [5, 5, 5],
            "sb_player_id": [100, 100, 101],
            "goals": [1, 0, 0],
            "cards": [0, 1, 0],
            "minutes": [90.0, 60.0, 30.0],
        }
    )
    tm = pd.DataFrame(
        {
            "game_id": [10, 10, 10, 20],
            "team_id": [5, 5, 6, 5],
            "tm_player_id": [900, 901, 900, 900],
            "goals": [1, 0, 0, 0],
            "cards": [0, 0, 0, 1],
            "minutes": [90, 30, 90, 61],
        }
    )
    # A link, and an alternative for the same player: player 901 shares only game 10.
    pairs = pd.DataFrame(
        {"sb_player_id": [100, 100], "team_id": [5, 5], "tm_player_id": [900, 901]}
    )
    out = side_by_side(sb, tm, pairs).sort_values(["tm_player_id", "game_id"])
    assert out[["tm_player_id", "game_id"]].values.tolist() == [[900, 10], [900, 20], [901, 10]]
    assert out.sb_goals.tolist() == [1, 0, 1] and out.tm_goals.tolist() == [1, 0, 0]
    assert out.sb_minutes.tolist() == [90.0, 60.0, 90.0] and out.tm_minutes.tolist() == [90, 61, 30]


def test_side_by_side_matches_the_team_the_player_appeared_for():
    # Player 900 appears in game 10 for team 6 (the opponent): no shared game for team 5.
    sb = pd.DataFrame(
        {"match_id": [1], "game_id": [10], "team_id": [5], "sb_player_id": [100],
         "goals": [0], "cards": [0], "minutes": [90.0]}
    )  # fmt: skip
    tm = pd.DataFrame(
        {"game_id": [10], "team_id": [6], "tm_player_id": [900], "goals": [0], "cards": [0],
         "minutes": [90]}
    )  # fmt: skip
    pairs = pd.DataFrame({"sb_player_id": [100], "team_id": [5], "tm_player_id": [900]})
    assert side_by_side(sb, tm, pairs).empty

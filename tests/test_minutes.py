"""Minutes played on synthetic matches with known answers.

Match 1: first half lasts 46:00 (2,760 s), second half 49:00 (2,940 s); the match ends at
5,700 s of real time. In real time, second-half clock 45:00 is 2,760 s.
"""

import duckdb
import pytest

from football_scouting.config import load_config
from football_scouting.model.minutes import build_minutes

P1, P2 = 2760, 2940
END = P1 + P2

STINTS = [
    # player, position_id, from, from_period, to, to_period, start_reason, end_reason
    (1, 23, "00:00", 1, None, None, "Starting XI", "Final Whistle"),  # full match
    (2, 19, "00:00", 1, "59:11", 2, "Starting XI", "Substitution - Off (Tactical)"),
    (3, 19, "59:11", 2, None, None, "Substitution - On (Tactical)", "Final Whistle"),
    (4, 3, "45:30", 1, None, None, "Substitution - On (Injury)", "Final Whistle"),  # 1st-half ST
    (5, 2, "00:00", 1, None, None, "Starting XI", "Final Whistle"),  # sent off at 70:00
    (6, 10, "00:00", 1, "30:00", 1, "Starting XI", "Player Off"),  # treatment, back at 32:00
    (6, 10, "32:00", 1, "60:00", 2, "Player On", "Tactical Shift"),
    (6, 15, "60:00", 2, None, None, "Tactical Shift", "Final Whistle"),
    (7, 1, "00:00", 1, "03:00", 1, "Starting XI", "Tactical Shift"),  # sent off at 02:00
    (7, 19, "03:00", 1, None, None, "Tactical Shift", "Final Whistle"),  # starts after card
    (8, 5, "00:00", 1, "50:00", 1, "Starting XI", "Tactical Shift"),  # clock past half length
    (8, 5, "45:00", 2, None, None, "Tactical Shift", "Final Whistle"),
    # Back from treatment and replaced at once; the lineup forgets the substitution.
    (10, 3, "00:00", 1, "17:05", 1, "Starting XI", "Player Off"),
    (10, 3, "18:23", 1, None, None, "Player On", "Final Whistle"),
    # Overlapping stints for the same player (55:00-60:00 listed twice).
    (11, 4, "00:00", 1, "60:00", 2, "Starting XI", "Player Off"),
    (11, 4, "55:00", 2, None, None, "Player On", "Final Whistle"),
]


@pytest.fixture
def con():
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE periods AS SELECT * FROM (VALUES (1, 1, ?), (1, 2, ?)) "
        "t(match_id, period, duration_seconds)",
        [float(P1), float(P2)],
    )
    con.execute(
        "CREATE TABLE stints (match_id BIGINT, team_id BIGINT, player_id BIGINT, "
        "position_id BIGINT, position VARCHAR, from_clock VARCHAR, from_period BIGINT, "
        "to_clock VARCHAR, to_period BIGINT, start_reason VARCHAR, end_reason VARCHAR)"
    )
    con.executemany(
        "INSERT INTO stints VALUES (1, 10, ?, ?, 'pos', ?, ?, ?, ?, ?, ?)",
        [list(s) for s in STINTS],
    )
    con.execute(
        "CREATE TABLE squads AS SELECT 1 AS match_id, 10 AS team_id, i AS player_id, "
        "i AS jersey_number FROM range(1, 12) t(i)"  # player 9 is an unused substitute
    )
    con.execute(
        "CREATE TABLE dismissals AS SELECT * FROM (VALUES "
        "(1, 10, 5, '70:00', 2, 'Red Card'), (1, 10, 7, '02:00', 1, 'Second Yellow')) "
        "t(match_id, team_id, player_id, card_clock, card_period, card_type)"
    )
    con.execute(
        "CREATE TABLE substitutions AS SELECT * FROM (VALUES "
        "(1, 10, 2, '59:11', 2), (1, 10, 10, '18:23', 1)) "
        "t(match_id, team_id, player_id, sub_clock, sub_period)"
    )
    build_minutes(con, load_config().position_groups)
    return con


def seconds(con, player_id):
    return con.execute(
        "SELECT seconds_played FROM player_matches WHERE player_id = ?", [player_id]
    ).fetchone()[0]


def test_full_match_counts_stoppage_time(con):
    assert seconds(con, 1) == END


def test_substitution_splits_time_in_real_seconds(con):
    sub_time = P1 + (59 * 60 + 11 - 45 * 60)
    assert seconds(con, 2) == sub_time
    assert seconds(con, 3) == END - sub_time


def test_first_half_stoppage_time_substitution(con):
    assert seconds(con, 4) == END - (45 * 60 + 30)


def test_red_card_ends_time_on_pitch(con):
    assert seconds(con, 5) == P1 + 25 * 60
    row = con.execute(
        "SELECT dismissed, dismissal_seconds FROM player_matches WHERE player_id = 5"
    ).fetchone()
    assert row == (True, P1 + 25 * 60)


def test_temporary_absence_is_not_counted(con):
    assert seconds(con, 6) == END - 120
    assert (
        con.execute("SELECT main_position_id FROM player_matches WHERE player_id = 6").fetchone()[0]
        == 10
    )


def test_stints_after_a_dismissal_are_dropped(con):
    assert seconds(con, 7) == 120
    positions = con.execute(
        "SELECT position_id, truncated_by FROM player_positions WHERE player_id = 7"
    ).fetchall()
    assert positions == [(1, "dismissal")]


def test_substitution_event_ends_time_even_if_lineup_does_not(con):
    assert seconds(con, 10) == 17 * 60 + 5
    row = con.execute(
        "SELECT substituted_off, substitution_seconds FROM player_matches WHERE player_id = 10"
    ).fetchone()
    assert row == (True, 18 * 60 + 23)


def test_clock_beyond_period_end_is_clamped(con):
    assert seconds(con, 8) == END


def test_unused_substitute_has_zero_minutes(con):
    row = con.execute(
        "SELECT played, started, seconds_played, n_stints FROM player_matches WHERE player_id = 9"
    ).fetchone()
    assert row == (False, False, 0, 0)


def test_position_groups_and_starts(con):
    rows = dict(con.execute("SELECT player_id, main_position_group FROM player_matches").fetchall())
    assert rows[1] == "CF" and rows[4] == "CB" and rows[5] == "FB" and rows[7] == "GK"
    starters = {
        r[0] for r in con.execute("SELECT player_id FROM player_matches WHERE started").fetchall()
    }
    assert starters == {1, 2, 5, 6, 7, 8, 10, 11}


def test_overlapping_stints_are_not_counted_twice(con):
    assert seconds(con, 11) == END
    trimmed = con.execute(
        "SELECT overlap_trimmed FROM player_positions WHERE player_id = 11 ORDER BY start_seconds"
    ).fetchall()
    assert trimmed == [(False,), (True,)]


def test_exit_kind_is_the_first_exit(con):
    rows = dict(
        con.execute(
            "SELECT player_id, exit_kind FROM player_matches WHERE exit_kind IS NOT NULL"
        ).fetchall()
    )
    assert rows == {2: "substitution", 5: "dismissal", 7: "dismissal", 10: "substitution"}

"""Data quality tests on the processed tables. Run with `make dq` (needs `make model links`)."""

from __future__ import annotations

import duckdb
import pytest

from football_scouting.config import load_config
from football_scouting.model.statsbomb_tables import EVENT_TABLES

pytestmark = pytest.mark.data

CFG = load_config()
SB = CFG.paths.processed / "statsbomb"
TM = CFG.paths.processed / "transfermarkt"
LINKS = CFG.paths.processed / "links"


@pytest.fixture(scope="module")
def con():
    if not (SB / "events.parquet").exists() or not (LINKS / "player_map.parquet").exists():
        pytest.skip("processed data not built (run `make model links`)")
    con = duckdb.connect()
    for d in (SB, TM, LINKS):
        prefix = "tm_" if d == TM else ""
        for f in d.glob("*.parquet"):
            con.execute(f"CREATE VIEW {prefix}{f.stem} AS SELECT * FROM read_parquet('{f}')")
    return con


def one(con, sql: str):
    return con.execute(sql).fetchone()[0]


# -- events ---------------------------------------------------------------------------------


def test_no_duplicate_events(con):
    assert one(con, "SELECT count(*) - count(DISTINCT event_id) FROM events") == 0
    assert one(con, "SELECT count(*) - count(DISTINCT (match_id, event_index)) FROM events") == 0


def test_event_count_matches_interim_layer(con):
    interim = CFG.paths.interim / "statsbomb" / "events" / "*.parquet"
    assert one(con, "SELECT count(*) FROM events") == one(
        con, f"SELECT count(*) FROM read_parquet('{interim}')"
    )


def test_goals_in_events_match_final_scores(con):
    mismatches = one(
        con,
        """
        WITH goals AS (
            SELECT match_id, team_id, count(*) AS goals FROM events
            WHERE (type = 'Shot' AND event_id IN (SELECT event_id FROM shots
                                                  WHERE outcome = 'Goal'))
               OR type = 'Own Goal For'
            GROUP BY ALL)
        SELECT count(*) FROM matches m
        LEFT JOIN goals h ON h.match_id = m.match_id AND h.team_id = m.home_team_id
        LEFT JOIN goals a ON a.match_id = m.match_id AND a.team_id = m.away_team_id
        WHERE coalesce(h.goals, 0) <> m.home_score OR coalesce(a.goals, 0) <> m.away_score
        """,
    )
    assert mismatches == 0


def test_event_types_tables_partition_events(con):
    for table in EVENT_TABLES:
        n_table = one(con, f"SELECT count(*) FROM {table.name}")
        n_events = one(
            con,
            f"SELECT count(*) FROM events WHERE type = '{table.event_type.replace(chr(39), '')}'",
        )
        assert n_table == n_events, table.name
        assert one(con, f"SELECT count(*) FROM {table.name} ANTI JOIN events USING (event_id)") == 0


def test_event_times_within_periods(con):
    """Only cards (Bad Behaviour) may come after the whistle; other events within 2 s."""
    late = one(
        con,
        "SELECT count(*) FROM events e JOIN periods p USING (match_id, period) "
        "WHERE e.period_seconds > p.duration_seconds + 2 AND e.type <> 'Bad Behaviour'",
    )
    assert late == 0


def test_coordinates_on_the_pitch(con):
    off = one(
        con,
        "SELECT count(*) FROM events WHERE x NOT BETWEEN 0 AND 121 OR y NOT BETWEEN 0 AND 81",
    )
    assert off == 0


# -- referential integrity ------------------------------------------------------------------


def test_events_reference_known_matches_teams_and_players(con):
    assert one(con, "SELECT count(*) FROM events ANTI JOIN matches USING (match_id)") == 0
    assert (
        one(
            con,
            "SELECT count(*) FROM events e JOIN matches m USING (match_id) "
            "WHERE e.team_id NOT IN (m.home_team_id, m.away_team_id)",
        )
        == 0
    )
    assert (
        one(
            con,
            "SELECT count(*) FROM events WHERE player_id IS NOT NULL "
            "AND player_id NOT IN (SELECT player_id FROM players)",
        )
        == 0
    )


def test_player_matches_reference_match_teams(con):
    bad = one(
        con,
        "SELECT count(*) FROM player_matches pm JOIN matches m USING (match_id) "
        "WHERE pm.team_id NOT IN (m.home_team_id, m.away_team_id)",
    )
    assert bad == 0
    assert one(con, "SELECT count(*) FROM player_matches ANTI JOIN players USING (player_id)") == 0


def test_match_teams_exist_in_teams(con):
    missing = one(
        con,
        "SELECT count(*) FROM (SELECT home_team_id AS team_id, competition_id, season_id "
        "FROM matches UNION SELECT away_team_id, competition_id, season_id FROM matches) "
        "ANTI JOIN teams USING (team_id, competition_id, season_id)",
    )
    assert missing == 0


def test_names_have_no_escaped_apostrophes(con):
    assert one(con, "SELECT count(*) FROM players WHERE player_name LIKE '%''''%'") == 0
    assert one(con, "SELECT count(*) FROM teams WHERE team_name LIKE '%''''%'") == 0


# -- minutes played -------------------------------------------------------------------------


def test_starters_are_the_starting_xi(con):
    """Starters (on the pitch at kick-off) are exactly the players of the Starting XI event."""
    diff = one(
        con,
        """
        WITH xi AS (
            SELECT match_id, team_id, unnest(lineup).player_id AS player_id
            FROM formations WHERE type = 'Starting XI'),
        st AS (SELECT match_id, team_id, player_id FROM player_matches WHERE started)
        SELECT (SELECT count(*) FROM (SELECT * FROM xi EXCEPT SELECT * FROM st))
             + (SELECT count(*) FROM (SELECT * FROM st EXCEPT SELECT * FROM xi))
        """,
    )
    assert diff == 0


def test_eleven_starters_per_team(con):
    bad = one(
        con,
        "SELECT count(*) FROM (SELECT match_id, team_id, count(*) FILTER (WHERE started) AS n "
        "FROM player_matches GROUP BY ALL) WHERE n <> 11",
    )
    assert bad == 0


def test_minutes_bounded_by_match_length(con):
    bad = one(
        con,
        "SELECT count(*) FROM player_matches "
        "WHERE seconds_played < 0 OR seconds_played > match_end_seconds + 1e-6",
    )
    assert bad == 0


def test_never_more_than_eleven_on_the_pitch(con):
    peak = one(
        con,
        """
        WITH changes AS (
            SELECT match_id, team_id, start_seconds AS t, 1 AS d FROM player_positions
            UNION ALL
            SELECT match_id, team_id, end_seconds, -1 FROM player_positions)
        SELECT max(n) FROM (
            SELECT sum(d) OVER (PARTITION BY match_id, team_id ORDER BY t, d
                                ROWS UNBOUNDED PRECEDING) AS n
            FROM changes)
        """,
    )
    assert peak == 11


def test_team_time_explained_by_dismissals_and_absences(con):
    """Per team-match: 11 x match length = time played + time lost to dismissals + time
    players were off the pitch without a replacement (treatment, permanent injury)."""
    worst = one(
        con,
        """
        WITH st AS (
            SELECT pp.match_id, pp.team_id, pp.end_seconds, pp.end_reason, pp.truncated_by,
                   lead(pp.start_seconds) OVER (PARTITION BY pp.match_id, pp.player_id
                                                ORDER BY pp.start_seconds) AS next_start,
                   coalesce(pm.substitution_seconds, pm.dismissal_seconds,
                            pm.match_end_seconds) AS exit_seconds
            FROM player_positions pp JOIN player_matches pm USING (match_id, player_id)),
        absent AS (
            SELECT match_id, team_id,
                   sum(CASE WHEN next_start IS NOT NULL THEN next_start - end_seconds
                            WHEN end_reason LIKE 'Player Off%' AND truncated_by IS NULL
                            THEN greatest(exit_seconds - end_seconds, 0)
                            ELSE 0 END) AS seconds
            FROM st GROUP BY ALL),
        t AS (
            SELECT match_id, team_id, any_value(match_end_seconds) AS d,
                   sum(seconds_played) AS played,
                   sum(CASE WHEN exit_kind = 'dismissal'
                            THEN match_end_seconds - exit_seconds ELSE 0 END) AS lost
            FROM player_matches GROUP BY ALL)
        SELECT max(abs(11 * t.d - t.played - t.lost - coalesce(a.seconds, 0)))
        FROM t LEFT JOIN absent a USING (match_id, team_id)
        """,
    )
    assert worst <= 30


def test_season_minutes_by_group_add_up(con):
    """Minutes per position group are never NULL and add up to the season minutes."""
    group_cols = [f"minutes_{g.code.lower()}" for g in CFG.position_groups]
    nulls = " OR ".join(f"{c} IS NULL" for c in group_cols)
    assert one(con, f"SELECT count(*) FROM player_seasons WHERE {nulls}") == 0
    worst = one(
        con, f"SELECT max(abs(minutes - ({' + '.join(group_cols)}))) FROM player_seasons"
    )
    assert worst < 1e-6


def test_player_events_fall_within_time_on_the_pitch(con):
    """Fewer than 1 in 100,000 on-ball events by a player outside his time on the pitch."""
    outside, total = con.execute(
        """
        WITH e AS (
            SELECT match_id, player_id, match_seconds FROM events
            WHERE player_id IS NOT NULL AND type NOT IN (
                'Substitution', 'Bad Behaviour', 'Player Off', 'Player On', 'Starting XI',
                'Tactical Shift', 'Foul Committed'))
        SELECT count(*) FILTER (WHERE NOT EXISTS (
                   SELECT 1 FROM player_positions p
                   WHERE p.match_id = e.match_id AND p.player_id = e.player_id
                     AND e.match_seconds BETWEEN p.start_seconds - 5 AND p.end_seconds + 5)),
               count(*)
        FROM e
        """
    ).fetchone()
    assert outside / total < 1e-5


# -- links to Transfermarkt -----------------------------------------------------------------


def test_every_match_and_team_is_linked(con):
    assert one(con, "SELECT count(*) FROM matches ANTI JOIN match_map USING (match_id)") == 0
    assert one(con, "SELECT count(*) - count(DISTINCT game_id) FROM match_map") == 0
    assert one(con, "SELECT count(*) FROM teams ANTI JOIN team_map USING (team_id)") == 0


def test_every_player_who_played_is_linked_one_to_one(con):
    unlinked = one(
        con,
        "SELECT count(DISTINCT player_id) FROM player_matches WHERE played "
        "AND player_id NOT IN (SELECT sb_player_id FROM player_map)",
    )
    assert unlinked == 0
    assert one(con, "SELECT count(*) - count(DISTINCT tm_player_id) FROM player_map") == 0
    assert (
        one(con, "SELECT count(*) FROM player_map ANTI JOIN tm_players "
                 "ON tm_players.player_id = player_map.tm_player_id")
        == 0
    )


def test_every_linked_player_has_a_date_of_birth(con):
    missing = one(
        con,
        "SELECT count(*) FROM player_map m JOIN tm_players tp ON tp.player_id = m.tm_player_id "
        "WHERE tp.date_of_birth IS NULL",
    )
    assert missing == 0


# -- documentation ---------------------------------------------------------------------------


def test_data_dictionary_documents_every_column(con):
    from football_scouting.model.dictionary import check

    assert check(CFG) == []

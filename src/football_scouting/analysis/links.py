"""Game records of both sources side by side: checks of the StatsBomb -> Transfermarkt links.

The player links (`model/entity_resolution.py`) rest on two signals: the games a player played
and the name. Goals, cards and minutes are recorded separately by both sources and were never
used to match, so they test a link independently. `side_by_side` lines them up for any pairing
of StatsBomb and Transfermarkt players, which lets a link and its alternatives be checked the
same way.

Conventions:
- cards are yellow and red cards together: both sources count a second yellow as two yellow
  cards, but they sometimes disagree on whether a dismissal was a second yellow or a straight
  red;
- minutes are on the match clock, as Transfermarkt counts them (90 for a full match, stoppage
  time left out). StatsBomb's real time on the pitch is converted half by half: a time in the
  first half's stoppage counts as minute 45, one in the second half's as minute 90.
"""

from __future__ import annotations

import duckdb
import pandas as pd

PAIR_KEYS = ["sb_player_id", "team_id", "tm_player_id"]
RECORDS = ["goals", "cards", "minutes"]


def statsbomb_games(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """One row per player and match played in StatsBomb, with the linked Transfermarkt game."""
    return con.sql("""
        WITH first_half AS (
            SELECT match_id, duration_seconds AS h1 FROM periods WHERE period = 1),
        goals AS (
            SELECT match_id, player_id, count(*) AS goals FROM shots
            WHERE outcome = 'Goal' GROUP BY ALL),
        cards AS (
            SELECT match_id, player_id, count(*) AS cards
            FROM (SELECT match_id, player_id, card FROM fouls_committed
                  UNION ALL SELECT match_id, player_id, card FROM bad_behaviours)
            WHERE card IS NOT NULL GROUP BY ALL),
        clock AS (
            SELECT pm.match_id, pm.competition_id, pm.season_id, pm.team_id, pm.player_id,
                   CASE WHEN pm.on_seconds < h.h1 THEN least(pm.on_seconds / 60, 45)
                        ELSE 45 + least((pm.on_seconds - h.h1) / 60, 45) END AS on_minute,
                   CASE WHEN pm.off_seconds < h.h1 THEN least(pm.off_seconds / 60, 45)
                        ELSE 45 + least((pm.off_seconds - h.h1) / 60, 45) END AS off_minute
            FROM player_matches pm JOIN first_half h USING (match_id)
            WHERE pm.played)
        SELECT c.match_id, mm.game_id, c.competition_id, c.season_id, c.team_id,
               c.player_id AS sb_player_id, coalesce(g.goals, 0) AS goals,
               coalesce(k.cards, 0) AS cards, c.off_minute - c.on_minute AS minutes
        FROM clock c
        JOIN match_map mm USING (match_id)
        LEFT JOIN goals g ON g.match_id = c.match_id AND g.player_id = c.player_id
        LEFT JOIN cards k ON k.match_id = c.match_id AND k.player_id = c.player_id
        ORDER BY c.match_id, c.player_id
    """).df()


def transfermarkt_games(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """One row per Transfermarkt appearance in a linked game, with the StatsBomb team the
    player appeared for."""
    return con.sql("""
        SELECT a.game_id, t.team_id, a.player_id AS tm_player_id, a.goals,
               a.yellow_cards + a.red_cards AS cards, a.minutes_played AS minutes
        FROM tm_appearances a
        JOIN match_map mm USING (game_id)
        JOIN team_map t ON t.club_id = a.player_club_id
             AND t.competition_id = mm.competition_id AND t.season_id = mm.season_id
        ORDER BY a.game_id, a.player_id
    """).df()


def side_by_side(sb: pd.DataFrame, tm: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    """The games both sources record for each pair of `sb_player_id`, `team_id` and
    `tm_player_id`, with each record as `sb_<record>` and `tm_<record>`."""
    out = pairs[PAIR_KEYS].merge(sb, on=["sb_player_id", "team_id"])
    return out.merge(tm, on=["game_id", "team_id", "tm_player_id"], suffixes=("", "_tm")).rename(
        columns={**{r: f"sb_{r}" for r in RECORDS}, **{f"{r}_tm": f"tm_{r}" for r in RECORDS}}
    )

"""Minutes played per player per match, in real time on the pitch (stoppage time included).

Clocks. StatsBomb lineups give each position stint as a match clock "MM:SS" plus a period;
the clock restarts at 45:00 in the second half however long the first half was. Real time is
rebuilt from the actual length of each period:

    real = start of the period in real time + (clock - clock value at which the period starts)

Final exits. A player who is sent off or substituted cannot come back, but lineups do not
always end the stint there:
- Dismissals: in 413 of the 420 dismissals in 2015/16 the stint runs to the final whistle.
- Substitutions: when a player returns from treatment ("Player On") and is replaced at once,
  the lineup can keep him on until the final whistle while the Substitution event takes him off.
So a player's time ends at his first exit, the earlier of the card (lineup `cards`) and the
Substitution event that takes him off; stints starting after it are dropped.

Temporary absences ("Player Off" / "Player On", e.g. treatment) are separate stints, so the
time off the pitch is not counted. A few lineups list overlapping stints for the same player;
the later stint is trimmed to start where the earlier one ends, so no time is counted twice.

Inputs (DuckDB relations, passed by name):
    periods(match_id, period, duration_seconds)
    squads(match_id, team_id, player_id, jersey_number)        every listed player
    stints(match_id, team_id, player_id, position_id, position,
           from_clock, from_period, to_clock, to_period, start_reason, end_reason)
    dismissals(match_id, team_id, player_id, card_clock, card_period, card_type)
    substitutions(match_id, team_id, player_id, sub_clock, sub_period)   player going off

Starters are the players on the pitch at kick-off (a stint starting at 0): two lineups label
some starters' first stint "Tactical Shift" instead of "Starting XI".

Outputs (DuckDB tables): `player_positions` (one row per stint with time > 0) and
`player_matches` (one row per squad player per match).
"""

from __future__ import annotations

import duckdb

from football_scouting.config import PositionGroup

# Value of the match clock when each period starts.
PERIOD_CLOCK_START = {1: 0, 2: 45 * 60, 3: 90 * 60, 4: 105 * 60}


def clock_seconds(col: str) -> str:
    """SQL: 'MM:SS' (minutes may exceed 59) -> seconds."""
    return (
        f"(CAST(split_part({col}, ':', 1) AS INTEGER) * 60 "
        f"+ CAST(split_part({col}, ':', 2) AS INTEGER))"
    )


def _clock_start(period: str) -> str:
    cases = " ".join(f"WHEN {p} THEN {s}" for p, s in PERIOD_CLOCK_START.items())
    return f"(CASE {period} {cases} END)"


def _to_real(clock: str, period: str, bounds: str) -> str:
    """SQL: clock + period -> real seconds since kick-off, clamped to the period."""
    raw = f"{bounds}.start_seconds + {clock_seconds(clock)} - {_clock_start(period)}"
    return f"least(greatest({raw}, {bounds}.start_seconds), {bounds}.end_seconds)"


def position_group_case(groups: tuple[PositionGroup, ...], col: str = "position_id") -> str:
    cases = " ".join(
        f"WHEN {col} IN ({', '.join(map(str, g.position_ids))}) THEN '{g.code}'" for g in groups
    )
    return f"(CASE {cases} END)"


def build_minutes(
    con: duckdb.DuckDBPyConnection,
    groups: tuple[PositionGroup, ...],
    *,
    periods: str = "periods",
    squads: str = "squads",
    stints: str = "stints",
    dismissals: str = "dismissals",
    substitutions: str = "substitutions",
) -> None:
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE period_bounds AS
        SELECT match_id, period,
               coalesce(sum(duration_seconds) OVER w, 0) AS start_seconds,
               coalesce(sum(duration_seconds) OVER w, 0) + duration_seconds AS end_seconds,
               sum(duration_seconds) OVER (PARTITION BY match_id) AS match_end_seconds
        FROM {periods}
        WINDOW w AS (PARTITION BY match_id ORDER BY period
                     ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE exits AS
        WITH x AS (
            SELECT d.match_id, d.player_id, 'dismissal' AS kind,
                   {_to_real("d.card_clock", "d.card_period", "b")} AS seconds
            FROM {dismissals} d
            JOIN period_bounds b ON b.match_id = d.match_id AND b.period = d.card_period
            UNION ALL
            SELECT s.match_id, s.player_id, 'substitution',
                   {_to_real("s.sub_clock", "s.sub_period", "b")}
            FROM {substitutions} s
            JOIN period_bounds b ON b.match_id = s.match_id AND b.period = s.sub_period)
        SELECT match_id, player_id,
               min(seconds) FILTER (WHERE kind = 'dismissal') AS dismissal_seconds,
               min(seconds) FILTER (WHERE kind = 'substitution') AS substitution_seconds,
               min(seconds) AS exit_seconds,
               first(kind ORDER BY seconds, kind) AS exit_kind
        FROM x GROUP BY ALL
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE player_positions AS
        WITH real AS (
            SELECT s.match_id, s.team_id, s.player_id, s.position_id, s.position,
                   s.start_reason, s.end_reason,
                   {_to_real("s.from_clock", "s.from_period", "bf")} AS start_seconds,
                   CASE WHEN s.to_clock IS NULL THEN bf.match_end_seconds
                        ELSE {_to_real("s.to_clock", "s.to_period", "bt")} END AS stint_end
            FROM {stints} s
            JOIN period_bounds bf ON bf.match_id = s.match_id AND bf.period = s.from_period
            LEFT JOIN period_bounds bt ON bt.match_id = s.match_id AND bt.period = s.to_period
        )
        , cut AS (
            SELECT r.*,
                   least(r.stint_end, coalesce(x.exit_seconds, r.stint_end)) AS cut_end,
                   CASE WHEN x.exit_seconds < r.stint_end THEN x.exit_kind END AS truncated_by
            FROM real r LEFT JOIN exits x USING (match_id, player_id)
        ), trimmed AS (
            SELECT *, greatest(start_seconds, coalesce(max(cut_end) OVER (
                       PARTITION BY match_id, player_id ORDER BY start_seconds, cut_end
                       ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), start_seconds))
                       AS eff_start
            FROM cut
        )
        SELECT match_id, team_id, player_id, position_id, position,
               {position_group_case(groups, "position_id")} AS position_group,
               eff_start AS start_seconds, cut_end AS end_seconds,
               cut_end - eff_start AS seconds,
               start_reason, end_reason, truncated_by,
               eff_start > start_seconds AS overlap_trimmed
        FROM trimmed
        WHERE cut_end > eff_start
        ORDER BY match_id, team_id, player_id, start_seconds
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE player_matches AS
        WITH by_position AS (
            SELECT match_id, player_id, position_id, sum(seconds) AS seconds
            FROM player_positions GROUP BY ALL
        ),
        main AS (
            SELECT match_id, player_id,
                   first(position_id ORDER BY seconds DESC, position_id) AS main_position_id
            FROM by_position GROUP BY ALL
        ),
        agg AS (
            SELECT match_id, player_id,
                   sum(seconds) AS seconds_played,
                   min(start_seconds) = 0 AS started,
                   min(start_seconds) AS on_seconds,
                   max(end_seconds) AS off_seconds,
                   count(*) AS n_stints
            FROM player_positions GROUP BY ALL
        )
        SELECT q.match_id, q.team_id, q.player_id, q.jersey_number,
               coalesce(a.started, false) AS started,
               coalesce(a.seconds_played, 0) > 0 AS played,
               coalesce(a.seconds_played, 0) AS seconds_played,
               coalesce(a.seconds_played, 0) / 60.0 AS minutes_played,
               a.on_seconds, a.off_seconds,
               m.main_position_id,
               {position_group_case(groups, "m.main_position_id")} AS main_position_group,
               coalesce(a.n_stints, 0) AS n_stints,
               x.dismissal_seconds IS NOT NULL AS dismissed,
               x.dismissal_seconds,
               x.substitution_seconds IS NOT NULL AS substituted_off,
               x.substitution_seconds,
               CASE WHEN a.seconds_played > 0 THEN x.exit_kind END AS exit_kind,
               CASE WHEN a.seconds_played > 0 THEN x.exit_seconds END AS exit_seconds,
               b.match_end_seconds
        FROM {squads} q
        LEFT JOIN agg a USING (match_id, player_id)
        LEFT JOIN main m USING (match_id, player_id)
        LEFT JOIN exits x USING (match_id, player_id)
        JOIN (SELECT DISTINCT match_id, match_end_seconds FROM period_bounds) b USING (match_id)
        ORDER BY q.match_id, q.team_id, q.player_id
        """
    )

"""Build the processed StatsBomb tables (data/processed/statsbomb/*.parquet) from the interim layer.

Conventions applied here (documented in docs/DATA_DICTIONARY.md):
- Pitch: 120 x 80, origin top-left; every event is seen from the acting team, which attacks
  towards x = 120 (verified: mean shot x = 103, mean clearance x = 21; checked in full in
  notebooks/01_data_exploration.ipynb, section 6).
- Time: `period_seconds` is the time since the start of the period (the event `timestamp`);
  `match_seconds` is real time since kick-off, using the actual length of earlier periods.
- Flags: StatsBomb only writes boolean attributes when true (no `false` values exist in the
  raw data), so missing flags become false.
- `{id, name}` objects become the name, except player references, which keep the id.
- Names: escaped apostrophes are undone ("N''Golo Kanté" -> "N'Golo Kanté").
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import duckdb
from duckdb.sqltypes import DuckDBPyType

from football_scouting.config import Config
from football_scouting.ingest.statsbomb_parquet import interim_dir
from football_scouting.model.io import clean_name, copy_to_parquet
from football_scouting.model.minutes import build_minutes, position_group_case

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EventTable:
    name: str
    event_type: str
    struct: str | None  # type-specific attribute object in the raw event, if any
    prefix: str  # prepended to attribute names that collide with common columns


EVENT_TABLES = (
    EventTable("passes", "Pass", "pass", "pass"),
    EventTable("shots", "Shot", "shot", "shot"),
    EventTable("carries", "Carry", "carry", "carry"),
    EventTable("dribbles", "Dribble", "dribble", "dribble"),
    EventTable("pressures", "Pressure", None, "pressure"),
    EventTable("duels", "Duel", "duel", "duel"),
    EventTable("ball_recoveries", "Ball Recovery", "ball_recovery", "recovery"),
    EventTable("interceptions", "Interception", "interception", "interception"),
    EventTable("clearances", "Clearance", "clearance", "clearance"),
    EventTable("blocks", "Block", "block", "block"),
    EventTable("goalkeeper_actions", "Goal Keeper", "goalkeeper", "goalkeeper"),
    EventTable("fouls_committed", "Foul Committed", "foul_committed", "foul"),
    EventTable("fouls_won", "Foul Won", "foul_won", "foul"),
    EventTable("miscontrols", "Miscontrol", "miscontrol", "miscontrol"),
    EventTable("dispossessions", "Dispossessed", None, "dispossessed"),
    EventTable("dribbled_past", "Dribbled Past", None, "dribbled_past"),
    EventTable("ball_receipts", "Ball Receipt*", "ball_receipt", "receipt"),
    EventTable("fifty_fifties", "50/50", "50_50", "fifty_fifty"),
    EventTable("bad_behaviours", "Bad Behaviour", "bad_behaviour", "behaviour"),
)

# Attributes that reference a player: keep the id (`<field>_id`) rather than the name.
PLAYER_REFERENCES = {"recipient", "replacement"}

# Attribute names that would collide with a common event column (or be ambiguous) get a prefix.
PREFIXED_ATTRIBUTES = {"type", "position"}


def processed_dir(cfg: Config) -> Path:
    return cfg.paths.processed / "statsbomb"


def _seconds_from_timestamp(col: str) -> str:
    """SQL: 'HH:MM:SS.fff' -> seconds (double)."""
    return (
        f"(CAST(split_part({col}, ':', 1) AS INTEGER) * 3600 "
        f"+ CAST(split_part({col}, ':', 2) AS INTEGER) * 60 "
        f"+ CAST(split_part({col}, ':', 3) AS DOUBLE))"
    )


def common_columns(alias: str = "e", bounds: str = "pb") -> list[str]:
    """SELECT expressions for the columns every event table starts with."""
    e = alias
    return [
        f"{e}.id AS event_id",
        f"{e}.match_id",
        f"{e}.competition_id",
        f"{e}.season_id",
        f"{e}.index AS event_index",
        f"{e}.period",
        f"{e}.timestamp",
        f"{_seconds_from_timestamp(f'{e}.timestamp')} AS period_seconds",
        f"{bounds}.start_seconds + {_seconds_from_timestamp(f'{e}.timestamp')} AS match_seconds",
        f"{e}.minute",
        f"{e}.second",
        f"{e}.possession",
        f"{e}.possession_team.id AS possession_team_id",
        f"{e}.play_pattern.name AS play_pattern",
        f"{e}.team.id AS team_id",
        f"{e}.player.id AS player_id",
        f"{e}.position.id AS position_id",
        f"{e}.position.name AS position",
        f"{e}.location[1] AS x",
        f"{e}.location[2] AS y",
        f"{e}.duration",
        f"coalesce({e}.under_pressure, false) AS under_pressure",
        f"coalesce({e}.counterpress, false) AS counterpress",
        f"coalesce({e}.off_camera, false) AS off_camera",
        f"coalesce({e}.out, false) AS out",
    ]


def _is_id_name(dtype: DuckDBPyType) -> bool:
    return dtype.id == "struct" and [n for n, _ in dtype.children] == ["id", "name"]


def attribute_columns(table: EventTable, struct_type: DuckDBPyType, alias: str = "e") -> list[str]:
    """SELECT expressions flattening one type-specific attribute object."""
    exprs = []
    for field, dtype in struct_type.children:
        src = f'{alias}."{table.struct}"."{field}"'
        out = f"{table.prefix}_{field}" if field in PREFIXED_ATTRIBUTES else field
        if field == "end_location":
            exprs += [f"{src}[1] AS end_x", f"{src}[2] AS end_y"]
            if table.name == "shots":
                exprs.append(f"{src}[3] AS end_z")
        elif field == "freeze_frame":
            exprs.append(
                f"list_transform({src}, f -> {{'x': f.location[1], 'y': f.location[2], "
                f"'player_id': f.player.id, 'position_id': f.position.id, "
                f"'teammate': coalesce(f.teammate, false)}}) AS freeze_frame"
            )
        elif _is_id_name(dtype):
            exprs.append(
                f"{src}.id AS {field}_id" if field in PLAYER_REFERENCES else f"{src}.name AS {out}"
            )
        elif dtype.id == "boolean":
            exprs.append(f"coalesce({src}, false) AS {out}")
        elif dtype.id in {"struct", "list"}:
            raise ValueError(f"No flattening rule for {table.struct}.{field}: {dtype}")
        else:
            exprs.append(f"{src} AS {out}")
    if table.name == "passes":
        # StatsBomb spec: a pass without an outcome was completed.
        exprs.append(f'{alias}."pass".outcome IS NULL AS completed')
    return exprs


class StatsBombModel:
    """Builds every processed StatsBomb table with one DuckDB connection."""

    def __init__(self, con: duckdb.DuckDBPyConnection, cfg: Config):
        self.con, self.cfg = con, cfg
        self.out = processed_dir(cfg)
        i = interim_dir(cfg)
        con.execute(
            f"CREATE OR REPLACE VIEW ev AS SELECT * FROM read_parquet('{i}/events/*.parquet')"
        )
        con.execute(
            f"CREATE OR REPLACE VIEW lu AS SELECT * FROM read_parquet('{i}/lineups/*.parquet')"
        )
        con.execute(
            f"CREATE OR REPLACE VIEW ma AS SELECT * FROM read_parquet('{i}/matches.parquet')"
        )
        con.execute(
            f"CREATE OR REPLACE VIEW co AS SELECT * FROM read_parquet('{i}/competitions.parquet')"
        )
        self.counts: dict[str, int] = {}

    def write(self, name: str, select_sql: str) -> None:
        n = copy_to_parquet(self.con, select_sql, self.out / f"{name}.parquet")
        self.counts[name] = n
        log.info("%s: %d rows", name, n)

    def build_all(self) -> dict[str, int]:
        self.build_periods()
        self.build_competitions()
        self.build_matches()
        self.build_teams()
        self.build_players()
        self.build_minutes()
        self.build_player_seasons()
        self.build_events()
        self.build_event_tables()
        self.build_defensive_actions()
        self.build_formations()
        return self.counts

    # -- dimensions -------------------------------------------------------------------------

    def build_periods(self) -> None:
        self.con.execute(
            f"""
            CREATE OR REPLACE TABLE periods AS
            SELECT match_id, period,
                   max({_seconds_from_timestamp("timestamp")}) AS duration_seconds
            FROM ev WHERE type.name = 'Half End' GROUP BY ALL ORDER BY ALL
            """
        )
        self.con.execute(
            """
            CREATE OR REPLACE TEMP TABLE pb AS
            SELECT match_id, period,
                   coalesce(sum(duration_seconds) OVER w, 0) AS start_seconds
            FROM periods
            WINDOW w AS (PARTITION BY match_id ORDER BY period
                         ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
            """
        )
        self.write("periods", "SELECT * FROM periods")

    def build_competitions(self) -> None:
        rows = ", ".join(
            f"({c.competition_id}, {c.season_id}, {c.scouting_pool}, "
            f"'{c.transfermarkt_competition_id}', {c.transfermarkt_season})"
            for c in self.cfg.statsbomb.competitions
        )
        self.write(
            "competitions",
            f"""
            SELECT co.competition_id, co.season_id, co.competition_name, co.country_name,
                   co.season_name, co.competition_gender, cfg.scouting_pool,
                   cfg.tm_competition_id AS transfermarkt_competition_id,
                   cfg.tm_season AS transfermarkt_season
            FROM co JOIN (VALUES {rows})
                 cfg(competition_id, season_id, scouting_pool, tm_competition_id, tm_season)
                 USING (competition_id, season_id)
            ORDER BY ALL
            """,
        )

    def build_matches(self) -> None:
        pool = ", ".join(
            str(c.competition_id) for c in self.cfg.statsbomb.competitions if c.scouting_pool
        )
        self.write(
            "matches",
            f"""
            WITH p AS (
                SELECT match_id,
                       max(duration_seconds) FILTER (WHERE period = 1) AS period_1_seconds,
                       max(duration_seconds) FILTER (WHERE period = 2) AS period_2_seconds,
                       sum(duration_seconds) AS duration_seconds
                FROM periods GROUP BY ALL)
            SELECT m.match_id, m.competition.competition_id AS competition_id,
                   m.season.season_id AS season_id,
                   m.competition.competition_id IN ({pool}) AS scouting_pool,
                   CAST(m.match_date AS DATE) AS match_date, m.kick_off, m.match_week,
                   m.competition_stage.name AS competition_stage,
                   m.home_team.home_team_id AS home_team_id,
                   m.away_team.away_team_id AS away_team_id,
                   m.home_score, m.away_score,
                   {clean_name("m.home_team.managers[1].name")} AS home_manager,
                   {clean_name("m.away_team.managers[1].name")} AS away_manager,
                   {clean_name("m.stadium.name")} AS stadium,
                   {clean_name("m.referee.name")} AS referee,
                   m.metadata.data_version, m.metadata.shot_fidelity_version,
                   m.metadata.xy_fidelity_version,
                   p.period_1_seconds, p.period_2_seconds, p.duration_seconds
            FROM ma m JOIN p USING (match_id)
            ORDER BY match_date, match_id
            """,
        )

    def build_teams(self) -> None:
        self.write(
            "teams",
            f"""
            WITH t AS (
                SELECT home_team.home_team_id AS team_id,
                       home_team.home_team_name AS team_name,
                       home_team.country.name AS country,
                       competition.competition_id AS competition_id,
                       season.season_id AS season_id, match_id
                FROM ma
                UNION ALL
                SELECT away_team.away_team_id, away_team.away_team_name, away_team.country.name,
                       competition.competition_id, season.season_id, match_id
                FROM ma)
            SELECT team_id, {clean_name("mode(team_name)")} AS team_name, mode(country) AS country,
                   competition_id, season_id, count(DISTINCT match_id) AS matches
            FROM t GROUP BY team_id, competition_id, season_id
            ORDER BY competition_id, team_name
            """,
        )

    def build_players(self) -> None:
        self.write(
            "players",
            f"""
            WITH p AS (SELECT unnest(lineup) AS p FROM lu)
            SELECT p.player_id,
                   {clean_name("mode(p.player_name)")} AS player_name,
                   {clean_name("mode(p.player_nickname)")} AS player_nickname,
                   mode(p.country.name) AS country,
                   count(DISTINCT {clean_name("p.player_name")}) > 1 AS name_varies,
                   count(DISTINCT p.country.name) > 1 AS country_varies
            FROM p GROUP BY p.player_id ORDER BY p.player_id
            """,
        )

    # -- minutes and positions --------------------------------------------------------------

    def build_minutes(self) -> None:
        con = self.con
        con.execute(
            """
            CREATE OR REPLACE TEMP TABLE squads AS
            SELECT match_id, team_id, p.player_id, p.jersey_number
            FROM (SELECT match_id, team_id, unnest(lineup) AS p FROM lu)
            """
        )
        con.execute(
            """
            CREATE OR REPLACE TEMP TABLE stints AS
            SELECT match_id, team_id, player_id, s.position_id, s.position,
                   s."from" AS from_clock, s.from_period, s."to" AS to_clock, s.to_period,
                   s.start_reason, s.end_reason
            FROM (SELECT match_id, team_id, p.player_id, unnest(p.positions) AS s
                  FROM (SELECT match_id, team_id, unnest(lineup) AS p FROM lu))
            """
        )
        con.execute(
            """
            CREATE OR REPLACE TEMP TABLE dismissals AS
            SELECT match_id, team_id, player_id, c.time AS card_clock, c.period AS card_period,
                   c.card_type
            FROM (SELECT match_id, team_id, p.player_id, unnest(p.cards) AS c
                  FROM (SELECT match_id, team_id, unnest(lineup) AS p FROM lu))
            WHERE c.card_type IN ('Red Card', 'Second Yellow')
            """
        )
        con.execute(
            """
            CREATE OR REPLACE TEMP TABLE substitutions AS
            SELECT match_id, team.id AS team_id, player.id AS player_id,
                   printf('%02d:%02d', minute, second) AS sub_clock, period AS sub_period
            FROM ev WHERE type.name = 'Substitution'
            """
        )
        build_minutes(con, self.cfg.position_groups)
        cols = "m.competition.competition_id AS competition_id, m.season.season_id AS season_id"
        self.write(
            "player_matches",
            f"SELECT pm.match_id, {cols}, pm.* EXCLUDE (match_id) "
            "FROM player_matches pm JOIN ma m USING (match_id) ORDER BY ALL",
        )
        self.write(
            "player_positions",
            f"SELECT pp.match_id, {cols}, pp.* EXCLUDE (match_id) "
            "FROM player_positions pp JOIN ma m USING (match_id) "
            "ORDER BY pp.match_id, pp.team_id, pp.player_id, pp.start_seconds",
        )

    def build_player_seasons(self) -> None:
        groups = self.cfg.position_groups
        by_group = ", ".join(
            f"sum(pp.seconds) FILTER (WHERE pp.position_group = '{g.code}') / 60.0 "
            f"AS minutes_{g.code.lower()}"
            for g in groups
        )
        # 0, not NULL, for groups (or whole seasons) without minutes.
        group_cols = ", ".join(
            f"coalesce(g.minutes_{code}, 0) AS minutes_{code}"
            for code in (grp.code.lower() for grp in groups)
        )
        self.write(
            "player_seasons",
            f"""
            WITH pp AS (
                SELECT pp.*, m.competition.competition_id AS competition_id,
                       m.season.season_id AS season_id
                FROM player_positions pp JOIN ma m USING (match_id)),
            pm AS (
                SELECT pm.*, m.competition.competition_id AS competition_id,
                       m.season.season_id AS season_id
                FROM player_matches pm JOIN ma m USING (match_id)),
            by_position AS (
                SELECT player_id, team_id, competition_id, season_id, position_id,
                       sum(seconds) AS seconds
                FROM pp GROUP BY ALL),
            main AS (
                SELECT player_id, team_id, competition_id, season_id,
                       first(position_id ORDER BY seconds DESC, position_id) AS position_id
                FROM by_position GROUP BY ALL),
            groups AS (
                SELECT player_id, team_id, competition_id, season_id, {by_group}
                FROM pp GROUP BY ALL),
            totals AS (
                SELECT player_id, team_id, competition_id, season_id,
                       count(*) AS matches_in_squad,
                       count(*) FILTER (WHERE played) AS matches_played,
                       count(*) FILTER (WHERE started) AS starts,
                       sum(seconds_played) / 60.0 AS minutes,
                       count(*) FILTER (WHERE dismissed AND played) AS dismissals
                FROM pm GROUP BY ALL)
            SELECT t.player_id, t.team_id, t.competition_id, t.season_id,
                   t.matches_in_squad, t.matches_played, t.starts, t.minutes, t.dismissals,
                   m.position_id AS primary_position_id,
                   {position_group_case(groups, "m.position_id")} AS primary_position_group,
                   {group_cols}
            FROM totals t
            LEFT JOIN main m USING (player_id, team_id, competition_id, season_id)
            LEFT JOIN groups g USING (player_id, team_id, competition_id, season_id)
            ORDER BY t.competition_id, t.team_id, t.minutes DESC
            """,
        )

    # -- events ------------------------------------------------------------------------------

    def _from_events(self) -> str:
        return "ev e JOIN pb ON pb.match_id = e.match_id AND pb.period = e.period"

    def build_events(self) -> None:
        cols = ", ".join(common_columns())
        self.write(
            "events",
            f"SELECT {cols}, e.type.name AS type, e.related_events FROM {self._from_events()} "
            "ORDER BY e.match_id, e.index",
        )

    def build_event_tables(self) -> None:
        rel = self.con.sql("SELECT * FROM ev LIMIT 0")
        types = dict(zip(rel.columns, rel.types, strict=True))
        for table in EVENT_TABLES:
            cols = common_columns()
            if table.struct is not None:
                cols += attribute_columns(table, types[table.struct])
            event_type = table.event_type.replace("'", "''")
            self.write(
                table.name,
                f"SELECT {', '.join(cols)} FROM {self._from_events()} "
                f"WHERE e.type.name = '{event_type}' ORDER BY e.match_id, e.index",
            )

    def build_defensive_actions(self) -> None:
        cols = ", ".join(common_columns())
        actions = [
            (
                "Tackle",
                "e.duel.outcome.name",
                "e.type.name = 'Duel' AND e.duel.type.name = 'Tackle'",
            ),
            ("Interception", "e.interception.outcome.name", "e.type.name = 'Interception'"),
            ("Block", "NULL", "e.type.name = 'Block'"),
            ("Clearance", "NULL", "e.type.name = 'Clearance'"),
            (
                "Ball Recovery",
                "CASE WHEN e.ball_recovery.recovery_failure THEN 'Recovery Failure' END",
                "e.type.name = 'Ball Recovery'",
            ),
            ("Foul Committed", "NULL", "e.type.name = 'Foul Committed'"),
            ("50/50", 'e."50_50".outcome.name', "e.type.name = '50/50'"),
        ]
        union = " UNION ALL ".join(
            f"SELECT {cols}, '{action}' AS action, {outcome} AS outcome "
            f"FROM {self._from_events()} WHERE {where}"
            for action, outcome, where in actions
        )
        self.write("defensive_actions", f"SELECT * FROM ({union}) ORDER BY match_id, event_index")

    def build_formations(self) -> None:
        self.write(
            "formations",
            f"""
            SELECT e.id AS event_id, e.match_id, e.competition_id, e.season_id, e.period,
                   pb.start_seconds + {_seconds_from_timestamp("e.timestamp")} AS match_seconds,
                   e.type.name AS type, e.team.id AS team_id, e.tactics.formation AS formation,
                   list_transform(e.tactics.lineup, l -> {{'player_id': l.player.id,
                       'position_id': l.position.id, 'jersey_number': l.jersey_number}})
                       AS lineup
            FROM {self._from_events()}
            WHERE e.type.name IN ('Starting XI', 'Tactical Shift')
            ORDER BY e.match_id, e.index
            """,
        )

"""Write the Phase 1 coverage report (reports/coverage_report.md) from the downloaded data.

StatsBomb: matches, teams, players, events per league (from the interim Parquet tables).
Transfermarkt: snapshot, date ranges, and coverage of valuations and transfers for the players
who appeared in the 2015/16 scouting-pool leagues. Transfermarkt players are a proxy for "our
players" until entity resolution (Phase 2) links them to StatsBomb players.

Usage: uv run python scripts/coverage_report.py
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from datetime import date

import duckdb

from football_scouting.config import PROJECT_ROOT, load_config
from football_scouting.ingest.statsbomb_parquet import connect, interim_dir
from football_scouting.ingest.transfermarkt import load_manifest
from football_scouting.ingest.transfermarkt import raw_dir as tm_raw_dir

# Transfermarkt competition codes of the StatsBomb scouting-pool leagues (verified in
# competitions.csv: GB1 premier-league, ES1 laliga, IT1 serie-a, FR1 ligue-1).
TM_POOL = {"Premier League": "GB1", "La Liga": "ES1", "Serie A": "IT1", "Ligue 1": "FR1"}
TM_SEASON = 2015  # Transfermarkt `games.season` 2015 = 2015/16 (dates 2015-08 to 2016-05)
CUTOFF = "2016-06-30"  # end of the 2015/16 season: last date a feature may use


def table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    def fmt(v: object) -> str:
        if isinstance(v, float):
            return f"{v:,.1f}"
        if isinstance(v, int):
            return f"{v:,}"
        return "" if v is None else str(v)

    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(fmt(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def pct(n: int, d: int) -> str:
    return f"{n:,} ({100 * n / d:.1f}%)" if d else "-"


def statsbomb_section(con: duckdb.DuckDBPyConnection, cfg) -> list[str]:
    i = interim_dir(cfg)
    con.execute(f"CREATE VIEW sb_matches AS SELECT * FROM read_parquet('{i}/matches.parquet')")
    con.execute(f"CREATE VIEW sb_events AS SELECT * FROM read_parquet('{i}/events/*.parquet')")
    con.execute(
        f"CREATE VIEW sb_lineup AS SELECT competition_id, match_id, team_id, unnest(lineup) AS p "
        f"FROM read_parquet('{i}/lineups/*.parquet')"
    )
    names = {c.competition_id: c for c in cfg.statsbomb.competitions}
    rows = con.execute(
        """
        WITH m AS (
            SELECT competition.competition_id AS cid, count(*) AS matches,
                   count(DISTINCT home_team.home_team_id) AS home_teams,
                   sum(home_score + away_score) AS goals
            FROM sb_matches GROUP BY 1),
        l AS (
            SELECT competition_id AS cid, count(DISTINCT team_id) AS teams,
                   count(DISTINCT p.player_id) AS squad_players,
                   count(DISTINCT p.player_id) FILTER (WHERE len(p.positions) > 0) AS players
            FROM sb_lineup GROUP BY 1),
        e AS (
            SELECT competition_id AS cid, count(*) AS events,
                   count(*) FILTER (WHERE type.name = 'Shot') AS shots,
                   sum(shot.statsbomb_xg) AS xg
            FROM sb_events GROUP BY 1)
        SELECT cid, matches, teams, players, squad_players, events, events / matches,
               shots, xg, goals
        FROM m JOIN l USING (cid) JOIN e USING (cid)
        """
    ).fetchall()
    order = [c.competition_id for c in cfg.statsbomb.competitions]
    rows.sort(key=lambda r: order.index(r[0]))
    body = [[names[r[0]].name, "yes" if names[r[0]].scouting_pool else "no", *r[1:]] for r in rows]
    pool_ids = [c.competition_id for c in cfg.statsbomb.competitions if c.scouting_pool]
    pool_players = con.execute(
        f"SELECT count(DISTINCT p.player_id) FROM sb_lineup "
        f"WHERE len(p.positions) > 0 AND competition_id IN ({','.join(map(str, pool_ids))})"
    ).fetchone()[0]
    types = con.execute(
        "SELECT type.name, count(*) FROM sb_events GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    return [
        "## StatsBomb Open Data, 2015/16",
        "",
        f"Source: `statsbomb/open-data` at commit `{cfg.statsbomb.ref}`.",
        "",
        table(
            [
                "League",
                "Scouting pool",
                "Matches",
                "Teams",
                "Players (played)",
                "Players (in squads)",
                "Events",
                "Events / match",
                "Shots",
                "StatsBomb xG",
                "Goals (final scores)",
            ],
            body,
        ),
        "",
        "- *Players (played)*: distinct players with at least one position in the lineups "
        "(starters and used substitutes). *In squads* also counts unused substitutes, who are "
        "listed in the lineups with no positions.",
        f"- Distinct players who played in the scouting pool (4 leagues): **{pool_players:,}** "
        "(players who moved between pool leagues mid-season count once).",
        "- Bundesliga: only Bayer Leverkusen's 34 matches, so 18 teams appear but 17 of them "
        "in one or two matches each.",
        "- Ligue 1: 377 of 380 matches. Missing (home vs away): Bastia vs Gazélec Ajaccio, "
        "Saint-Étienne vs Paris Saint-Germain, Troyes vs Bordeaux.",
        "- No 360 freeze-frame files exist for these matches.",
        "",
        "### Event types (all 5 competitions)",
        "",
        table(["Event type", "Events"], types),
        "",
    ]


def transfermarkt_section(con: duckdb.DuckDBPyConnection, cfg) -> list[str]:
    d = tm_raw_dir(cfg)
    manifest = load_manifest(cfg)
    for t in cfg.transfermarkt.tables:
        con.execute(
            f"CREATE VIEW tm_{t} AS SELECT * FROM read_csv('{d}/{t}.csv.gz', sample_size = -1)"
        )
    snapshot = [
        [t, con.execute(f"SELECT count(*) FROM tm_{t}").fetchone()[0], m["last_modified"]]
        for t, m in manifest.items()
    ]
    ranges = con.execute(
        """
        SELECT (SELECT min(date) FROM tm_player_valuations),
               (SELECT max(date) FROM tm_player_valuations),
               (SELECT min(transfer_date) FROM tm_transfers),
               (SELECT max(transfer_date) FROM tm_transfers),
               (SELECT count(*) FROM tm_transfers
                WHERE transfer_date > (SELECT max(date) FROM tm_games)),
               (SELECT min(season) FROM tm_games),
               (SELECT max(season) FROM tm_games),
               (SELECT max(date) FROM tm_games)
        """
    ).fetchone()
    codes = ", ".join(f"'{c}'" for c in TM_POOL.values())
    games = con.execute(
        f"""
        SELECT g.competition_id, count(DISTINCT g.game_id), count(DISTINCT a.player_id)
        FROM tm_games g LEFT JOIN tm_appearances a USING (game_id)
        WHERE g.season = {TM_SEASON} AND g.competition_id IN ({codes})
        GROUP BY 1
        """
    ).fetchall()
    league = {v: k for k, v in TM_POOL.items()}
    games_rows = sorted(([league[c], g, p] for c, g, p in games), key=lambda r: r[0])

    con.execute(
        f"""
        CREATE TEMP TABLE pool AS
        SELECT DISTINCT a.player_id FROM tm_appearances a JOIN tm_games g USING (game_id)
        WHERE g.season = {TM_SEASON} AND g.competition_id IN ({codes})
        """
    )
    n_pool, in_players, with_dob = con.execute(
        "SELECT count(*), count(p.player_id), count(p.date_of_birth) "
        "FROM pool LEFT JOIN tm_players p USING (player_id)"
    ).fetchone()
    has_val, within_6m, within_12m = con.execute(
        f"""
        WITH v AS (SELECT player_id, max(date) AS last_date FROM tm_player_valuations
                   WHERE date <= DATE '{CUTOFF}' GROUP BY 1)
        SELECT count(v.player_id),
               count(*) FILTER (WHERE last_date > DATE '{CUTOFF}' - INTERVAL 6 MONTH),
               count(*) FILTER (WHERE last_date > DATE '{CUTOFF}' - INTERVAL 12 MONTH)
        FROM pool LEFT JOIN v USING (player_id)
        """
    ).fetchone()
    by_season = con.execute(
        """
        WITH v AS (
            SELECT player_id, date, market_value_in_eur,
                   CASE WHEN month(date) >= 7 THEN year(date) ELSE year(date) - 1 END AS s
            FROM tm_player_valuations JOIN pool USING (player_id))
        SELECT s, count(DISTINCT player_id), count(*)
        FROM v WHERE s BETWEEN 2015 AND 2025 GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    val_rows = [[f"{s}/{(s + 1) % 100:02d}", pct(n, n_pool), rows] for s, n, rows in by_season]
    transfers = con.execute(
        """
        SELECT CASE WHEN month(transfer_date) >= 7 THEN year(transfer_date)
                    ELSE year(transfer_date) - 1 END AS s,
               count(*), count(DISTINCT player_id), count(transfer_fee)
        FROM tm_transfers JOIN pool USING (player_id)
        WHERE transfer_date >= DATE '2015-07-01' AND transfer_date < DATE '2026-07-01'
        GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    transfer_rows = [[f"{s}/{(s + 1) % 100:02d}", n, p, f] for s, n, p, f in transfers]
    first_transfer = con.execute(
        "SELECT count(DISTINCT player_id) FROM tm_transfers JOIN pool USING (player_id)"
    ).fetchone()[0]
    # Transfers only exist for players still active recently: split by `players.last_season`.
    by_activity = con.execute(
        f"""
        WITH t AS (SELECT DISTINCT player_id FROM tm_transfers),
             v AS (SELECT DISTINCT player_id FROM tm_player_valuations
                   WHERE date <= DATE '{CUTOFF}')
        SELECT p.last_season >= 2020, count(*), count(t.player_id), count(v.player_id)
        FROM pool JOIN tm_players p USING (player_id)
        LEFT JOIN t USING (player_id) LEFT JOIN v USING (player_id)
        GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    activity_rows = [
        ["2020 or later" if recent else "before 2020", n, pct(t, n), pct(v, n)]
        for recent, n, t, v in by_activity
    ]
    all_players_without = con.execute(
        "SELECT count(*), count(t.player_id) FROM tm_players p "
        "LEFT JOIN (SELECT DISTINCT player_id FROM tm_transfers) t USING (player_id) "
        "WHERE p.last_season < 2020"
    ).fetchone()

    # Completeness check: a player whose main club (most minutes) changed between 2015/16 and
    # 2016/17 should have a transfer to the new club dated between the two seasons.
    moved, explained = con.execute(
        f"""
        WITH mins AS (
            SELECT a.player_id, g.season, a.player_club_id, sum(a.minutes_played) AS minutes
            FROM tm_appearances a JOIN tm_games g USING (game_id) JOIN pool USING (player_id)
            WHERE g.season IN ({TM_SEASON}, {TM_SEASON + 1})
            GROUP BY ALL),
        main AS (
            SELECT player_id, season, arg_max(player_club_id, minutes) AS club_id
            FROM mins GROUP BY ALL),
        moves AS (
            SELECT a.player_id, b.club_id AS new_club
            FROM main a JOIN main b ON a.player_id = b.player_id
                 AND a.season = {TM_SEASON} AND b.season = {TM_SEASON + 1}
            WHERE a.club_id <> b.club_id)
        SELECT count(*),
               count(*) FILTER (WHERE EXISTS (
                   SELECT 1 FROM tm_transfers t
                   WHERE t.player_id = moves.player_id AND t.to_club_id = moves.new_club
                     AND t.transfer_date BETWEEN DATE '2015-07-01' AND DATE '2017-06-30'))
        FROM moves
        """
    ).fetchone()

    vmin, vmax, tmin, tmax, t_future, smin, smax, gmax = ranges
    return [
        "## Transfermarkt (dcaribou/transfermarkt-datasets)",
        "",
        table(["Table", "Rows", "Published (Last-Modified)"], snapshot),
        "",
        f"- `player_valuations` dates: {vmin} to {vmax}.",
        f"- `transfers` dates: {tmin} to {tmax}; {t_future:,} rows are dated after the last "
        f"game in the snapshot ({gmax}), i.e. announced future moves.",
        f"- `games` seasons: {smin} to {smax}; `season` {TM_SEASON} = 2015/16.",
        "",
        "### 2015/16 games and players in the scouting-pool leagues",
        "",
        table(["League", "Games", "Players with an appearance"], games_rows),
        "",
        "Transfermarkt appearances only list players who played (3 of 1.9M rows have 0 minutes).",
        "",
        f"### Coverage for the {n_pool:,} players who played in the pool leagues in 2015/16",
        "",
        "These Transfermarkt players stand in for our StatsBomb players until entity "
        "resolution (Phase 2) links the two sources.",
        "",
        f"- In `players` table: {pct(in_players, n_pool)}; with date of birth: "
        f"{pct(with_dob, n_pool)}.",
        f"- With a market valuation on or before {CUTOFF} (feature side of the back-test): "
        f"{pct(has_val, n_pool)}; latest one within 6 months of the cutoff: "
        f"{pct(within_6m, n_pool)}; within 12 months: {pct(within_12m, n_pool)}.",
        f"- With at least one transfer record (any date): {pct(first_transfer, n_pool)}.",
        f"- Main club changed between 2015/16 and 2016/17: {moved:,} players; a transfer to the "
        f"new club dated 2015-07-01 to 2017-06-30 exists for {pct(explained, moved)}.",
        "",
        "**The `transfers` table has no records for players whose `last_season` is before "
        "2020, and is incomplete for the others.** Across the "
        f"whole snapshot, {all_players_without[0]:,} players have `last_season` before 2020 "
        f"and {all_players_without[1]:,} of them have a transfer record. For the pool players:",
        "",
        table(
            ["`players.last_season`", "Players", "With any transfer", "With a valuation ≤ cutoff"],
            activity_rows,
        ),
        "",
        "So `transfers` is survivorship-biased and cannot describe the careers of players who "
        "left the tracked leagues before 2020. Career moves can instead be derived from "
        "`appearances` (club per season) and the club recorded with each valuation, with "
        "`transfers` adding fees where present.",
        "",
        "Valuations of these players per season (July to June), the outcome side of the back-test:",
        "",
        table(["Season", "Players with a valuation", "Valuations"], val_rows),
        "",
        "Transfers of these players per season (July to June):",
        "",
        table(["Season", "Transfers", "Players", "With fee field"], transfer_rows),
        "",
    ]


def main() -> int:
    cfg = load_config()
    con = connect(cfg)
    lines = [
        "# Data coverage report",
        "",
        f"Generated by `scripts/coverage_report.py` on {date.today().isoformat()}. "
        "Counts only; no raw data is reproduced here.",
        "",
        *statsbomb_section(con, cfg),
        *transfermarkt_section(con, cfg),
    ]
    out = PROJECT_ROOT / "reports" / "coverage_report.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

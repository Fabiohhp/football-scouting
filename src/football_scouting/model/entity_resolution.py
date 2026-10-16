"""Link StatsBomb and Transfermarkt, which share no identifiers.

1. Matches and teams. Each StatsBomb match is paired with the Transfermarkt game of the same
   league-season, date and final score; every StatsBomb team then takes the Transfermarkt club
   it is paired with most often. Matches are finally linked by date + both clubs.
2. Players. Within each StatsBomb team-season, every player who played is compared with every
   Transfermarkt player who appeared for the linked club in the linked games, on:
   - games in common (Jaccard index of the two sets of linked games played),
   - name similarity (accents and punctuation removed; nickname and display name included),
   and pairs are assigned one-to-one, best score first. Each link gets a confidence tier from
   the strength of both signals and the margin over the runner-up.
   Manual decisions live in config/player_match_overrides.csv and take precedence.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import duckdb
import pandas as pd
from anyascii import anyascii
from rapidfuzz import fuzz

from football_scouting.config import PROJECT_ROOT, Config

OVERRIDES_PATH = PROJECT_ROOT / "config" / "player_match_overrides.csv"

# Weights of the combined score and thresholds of the confidence tiers.
W_GAMES, W_NAME = 0.6, 0.4
HIGH = {"games": 0.8, "name": 0.75, "margin": 0.1}
MEDIUM = {"games": 0.6, "name": 0.5, "margin": 0.05}


def links_dir(cfg: Config) -> Path:
    return cfg.paths.processed / "links"


def normalize_name(name: str | None) -> str:
    """'N'Golo Kanté' -> 'n golo kante'; transliterates (ø, ł, ß, ...) and drops punctuation."""
    if not name:
        return ""
    text = anyascii(name).lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def name_similarity(sb_names: list[str | None], tm_names: list[str | None]) -> float:
    """Best token-set similarity (0-1) over all StatsBomb x Transfermarkt name variants."""
    a = [n for n in map(normalize_name, sb_names) if n]
    b = [n for n in map(normalize_name, tm_names) if n]
    if not a or not b:
        return 0.0
    return max(fuzz.token_set_ratio(x, y) for x in a for y in b) / 100.0


def confidence_tier(games: float, name: float, margin: float) -> str:
    if games >= HIGH["games"] and name >= HIGH["name"] and margin >= HIGH["margin"]:
        return "high"
    if games >= MEDIUM["games"] and name >= MEDIUM["name"] and margin >= MEDIUM["margin"]:
        return "medium"
    return "low"


# -- matches and teams ---------------------------------------------------------------------


def pick_clubs(votes: pd.DataFrame) -> pd.DataFrame:
    """Choose one Transfermarkt club per StatsBomb team-season from the match votes.

    A club gets a vote for every match whose date and score agree. Teams with few matches (the
    Bundesliga sample: 2 each) can tie with a club that coincides by chance, so ties go to the
    most similar club name. Raises unless every match of the team supports the chosen club and
    no club is chosen twice in a league-season.
    """
    v = votes.copy()
    v["name_similarity"] = [
        name_similarity([a], [b]) for a, b in zip(v["team_name"], v["club_name"], strict=True)
    ]
    keys = ["competition_id", "season_id", "team_id"]
    v = v.sort_values(
        [*keys, "votes", "name_similarity", "club_id"],
        ascending=[True, True, True, False, False, True],
    )
    best = v.groupby(keys, as_index=False).first()
    second = v.groupby(keys).nth(1).set_index(keys)
    best["runner_up_votes"] = best.set_index(keys).index.map(second["votes"]).fillna(0).astype(int)
    unsupported = best[best["votes"] < best["matches"]]
    if len(unsupported):
        raise ValueError(f"Teams whose matches do not all support one club:\n{unsupported}")
    if best.duplicated(["competition_id", "season_id", "club_id"]).any():
        raise ValueError("A Transfermarkt club was matched to two StatsBomb teams")
    return best.drop(columns="name_similarity").reset_index(drop=True)


def link_matches(con: duckdb.DuckDBPyConnection, cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (team_map, match_map)."""
    sb = cfg.paths.processed / "statsbomb"
    tm = cfg.paths.processed / "transfermarkt"
    leagues = ", ".join(
        f"({c.competition_id}, {c.season_id}, '{c.transfermarkt_competition_id}', "
        f"{c.transfermarkt_season})"
        for c in cfg.statsbomb.competitions
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE pairs AS
        SELECT m.match_id, m.competition_id, m.season_id, g.game_id,
               m.home_team_id, m.away_team_id, g.home_club_id, g.away_club_id,
               g.home_club_name, g.away_club_name,
               abs(date_diff('day', m.match_date, g.date)) AS day_diff
        FROM read_parquet('{sb}/matches.parquet') m
        JOIN (VALUES {leagues}) l(competition_id, season_id, tm_competition_id, tm_season)
             USING (competition_id, season_id)
        JOIN read_parquet('{tm}/games.parquet') g
             ON g.competition_id = l.tm_competition_id AND g.season = l.tm_season
            AND abs(date_diff('day', m.match_date, g.date)) <= 1
            AND g.home_club_goals = m.home_score AND g.away_club_goals = m.away_score
        """
    )
    votes = con.execute(
        f"""
        WITH v AS (
            SELECT competition_id, season_id, home_team_id AS team_id, home_club_id AS club_id,
                   home_club_name AS club_name
            FROM pairs
            UNION ALL
            SELECT competition_id, season_id, away_team_id, away_club_id, away_club_name
            FROM pairs)
        SELECT v.competition_id, v.season_id, v.team_id, t.team_name, t.matches, v.club_id,
               any_value(v.club_name) AS club_name, count(*) AS votes
        FROM v JOIN read_parquet('{sb}/teams.parquet') t
             USING (team_id, competition_id, season_id)
        GROUP BY ALL
        """
    ).df()
    team_map = pick_clubs(votes)
    con.register("team_map_df", team_map)
    match_map = con.execute(
        f"""
        SELECT m.match_id, m.competition_id, m.season_id, g.game_id,
               abs(date_diff('day', m.match_date, g.date)) AS day_diff
        FROM read_parquet('{sb}/matches.parquet') m
        JOIN team_map_df h ON h.team_id = m.home_team_id
             AND h.competition_id = m.competition_id AND h.season_id = m.season_id
        JOIN team_map_df a ON a.team_id = m.away_team_id
             AND a.competition_id = m.competition_id AND a.season_id = m.season_id
        JOIN read_parquet('{tm}/games.parquet') g
             ON g.home_club_id = h.club_id AND g.away_club_id = a.club_id
            AND abs(date_diff('day', m.match_date, g.date)) <= 1
        ORDER BY m.match_id
        """
    ).df()
    return team_map, match_map


# -- players -------------------------------------------------------------------------------


def player_evidence(
    con: duckdb.DuckDBPyConnection, cfg: Config, team_map: pd.DataFrame, match_map: pd.DataFrame
) -> pd.DataFrame:
    """One row per (StatsBomb player-team-season, Transfermarkt candidate) with the evidence."""
    sb = cfg.paths.processed / "statsbomb"
    tm = cfg.paths.processed / "transfermarkt"
    con.register("team_map_df", team_map)
    con.register("match_map_df", match_map)
    return con.execute(
        f"""
        WITH sb_games AS (
            SELECT pm.player_id AS sb_player_id, pm.team_id, pm.competition_id, pm.season_id,
                   mm.game_id, pm.minutes_played AS sb_minutes
            FROM read_parquet('{sb}/player_matches.parquet') pm
            JOIN match_map_df mm USING (match_id)
            WHERE pm.played),
        sb_sets AS (
            SELECT sb_player_id, team_id, competition_id, season_id,
                   list(game_id) AS sb_games, sum(sb_minutes) AS sb_minutes
            FROM sb_games GROUP BY ALL),
        tm_games AS (
            SELECT a.player_id AS tm_player_id, tmap.team_id, tmap.competition_id,
                   tmap.season_id, a.game_id, a.minutes_played AS tm_minutes
            FROM read_parquet('{tm}/appearances.parquet') a
            JOIN match_map_df mm USING (game_id)
            JOIN team_map_df tmap ON tmap.club_id = a.player_club_id
                 AND tmap.competition_id = mm.competition_id
                 AND tmap.season_id = mm.season_id),
        tm_sets AS (
            SELECT tm_player_id, team_id, competition_id, season_id,
                   list(game_id) AS tm_games, sum(tm_minutes) AS tm_minutes
            FROM tm_games GROUP BY ALL)
        SELECT s.sb_player_id, s.team_id, s.competition_id, s.season_id, t.tm_player_id,
               len(s.sb_games) AS sb_n_games, len(t.tm_games) AS tm_n_games,
               len(list_intersect(s.sb_games, t.tm_games)) AS both_games,
               s.sb_minutes, t.tm_minutes,
               p.player_name AS sb_name, p.player_nickname AS sb_nickname,
               p.country AS sb_country,
               tp.name AS tm_name, tp.first_name AS tm_first_name, tp.last_name AS tm_last_name,
               tp.country_of_citizenship AS tm_country, tp.date_of_birth AS tm_date_of_birth
        FROM sb_sets s
        JOIN tm_sets t USING (team_id, competition_id, season_id)
        JOIN read_parquet('{sb}/players.parquet') p ON p.player_id = s.sb_player_id
        JOIN read_parquet('{tm}/players.parquet') tp ON tp.player_id = t.tm_player_id
        """
    ).df()


def score_candidates(evidence: pd.DataFrame) -> pd.DataFrame:
    ev = evidence.copy()
    union = ev["sb_n_games"] + ev["tm_n_games"] - ev["both_games"]
    ev["games_jaccard"] = ev["both_games"] / union
    ev["name_similarity"] = [
        name_similarity(
            [r.sb_name, r.sb_nickname],
            [r.tm_name, f"{r.tm_first_name or ''} {r.tm_last_name or ''}", r.tm_last_name],
        )
        for r in ev.itertuples()
    ]
    ev["score"] = W_GAMES * ev["games_jaccard"] + W_NAME * ev["name_similarity"]
    return ev


def assign(scored: pd.DataFrame) -> pd.DataFrame:
    """One-to-one assignment within each team-season, best score first, with tiers."""
    keys = ["team_id", "competition_id", "season_id"]
    rows = []
    for _, group in scored.groupby(keys):
        group = group.sort_values(
            ["score", "sb_player_id", "tm_player_id"], ascending=[False, True, True]
        )
        used_sb, used_tm = set(), set()
        for r in group.itertuples():
            if r.sb_player_id in used_sb or r.tm_player_id in used_tm:
                continue
            others = group[
                (group["sb_player_id"] == r.sb_player_id)
                & (group["tm_player_id"] != r.tm_player_id)
            ]
            runner_up = others["score"].max() if len(others) else 0.0
            used_sb.add(r.sb_player_id)
            used_tm.add(r.tm_player_id)
            rows.append({**r._asdict(), "runner_up_score": runner_up})
    out = pd.DataFrame(rows).drop(columns="Index")
    out["margin"] = out["score"] - out["runner_up_score"]
    out["confidence"] = [
        confidence_tier(g, n, m)
        for g, n, m in zip(out["games_jaccard"], out["name_similarity"], out["margin"], strict=True)
    ]
    return out


def load_overrides(path: Path = OVERRIDES_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["sb_player_id", "tm_player_id", "reason"])
    with open(path, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if not r["sb_player_id"].startswith("#")]
    df = pd.DataFrame(rows, columns=["sb_player_id", "tm_player_id", "reason"])
    df["sb_player_id"] = df["sb_player_id"].astype("int64")
    df["tm_player_id"] = pd.to_numeric(df["tm_player_id"], errors="coerce").astype("Int64")
    return df


def resolve_players(con: duckdb.DuckDBPyConnection, cfg: Config) -> dict[str, pd.DataFrame]:
    """Run the whole linkage; return the tables to write (see module docstring)."""
    team_map, match_map = link_matches(con, cfg)
    links = assign(score_candidates(player_evidence(con, cfg, team_map, match_map)))
    links["method"] = "auto"
    links["reason"] = None

    overrides = load_overrides()
    if len(overrides):
        sb = cfg.paths.processed / "statsbomb"
        tm = cfg.paths.processed / "transfermarkt"
        con.register("overrides_df", overrides)
        manual = con.execute(
            f"""
            SELECT o.sb_player_id, ps.team_id, ps.competition_id, ps.season_id,
                   o.tm_player_id, o.reason, p.player_name AS sb_name,
                   p.player_nickname AS sb_nickname, tp.name AS tm_name
            FROM overrides_df o
            JOIN read_parquet('{sb}/player_seasons.parquet') ps
                 ON ps.player_id = o.sb_player_id AND ps.matches_played > 0
            JOIN read_parquet('{sb}/players.parquet') p ON p.player_id = o.sb_player_id
            LEFT JOIN read_parquet('{tm}/players.parquet') tp ON tp.player_id = o.tm_player_id
            """
        ).df()
        # Keep the automatic evidence where it exists, then apply the manual decision.
        auto = links[links["sb_player_id"].isin(overrides["sb_player_id"])]
        keys = ["sb_player_id", "team_id", "competition_id", "season_id"]
        manual = manual.merge(
            auto.drop(
                columns=["tm_player_id", "reason", "method", "sb_name", "sb_nickname", "tm_name"]
            ),
            on=keys,
            how="left",
        )
        manual["method"] = "manual"
        manual["confidence"] = "manual"
        links = pd.concat(
            [links[~links["sb_player_id"].isin(overrides["sb_player_id"])], manual],
            ignore_index=True,
        )
        links = links[links["tm_player_id"].notna()]

    conflicts = links.groupby("sb_player_id")["tm_player_id"].nunique()
    if (conflicts > 1).any():
        raise ValueError(
            f"StatsBomb players linked to several Transfermarkt players: "
            f"{conflicts[conflicts > 1].index.tolist()}"
        )
    reverse = links.groupby("tm_player_id")["sb_player_id"].nunique()
    if (reverse > 1).any():
        raise ValueError(
            f"Transfermarkt players linked to several StatsBomb players: "
            f"{reverse[reverse > 1].index.tolist()}"
        )

    tier_order = {"low": 0, "medium": 1, "high": 2, "manual": 3}
    links["tier_rank"] = links["confidence"].map(tier_order)
    player_map = (
        links.sort_values("tier_rank")
        .groupby("sb_player_id", as_index=False)
        .agg(
            tm_player_id=("tm_player_id", "first"),
            confidence=("confidence", "first"),
            method=("method", "first"),
            reason=("reason", "first"),
            team_seasons=("team_id", "size"),
            games_jaccard=("games_jaccard", "min"),
            name_similarity=("name_similarity", "min"),
            sb_name=("sb_name", "first"),
            tm_name=("tm_name", "first"),
        )
    )
    player_map["tm_player_id"] = player_map["tm_player_id"].astype("int64")
    links = links.drop(columns=["tier_rank"])
    return {
        "team_map": team_map,
        "match_map": match_map,
        "player_team_links": links,
        "player_map": player_map,
    }

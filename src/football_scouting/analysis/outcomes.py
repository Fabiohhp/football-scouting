"""What happened next: the outcomes the back-test scores, read after the market view.

Everything here reads Transfermarkt after `backtest.market_view` and must never feed a model of
the market view (`analysis.market`).

Value growth (`value_growth`): each player's latest valuation on or before each horizon against
their value on `backtest.outcome_base`, on the log scale. A player whose latest valuation is more
than `still_valued_days` old at a horizon is no longer valued and has no growth. Raw growth is
mostly age, so it is scored against players of the same age band (`age_band`, `growth_score`):
a percentile, with the players no longer valued tied at the bottom. `excess_growth` is the
check: growth less what an age curve predicts.

Careers (`career`): at each horizon, what the player played in the season that ended before it,
from Transfermarkt's appearances: league minutes in the covered leagues, in the big five and in
the Champions League, and the league they played most league minutes in (their `level`).
Seasons run July to June and are named by their first year, as in `tm_games.season`. The club
named on a valuation is not used for the level: valuations name clubs by their short name ("AS
Roma"), games by their full name ("Associazione Sportiva Roma"), and a valuation can predate a
move. `club_ids` links the names through the players (a name goes to the club its players played
league matches for in the same season) and `club_leagues` gives each club's league, to check
where the players without league minutes were. `season_clubs` gives the club a player played
most for in each season, to follow moves between clubs.

Signings (`first_half_clubs`, `league_share`, `coaches`): the club a player was at in the first
half of a season, the share of a club's league minutes a player played in a season, and whether a
club changed coach between two seasons.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

import duckdb
import numpy as np
import pandas as pd

from football_scouting.analysis.market import value_model
from football_scouting.analysis.values import pool_valuations, value_at
from football_scouting.config import BacktestConfig, Config

LEVELS = ("big five", "other covered league", "no league minutes", "no longer valued")


def value_growth(valuations: pd.DataFrame, bt: BacktestConfig) -> pd.DataFrame:
    """One row per player valued on `bt.outcome_base` and horizon.

    Columns: `player_id`, `horizon`, `base` (the value on `outcome_base`, euros), the latest
    valuation on or before the horizon (`value`, `date`, `club`), `still_valued` (that valuation
    at most `still_valued_days` old) and `growth`, log(value / base), missing when no longer
    valued.
    """
    base = value_at(valuations, bt.outcome_base).value
    frames = []
    for horizon in bt.horizons:
        at = value_at(valuations, horizon).reindex(base.index)
        frame = at[["value", "date", "club"]].assign(
            horizon=pd.Timestamp(horizon),
            base=base,
            still_valued=at.age_days <= bt.still_valued_days,
        )
        frame["growth"] = np.log(frame.value / frame.base).where(frame.still_valued)
        frames.append(frame)
    columns = ["horizon", "base", "value", "date", "club", "still_valued", "growth"]
    return pd.concat(frames).reset_index()[["player_id", *columns]]


def age_band(age: pd.Series, starts: Sequence[int]) -> pd.Series:
    """Each age's band: under the first start, from each start to the next ("21-22"), and the
    last open ("33 and over")."""
    labels = [
        f"under {starts[0]}",
        *(f"{a}-{b - 1}" for a, b in pairwise(starts)),
        f"{starts[-1]} and over",
    ]
    return pd.cut(age, [-np.inf, *starts, np.inf], right=False, labels=labels)


def growth_score(growth: pd.Series, groups: Sequence[pd.Series] | pd.Series) -> pd.Series:
    """The percentile of `growth` within `groups`: its rank over the group's size, 0 to 100, ties
    sharing the average rank; a missing growth (no longer valued) below every other."""
    return growth.fillna(-np.inf).groupby(groups, observed=True).rank(pct=True) * 100


def excess_growth(growth: pd.Series, age: pd.Series) -> pd.Series:
    """`growth` less the prediction of an age curve (`market.value_model` on age alone) fitted on
    the players still valued; missing when no longer valued."""
    valued = growth.notna()
    model = value_model(["age"]).fit(age[valued].to_frame("age"), growth[valued])
    return growth - model.predict(age.to_frame("age"))


def club_ids(con: duckdb.DuckDBPyConnection, min_players: int = 10) -> pd.Series:
    """The Transfermarkt club id (values) of each club name on valuations (index).

    A player valued under a name in a season votes for each club they played league matches for
    in that season. A name goes to the club with at least half of its voters, when that club has
    `min_players` or more of them; names of clubs outside the covered leagues, whose players vote
    only once they have moved, stay out.
    """
    votes = con.execute("""
        WITH named AS (
            SELECT DISTINCT player_id, current_club_name AS name,
                   year(date) - CASE WHEN month(date) < 7 THEN 1 ELSE 0 END AS season
            FROM tm_player_valuations
            WHERE current_club_name IS NOT NULL),
        played AS (
            SELECT DISTINCT a.player_id, g.season, a.player_club_id AS club_id
            FROM tm_appearances a JOIN tm_games g USING (game_id)
            JOIN tm_competitions c ON c.competition_id = g.competition_id
            WHERE c.type = 'domestic_league'),
        voted AS (SELECT * FROM named JOIN played USING (player_id, season))
        SELECT name, club_id, count(DISTINCT player_id) AS players,
               any_value(voters) AS voters
        FROM voted
        JOIN (SELECT name, count(DISTINCT player_id) AS voters FROM voted GROUP BY name)
            USING (name)
        GROUP BY name, club_id
    """).df()
    best = votes.sort_values(["players", "club_id"], ascending=[False, True]).drop_duplicates(
        "name"
    )
    kept = best[(best.players >= min_players) & (best.players >= best.voters / 2)]
    return kept.set_index("name").club_id.sort_index()


def club_leagues(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """The domestic league (`league`, a competition id) each club (`club_id`) played in each
    `season`, for the leagues Transfermarkt's games cover."""
    return con.execute("""
        SELECT DISTINCT club_id, season, league FROM (
            SELECT home_club_id AS club_id, season, competition_id AS league FROM tm_games
            UNION ALL
            SELECT away_club_id, season, competition_id FROM tm_games)
        JOIN tm_competitions c ON c.competition_id = league
        WHERE c.type = 'domestic_league'
        ORDER BY club_id, season
    """).df()


def season_minutes(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Minutes of each linked player (`player_id`, StatsBomb) by `season` and `competition_id`,
    from Transfermarkt's appearances, with the competition's `type`."""
    return con.execute("""
        SELECT m.sb_player_id AS player_id, g.season, a.competition_id, c.type,
               sum(a.minutes_played) AS minutes
        FROM tm_appearances a JOIN tm_games g USING (game_id)
        JOIN tm_competitions c ON c.competition_id = a.competition_id
        JOIN player_map m ON m.tm_player_id = a.player_id
        GROUP BY ALL
        ORDER BY ALL
    """).df()


def season_clubs(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """The club (`club_id`) each linked player (`player_id`, StatsBomb) played the most minutes
    for in each `season`, over every competition Transfermarkt's appearances cover, with those
    `minutes` (a tie goes to the lowest club id)."""
    return con.execute("""
        SELECT player_id, season, club_id, minutes FROM (
            SELECT m.sb_player_id AS player_id, g.season, a.player_club_id AS club_id,
                   sum(a.minutes_played) AS minutes
            FROM tm_appearances a JOIN tm_games g USING (game_id)
            JOIN player_map m ON m.tm_player_id = a.player_id
            GROUP BY ALL)
        QUALIFY row_number() OVER (
            PARTITION BY player_id, season ORDER BY minutes DESC, club_id) = 1
        ORDER BY player_id, season
    """).df()


def first_half_clubs(con: duckdb.DuckDBPyConnection, season: int) -> pd.DataFrame:
    """The club (`club_id`) each linked player (`player_id`, StatsBomb) was at in the first half
    of `season` (July to December), with its `source`.

    "appearances": the club they played the most minutes for in that half, over every competition
    Transfermarkt's appearances cover (a tie goes to the lowest club id). "transfer": for a player
    without appearances in it, the club their last transfer from May to the end of August went
    to. Transfers are on record for few players (`docs/DEVELOPMENT.md`): a player who joined a
    club and did not play for it, with no record, is missed.
    """
    played = con.execute(f"""
        SELECT player_id, club_id FROM (
            SELECT m.sb_player_id AS player_id, a.player_club_id AS club_id,
                   sum(a.minutes_played) AS minutes
            FROM tm_appearances a JOIN player_map m ON m.tm_player_id = a.player_id
            WHERE a.date BETWEEN DATE '{season}-07-01' AND DATE '{season}-12-31'
            GROUP BY ALL)
        QUALIFY row_number() OVER (PARTITION BY player_id ORDER BY minutes DESC, club_id) = 1
    """).df()
    moved = con.execute(f"""
        SELECT m.sb_player_id AS player_id, t.to_club_id AS club_id
        FROM tm_transfers t JOIN player_map m ON m.tm_player_id = t.player_id
        WHERE t.transfer_date BETWEEN DATE '{season}-05-01' AND DATE '{season}-08-31'
        QUALIFY row_number() OVER (
            PARTITION BY m.sb_player_id ORDER BY t.transfer_date DESC, t.to_club_id) = 1
    """).df()
    moved = moved[~moved.player_id.isin(played.player_id)]
    out = pd.concat(
        [played.assign(source="appearances"), moved.assign(source="transfer")], ignore_index=True
    )
    return out.sort_values("player_id", ignore_index=True)


def league_share(con: duckdb.DuckDBPyConnection, season: int, pairs: pd.DataFrame) -> pd.Series:
    """For each row of `pairs` (`player_id`, StatsBomb, and `club_id`), the share of the club's
    league minutes in `season` the player played for it: their league minutes over the club's
    league matches times 90; 0 if they played none, missing for a club outside the leagues
    Transfermarkt's games cover."""
    played = con.execute(f"""
        SELECT m.sb_player_id AS player_id, a.player_club_id AS club_id,
               sum(a.minutes_played) AS minutes
        FROM tm_appearances a JOIN tm_games g USING (game_id)
        JOIN tm_competitions c ON c.competition_id = g.competition_id
        JOIN player_map m ON m.tm_player_id = a.player_id
        WHERE g.season = {season} AND c.type = 'domestic_league'
        GROUP BY ALL
    """).df()
    matches = con.execute(f"""
        SELECT club_id, count(*) AS matches FROM (
            SELECT home_club_id AS club_id, competition_id FROM tm_games WHERE season = {season}
            UNION ALL
            SELECT away_club_id, competition_id FROM tm_games WHERE season = {season})
        JOIN tm_competitions USING (competition_id)
        WHERE type = 'domestic_league'
        GROUP BY club_id
    """).df()
    out = pairs[["player_id", "club_id"]].merge(played, how="left").merge(matches, how="left")
    share = out.minutes.fillna(0) / (90 * out.matches)
    return pd.Series(share.to_numpy(), index=pairs.index, name="share")


def coaches(con: duckdb.DuckDBPyConnection, season: int) -> pd.DataFrame:
    """Each club's coach (`club_id` index) in its last league match of the season before `season`
    (`before`) and in its first of `season` (`after`), as named on Transfermarkt's games."""
    query = f"""
        WITH sides AS (
            SELECT season, date, home_club_id AS club_id, home_club_manager_name AS coach,
                   competition_id
            FROM tm_games
            UNION ALL
            SELECT season, date, away_club_id, away_club_manager_name, competition_id
            FROM tm_games)
        SELECT club_id,
               arg_max(coach, date) FILTER (WHERE season = {season - 1}) AS before,
               arg_min(coach, date) FILTER (WHERE season = {season}) AS after
        FROM sides JOIN tm_competitions USING (competition_id)
        WHERE type = 'domestic_league' AND season IN ({season - 1}, {season})
        GROUP BY club_id
        ORDER BY club_id
    """
    return con.execute(query).df().set_index("club_id")


def career(growth: pd.DataFrame, minutes: pd.DataFrame, bt: BacktestConfig) -> pd.DataFrame:
    """`growth` (from `value_growth`) with what each player played in the season that ended
    before the horizon (`minutes` from `season_minutes`).

    Adds `league_minutes` (any covered league), `big_five_minutes`, `champions_league_minutes`,
    `league` (the league of most league minutes; missing without any) and `level` (`LEVELS`):
    no longer valued, or the league's: the big five, another covered league, or no league
    minutes in the covered leagues.
    """
    played = minutes.assign(
        league_minutes=minutes.minutes.where(minutes.type == "domestic_league", 0),
        big_five_minutes=minutes.minutes.where(minutes.competition_id.isin(bt.big_five), 0),
        champions_league_minutes=minutes.minutes.where(
            minutes.competition_id == bt.champions_league, 0
        ),
    )
    columns = ["league_minutes", "big_five_minutes", "champions_league_minutes"]
    totals = played.groupby(["player_id", "season"])[columns].sum()
    leagues = played[played.type == "domestic_league"].sort_values(
        ["minutes", "competition_id"], ascending=[False, True]
    )
    totals["league"] = (
        leagues.drop_duplicates(["player_id", "season"])
        .set_index(["player_id", "season"])
        .competition_id
    )
    totals = totals.reset_index()
    totals["season"] += 1  # matched to the horizon that follows the season
    out = growth.assign(season=growth.horizon.dt.year).merge(
        totals, on=["player_id", "season"], how="left"
    )
    out[columns] = out[columns].fillna(0)
    out["level"] = np.select(
        [~out.still_valued, out.league.isin(bt.big_five), out.league.notna()],
        [LEVELS[3], LEVELS[0], LEVELS[1]],
        default=LEVELS[2],
    )
    return out.drop(columns="season")


def player_outcomes(con: duckdb.DuckDBPyConnection, cfg: Config) -> pd.DataFrame:
    """Every outcome of every profiled player (`profile_players`) at every horizon.

    `value_growth` and `career`, with the player's `comparison_group`, `age` (on 30 June 2016),
    `band` (`age_band` of `backtest.age_bands`), `score` (`growth_score` within horizon and band)
    and `excess` (`excess_growth` within horizon).
    """
    players = con.sql("SELECT player_id, comparison_group, age FROM profile_players").df()
    valuations = pool_valuations(con)
    valuations = valuations[valuations.player_id.isin(players.player_id)]
    bt = cfg.backtest
    out = value_growth(valuations, bt).merge(players)
    out["band"] = age_band(out.age, bt.age_bands)
    out["score"] = growth_score(out.growth, [out.horizon, out.band])
    out["excess"] = pd.concat(
        [excess_growth(d.growth, d.age) for _, d in out.groupby("horizon")]
    ).reindex(out.index)
    return career(out, season_minutes(con), bt)

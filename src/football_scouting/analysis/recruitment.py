"""The recruitment case study (notebook 08): a club replacing a player it sold, decided on the
back-test's market view with the tools the earlier notebooks built and tested.

The scenario is `case_study` in the config; its rules were set before any list was drawn up
(`docs/DECISIONS.md`, 2026-11-01):

- the budget (`fee_ratios`, `ceiling`): the player's fee (`sale`) over the median ratio of fee to
  market value the clubs of the club's league paid for profiled players the summer before, the
  last one known on the market view (Transfermarkt dates summer transfers from 1 July);
- the candidates (`candidates`): the players of the group in the similarity search's lists
  (`similarity.similar`), filtered in turn: not the player's teammates, playing on the player's
  side, younger than `younger_than`, valued within the ceiling, their main team outside the
  strongest fifth of teams by goal difference per match (`team_fifths`), which do not sell at
  their market value (notebook 04, section 1.6);
- the long list (`long_list`): the candidates by their distance from the player, list by list,
  and the nearer half of each list;
- the shortlist (`shortlist`): the largest gaps within team (`market.gap`) of the nearer half;
- the recommendation (`recommend`): the shortlisted player who fits the club's style best
  (`club_fit`, read as `teams.fit` reads it in notebook 07, section 4).

`case_study` chains the steps for `make reports`. Nothing after the market view enters them; the
players the club signed (`signings`) are read afterwards, for comparison only.
"""

from __future__ import annotations

from collections.abc import Collection, Hashable
from dataclasses import dataclass
from datetime import date

import duckdb
import pandas as pd

from football_scouting.analysis.market import gap, market_players, profile_matrix, team_strength
from football_scouting.analysis.outcomes import club_leagues, first_half_clubs
from football_scouting.analysis.profiles import POSSESSION, recording_context, rescale
from football_scouting.analysis.roles import Axes, place, style_matches
from football_scouting.analysis.similarity import (
    fit_block,
    main_positions,
    search_players,
    search_points,
    search_values,
    similar,
    style_ends,
)
from football_scouting.analysis.style import SUMMED
from football_scouting.analysis.teams import (
    Seasons,
    fit,
    fit_distances,
    numbers,
    scores_without,
    style_axes,
    style_slopes,
    team_seasons,
    whole_season_team,
)
from football_scouting.config import Config

SUMMER = ("05-01", "08-31")  # the window a summer's transfers are read from
FIFTHS = 5  # teams split by strength; the strongest fifth does not sell at market value
STYLE_SUMS = [*SUMMED, "minutes", *POSSESSION]  # the sums a style is read from (`roles.place`)


def sale(con: duckdb.DuckDBPyConnection, player_id: int, year: int) -> pd.Series:
    """The transfer of a player (StatsBomb id) from 1 May to 31 August `year`: `transfer_date`,
    `transfer_fee` and `to_club_name`. Fails unless there is exactly one."""
    start, end = SUMMER
    moves = con.execute(f"""
        SELECT t.transfer_date, t.transfer_fee, t.to_club_name
        FROM tm_transfers t JOIN player_map m ON m.tm_player_id = t.player_id
        WHERE m.sb_player_id = {int(player_id)}
          AND t.transfer_date BETWEEN DATE '{year}-{start}' AND DATE '{year}-{end}'
    """).df()
    if len(moves) != 1:
        raise ValueError(f"player {player_id}: {len(moves)} transfers in the summer of {year}")
    return moves.iloc[0]


def league_table(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """One row per pool team (index `team_id`) from the pool's results: `competition_id`,
    `played`, `points`, `goal_difference`, `scored` and `place` in its league (by points, then
    goal difference, then goals scored)."""
    results = con.sql("""
        WITH sides AS (
            SELECT competition_id, home_team_id AS team_id, home_score AS scored,
                   away_score AS conceded
            FROM matches WHERE scouting_pool
            UNION ALL
            SELECT competition_id, away_team_id, away_score, home_score
            FROM matches WHERE scouting_pool)
        SELECT competition_id, team_id, count(*) AS played,
               sum(CASE WHEN scored > conceded THEN 3 WHEN scored = conceded THEN 1 ELSE 0 END)
                   AS points,
               sum(scored - conceded) AS goal_difference, sum(scored) AS scored
        FROM sides GROUP BY ALL
    """).df()
    results = results.sort_values(
        ["competition_id", "points", "goal_difference", "scored"],
        ascending=[True, False, False, False],
    )
    results["place"] = results.groupby("competition_id").cumcount() + 1
    return results.set_index("team_id")


def fee_ratios(
    con: duckdb.DuckDBPyConnection, cfg: Config, profiled: Collection, year: int
) -> pd.DataFrame:
    """Transfers with a fee on record from 1 May to 31 August `year` to a club that played in one
    of the pool's leagues in the season starting then, against the player's latest market value on
    or before 30 June `year`.

    One row per transfer: `player_id` (Transfermarkt), `sb_player_id`, `transfer_date`,
    `transfer_fee`, `to_club_id`, `value`, `league` (the buying club's, a Transfermarkt competition
    id), `ratio` (the fee over the value) and `profiled` (`sb_player_id` in `profiled`).
    """
    start, end = SUMMER
    paid = con.execute(f"""
        WITH valued AS (
            SELECT player_id, market_value_in_eur AS value FROM tm_player_valuations
            WHERE date <= DATE '{year}-06-30'
            QUALIFY row_number() OVER (PARTITION BY player_id ORDER BY date DESC) = 1)
        SELECT t.player_id, m.sb_player_id, t.transfer_date, t.transfer_fee, t.to_club_id,
               v.value
        FROM tm_transfers t JOIN valued v USING (player_id)
        LEFT JOIN player_map m ON m.tm_player_id = t.player_id
        WHERE t.transfer_date BETWEEN DATE '{year}-{start}' AND DATE '{year}-{end}'
          AND t.transfer_fee > 0 AND v.value > 0
    """).df()
    pool = [c.transfermarkt_competition_id for c in cfg.statsbomb.competitions if c.scouting_pool]
    leagues = club_leagues(con)
    buyers = leagues[(leagues.season == year) & leagues.league.isin(pool)]
    paid = paid.merge(buyers.drop(columns="season").rename(columns={"club_id": "to_club_id"}))
    return paid.assign(
        ratio=paid.transfer_fee / paid.value, profiled=paid.sb_player_id.isin(profiled)
    )


def ceiling(fee: float, ratios: pd.DataFrame, league: str) -> float:
    """The highest market value `fee` buys: the fee over the median ratio of the profiled players'
    transfers to clubs of `league` among `ratios` (`fee_ratios`)."""
    return fee / ratios.ratio[ratios.profiled & (ratios.league == league)].median()


def team_fifths(strength: pd.Series) -> pd.Series:
    """Each team's fifth by `strength` (team id -> e.g. goal difference per match): 1 the weakest
    to `FIFTHS` the strongest, ties split by order."""
    return pd.qcut(strength.rank(method="first"), FIFTHS, labels=False) + 1


def candidates(
    found: pd.DataFrame, *, side: str, younger_than: float, max_value: float, fifth: pd.Series
) -> dict[str, pd.DataFrame]:
    """The candidates left after each filter in turn, from `found` (`similarity.similar` with every
    candidate, the player's teammates left out): playing on `side`, younger than `younger_than`,
    valued at or under `max_value`, their main team outside the strongest fifth (`fifth`: each
    player's team's fifth, `team_fifths`). Keyed by what each step keeps, in order."""
    steps = {"Not a teammate": found}
    steps[f"On the {side.lower()}"] = kept = found[found.side == side]
    steps[f"{younger_than - 1:g} or under"] = kept = kept[kept.age < younger_than]
    steps["Within the budget"] = kept = kept[kept.value <= max_value]
    steps["Outside the strongest fifth"] = kept[fifth.loc[kept.index] != FIFTHS]
    return steps


def long_list(kept: pd.DataFrame) -> pd.DataFrame:
    """The candidates the last filter kept (`candidates`), sorted by list and distance, with their
    `place` in their list (1: the nearest) and whether they are in its nearer half (`nearer_half`:
    half of each list, rounded up)."""
    out = kept.copy()
    out["place"] = out.groupby("list").cumcount() + 1
    half = out.groupby("list").place.transform("max").add(1) // 2
    out["nearer_half"] = out.place <= half
    return out


def last_teams(con: duckdb.DuckDBPyConnection) -> pd.Series:
    """The team each player played their last pool match for (player id -> team id)."""
    return (
        con.sql("""
            SELECT player_id, arg_max(team_id, match_date) AS team_id
            FROM player_matches JOIN matches USING (match_id)
            WHERE scouting_pool AND played GROUP BY player_id
        """)
        .df()
        .set_index("player_id")
        .team_id
    )


def club_fit(
    rows: pd.DataFrame,
    seasons: Seasons,
    axes: Axes,
    style_values: pd.DataFrame,
    style_descriptors: pd.DataFrame,
    group: str,
    regulars: Collection,
    players: pd.Index,
    club: int,
    last_team: pd.Series,
) -> pd.Series:
    """How well each of `players` fits `club` (`teams.fit`), as notebook 07 reads fit.

    `rows` are the matches of the group's players in its positions (`roles.style_matches`,
    rescaled), `seasons` and `axes` the teams' seasons (`teams.team_seasons`) and style axes
    (`teams.style_axes`). The styles of a player and of every club's players in the position are
    their style descriptors on the season's terms (`roles.place`), in the space of the group's
    `regulars` (`similarity.fit_block`). The team's part is taken out on both sides by the
    descriptors' slopes on the team axes (`teams.style_slopes`) over the regulars who played for
    one team all season: each player at their last team's scores without them (`last_team`), each
    club at its own.
    """
    sums = rows[["team_id", "player_id", *STYLE_SUMS]]

    def on_terms(s: pd.DataFrame) -> pd.DataFrame:
        return place(s, group, style_descriptors)

    season_values = on_terms(sums.drop(columns="team_id").groupby("player_id").sum())
    block = fit_block(season_values[season_values.index.isin(regulars)])
    one_team = whole_season_team(seasons, regulars)
    adjusted = style_values[style_values.comparison_group == group].pivot(
        index="player_id", columns="descriptor", values="adjusted"
    )
    their_teams = scores_without(seasons, axes, one_team.index, one_team.to_numpy())
    slopes = style_slopes(adjusted.loc[one_team.index, season_values.columns], their_teams)
    old = last_team.loc[players]
    distances = fit_distances(
        sums, on_terms, block, players, slopes=slopes,
        team_scores=axes.scores(numbers(seasons.season)),
        old_scores=scores_without(seasons, axes, players, old.to_numpy()),
    )  # fmt: skip
    return fit(distances, pd.Series(club, index=players), old)


def shortlist(listed: pd.DataFrame, n: int) -> pd.DataFrame:
    """The `n` largest gaps (`gap`) in the nearer half of the long list (`long_list`), largest
    first."""
    return listed[listed.nearer_half].sort_values("gap", ascending=False).head(n)


def recommend(short: pd.DataFrame) -> Hashable:
    """The shortlisted player who fits the club best (`fit`); a tie goes to the larger gap."""
    return short.sort_values(["fit", "gap"], ascending=False).index[0]


@dataclass(frozen=True)
class CaseStudy:
    """A case study's choices and what its scouting reports read, all known on the market view."""

    club: int  # the club's StatsBomb team id
    club_name: str
    player: int  # the StatsBomb id of the player it sold
    group: str  # their comparison group
    fee: float  # what the club sold the player for, euros
    sold_to: str  # and to whom
    sold_on: date  # the day of the transfer
    ceiling: float  # the highest market value the fee buys, euros
    players: pd.DataFrame  # the group's `similarity.search_players` rows, with `team_id`,
    # `team_fifth`, `position` and `pool_minutes` (`profile_players.minutes`)
    points: pd.DataFrame  # the group's players in the search's space
    found: pd.DataFrame  # every candidate (`similarity.similar`), the player's teammates left out
    steps: dict[str, pd.DataFrame]  # the candidates filter by filter (`candidates`)
    long_list: pd.DataFrame  # `long_list`, with `gap` and `fit`
    shortlist: pd.DataFrame
    recommended: int
    gap: pd.Series  # the group's gap within team (`market.gap`)
    fit: pd.Series  # fit to the club of every candidate in `found` and of the player
    profile: pd.DataFrame  # the group's `profile_values` rows
    scores: pd.DataFrame  # the group's scores on its style axes, players x axes
    ends: pd.DataFrame  # the axis ends each player stands at (`similarity.style_ends`)
    matches: pd.DataFrame  # the matches each player's style is read from: `match_id`, `player_id`


def case_study(
    con: duckdb.DuckDBPyConnection,
    cfg: Config,
    *,
    rows: pd.DataFrame | None = None,
    seasons: Seasons | None = None,
) -> CaseStudy:
    """The case study of `case_study` in the config, step by step as notebook 08 takes it.

    `rows` (every profiled player's `roles.style_matches`, rescaled with `style_recording`) and
    `seasons` (`teams.team_seasons`) take most of the time to build and are built when not given.
    """
    cs = cfg.case_study
    year = cfg.backtest.market_view.year
    profiled = con.sql("SELECT * FROM profile_players").df().set_index("player_id")
    groups = profiled.comparison_group
    market = market_players(con, cfg).set_index("player_id")
    if rows is None:
        rows = style_matches(con, cfg, groups)
        recorded = con.sql("SELECT * FROM style_recording").df()
        rows = rescale(rows, groups, recording_context(rows, cfg), recorded)
    if seasons is None:
        seasons = team_seasons(con, cfg)
    teams = con.sql("SELECT DISTINCT team_id, team_name FROM teams").df()
    (club,) = teams.team_id[teams.team_name == cs.club]
    (player,) = profiled.index[profiled.known_as == cs.player]

    who = search_players(con, cfg, market, rows)
    who = who[who.group == cs.group].copy()
    strength = team_strength(con).set_index("team_id").goal_difference
    who["team_id"] = market.team_id.loc[who.index]
    who["team_fifth"] = who.team_id.map(team_fifths(strength))
    who["position"] = main_positions(con, cfg, groups).position.loc[who.index]
    who["pool_minutes"] = profiled.minutes.loc[who.index]
    regulars = who.index[who["list"] == "Regulars"]

    sold = sale(con, player, year)
    league = {c.name: c.transfermarkt_competition_id for c in cfg.statsbomb.competitions}
    ratios = fee_ratios(con, cfg, profiled.index, year - 1)  # the summer before
    top = ceiling(sold.transfer_fee, ratios, league[who.league[player]])

    values = con.sql("SELECT * FROM profile_values").df()
    style_values = con.sql("SELECT * FROM style_values").df()
    points = search_points(search_values(style_values, values, cs.group), regulars)
    found = similar(points, who, player, n=None)
    steps = candidates(found, side=who.side[player], younger_than=cs.younger_than, max_value=top,
                       fifth=who.team_fifth)  # fmt: skip
    listed = long_list(steps[list(steps)[-1]])

    pool = [c.name for c in cfg.statsbomb.competitions if c.scouting_pool]
    group_gap = gap(market, profile_matrix(values, cs.group, cfg.profiles[cs.group]), pool)
    in_group = rows[rows.player_id.map(groups) == cs.group]
    style_descriptors = con.sql("SELECT * FROM style_descriptors").df()
    fits = club_fit(
        in_group, seasons, style_axes(seasons.season, cfg), style_values, style_descriptors,
        cs.group, regulars, found.index.append(pd.Index([player])), club, last_teams(con),
    )  # fmt: skip
    listed = listed.assign(gap=group_gap.loc[listed.index], fit=fits.loc[listed.index])
    short = shortlist(listed, cs.shortlist)

    style_scores = con.sql("SELECT * FROM style_scores").df()
    scores = style_scores[style_scores.comparison_group == cs.group].pivot(
        index="player_id", columns="axis", values="score"
    )
    return CaseStudy(
        club=int(club),
        club_name=cs.club,
        player=int(player),
        group=cs.group,
        fee=float(sold.transfer_fee),
        sold_to=sold.to_club_name,
        sold_on=sold.transfer_date.date(),
        ceiling=float(top),
        players=who,
        points=points,
        found=found,
        steps=steps,
        long_list=listed,
        shortlist=short,
        recommended=int(recommend(short)),
        gap=group_gap,
        fit=fits,
        profile=values[values.comparison_group == cs.group],
        scores=scores,
        ends=style_ends(scores, cfg.roles.names[cs.group], regulars),
        matches=in_group[["match_id", "player_id"]],
    )


def signings(con: duckdb.DuckDBPyConnection, case: CaseStudy, season: int) -> pd.Index:
    """The players of the case's group the club signed for `season` (a Transfermarkt season,
    2016 = 2016/17): at the club in the first half of it (`outcomes.first_half_clubs`) after
    playing none of the pool's 2015/16 matches for it. Read after the market view, for comparison
    only."""
    team_map = con.sql("SELECT team_id, club_id FROM team_map").df()
    clubs = team_map.club_id[team_map.team_id == case.club]
    arrived = first_half_clubs(con, season)
    arrived = arrived.player_id[arrived.club_id.isin(clubs)]
    who = case.players
    new = who.index.isin(arrived) & ~who.teams.map(lambda t: case.club in t).astype(bool)
    return who.index[new]

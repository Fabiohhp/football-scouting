"""Team style: how a team plays, from its matches.

`team_match_sums` counts, for every team and pool match, the events behind the team numbers
(`NUMBERS`), next to the opponent's counts the numbers need (prefixed `opp_`) and the time with the
ball (`possession.team_possession`). Counts add up, so a season or any sample of a team's matches
is a sum of rows, and `numbers` turns the sums into the team's numbers.

Definitions (StatsBomb pitch, 120 x 80; each team attacks towards x = 120; open-play passes as in
`analysis.metrics`):
- PPDA (passes per defensive action): the opponent's open-play passes in their own 60% of the
  pitch (x <= 72 from their side) per tackle, interception or foul committed by the team in the
  opponent's 60% (x >= 48); the lower, the harder a team presses;
- the height of defensive actions: the mean x of tackles, interceptions, ball recoveries,
  clearances and blocks (as for players);
- the pressing shares: pressures in the final third (x >= 80) and counterpressures (within five
  seconds of losing the ball) per pressure;
- possession: the team's share of the match's time with the ball;
- field tilt: the team's share of the open-play passes both teams played in their final third;
- passes per possession (StatsBomb's possessions), and tempo: open-play passes per minute with
  the ball;
- directness: the yards towards the opponent's goal line a completed open-play pass gains, on
  average (incomplete passes end where they were cut out, not where they were aimed);
- long balls from the back: open-play passes of 30 yards or more per open-play pass from the own
  third (x < 40); long goal kicks: goal kicks of `LONG_GOAL_KICK` yards or more per goal kick
  (their lengths are bimodal, short ones around 20 yards, long ones around 65);
- wide entries: the share of entries into the final third (completed open-play passes and
  carries from x < 80 to x >= 80) that end outside the width of the box (y < 18 or y > 62);
- crosses per open-play pass in the final third;
- pass ease: the mean expected completion of the team's open-play passes (`analysis.xpass`), the
  risk a team's passing takes.

Counts recorded differently between leagues and in the Premier League from match week 19
(`recording` in the config, and tackles and fouls, which follow the league's refereeing) are put
on one scale by `recording_factors` and `rescale`: within each recording context a count is
multiplied so that its mean per team-match equals the mean over every context, and the location
sums of its events follow it, so that a context keeps its heights. `split_half` measures how
reliably each number, or any function of the numbers such as a team's scores on style axes, tells
teams apart. `pass_network` draws a team's passing between the positions of the formation it
plays most.

`team_seasons` gathers every team's and player's 2015/16 counts on one scale, `style_axes` fits the
team style axes on them (`team_style` in the config) and `scores_without` reads a team's scores
without one of its players. Fit (notebook 07, section 4): `fit_distances` measures how far a
player's style is from every club's in their position, the team's part taken out on both sides by
the slopes of the style descriptors on the team's scores (`style_slopes`, from the players who
played for one team all season, `whole_season_team`), and `fit` reads the distances as a rank among
the clubs.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass

import duckdb
import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist

from football_scouting.analysis import xpass
from football_scouting.analysis.metrics import OPEN_PLAY
from football_scouting.analysis.possession import team_possession
from football_scouting.analysis.profiles import recording_context
from football_scouting.analysis.roles import Axes, fit_axes
from football_scouting.analysis.similarity import Block
from football_scouting.config import Config

KEYS = ["match_id", "team_id"]
PLAYER_KEYS = [*KEYS, "player_id"]
# Columns that identify a row, never summed or subtracted.
INFO = [*PLAYER_KEYS, "competition_id", "match_date", "opponent_id"]
LONG_GOAL_KICK = 40  # yards: the trough between short and long goal kicks
# Counts rescaled by recording context, and the location sums that follow each.
RECORDED = {
    "tackles": ("sum_x_tackles",),
    "tackles_high": (),
    "interceptions": ("sum_x_interceptions",),
    "interceptions_high": (),
    "fouls_high": (),
    "clearances": ("sum_x_clearances",),
    "pressures": (),
    "pressures_final_third": (),
    "counterpressures": (),
}
# The team numbers: {name: label}.
NUMBERS = {
    "ppda": "PPDA (opponent passes per defensive action)",
    "defence_height": "Height of defensive actions (x)",
    "high_press_share": "Final-third pressures per pressure",
    "counterpress_share": "Counterpressures per pressure",
    "possession": "Possession (share of the time with the ball)",
    "field_tilt": "Field tilt (share of final-third passes)",
    "passes_per_possession": "Passes per possession",
    "tempo": "Passes per minute with the ball",
    "directness": "Yards gained per completed pass",
    "long_from_back": "Long passes per pass from the own third",
    "long_goal_kicks": "Long goal kicks per goal kick",
    "wide_entries": "Wide entries into the final third",
    "cross_share": "Crosses per final-third pass",
    "pass_ease": "Pass ease (expected completion)",
}
OPPONENT = ("passes_own60", "passes_final_third", "seconds")  # the opponent's counts used


def player_match_sums(con: duckdb.DuckDBPyConnection, *, pass_ease: bool = True) -> pd.DataFrame:
    """One row per player, team and pool match with an action counted: `competition_id`,
    `match_date` and the counts behind `NUMBERS` that a player's own actions make, as recorded
    (passes, goal kicks, carries, defensive actions, pressures). With `pass_ease`, the open-play
    passes' expected completion (`xpass_passes`, `xpass_expected`), each pass scored by a model
    fitted on other matches."""
    sums = con.execute(f"""
        WITH
        p AS (
            SELECT match_id, team_id, player_id, count(*) AS passes,
                   count(*) FILTER (WHERE completed) AS passes_completed,
                   coalesce(sum(end_x - x) FILTER (WHERE completed), 0) AS forward_yards,
                   count(*) FILTER (WHERE x <= 72) AS passes_own60,
                   count(*) FILTER (WHERE x < 40) AS passes_own_third,
                   count(*) FILTER (WHERE x < 40 AND length >= 30) AS long_passes_own_third,
                   count(*) FILTER (WHERE x >= 80) AS passes_final_third,
                   count(*) FILTER (WHERE x >= 80 AND "cross") AS crosses,
                   count(*) FILTER (WHERE completed AND x < 80 AND end_x >= 80) AS pass_entries,
                   count(*) FILTER (WHERE completed AND x < 80 AND end_x >= 80
                                    AND (end_y < 18 OR end_y > 62)) AS wide_pass_entries
            FROM passes WHERE {OPEN_PLAY} GROUP BY ALL),
        g AS (
            SELECT match_id, team_id, player_id, count(*) AS goal_kicks,
                   count(*) FILTER (WHERE length >= {LONG_GOAL_KICK}) AS long_goal_kicks
            FROM passes WHERE pass_type = 'Goal Kick' GROUP BY ALL),
        c AS (
            SELECT match_id, team_id, player_id,
                   count(*) FILTER (WHERE x < 80 AND end_x >= 80) AS carry_entries,
                   count(*) FILTER (WHERE x < 80 AND end_x >= 80 AND (end_y < 18 OR end_y > 62))
                       AS wide_carry_entries
            FROM carries GROUP BY ALL),
        d AS (
            SELECT match_id, team_id, player_id,
                   count(*) FILTER (WHERE action = 'Tackle') AS tackles,
                   coalesce(sum(x) FILTER (WHERE action = 'Tackle'), 0) AS sum_x_tackles,
                   count(*) FILTER (WHERE action = 'Interception') AS interceptions,
                   coalesce(sum(x) FILTER (WHERE action = 'Interception'), 0)
                       AS sum_x_interceptions,
                   count(*) FILTER (WHERE action = 'Clearance') AS clearances,
                   coalesce(sum(x) FILTER (WHERE action = 'Clearance'), 0) AS sum_x_clearances,
                   count(*) FILTER (WHERE action IN ('Ball Recovery', 'Block'))
                       AS recoveries_blocks,
                   coalesce(sum(x) FILTER (WHERE action IN ('Ball Recovery', 'Block')), 0)
                       AS sum_x_recoveries_blocks,
                   count(*) FILTER (WHERE action = 'Tackle' AND x >= 48) AS tackles_high,
                   count(*) FILTER (WHERE action = 'Interception' AND x >= 48)
                       AS interceptions_high,
                   count(*) FILTER (WHERE action = 'Foul Committed' AND x >= 48) AS fouls_high
            FROM defensive_actions GROUP BY ALL),
        pr AS (
            SELECT match_id, team_id, player_id, count(*) AS pressures,
                   count(*) FILTER (WHERE x >= 80) AS pressures_final_third,
                   count(*) FILTER (WHERE counterpress) AS counterpressures
            FROM pressures GROUP BY ALL),
        k AS (
            SELECT match_id, team_id, player_id FROM p UNION SELECT match_id, team_id, player_id
            FROM g UNION SELECT match_id, team_id, player_id FROM c UNION SELECT match_id,
            team_id, player_id FROM d UNION SELECT match_id, team_id, player_id FROM pr),
        pool AS (
            SELECT k.*, competition_id, match_date FROM k JOIN matches USING (match_id)
            WHERE scouting_pool)
        SELECT pool.*, p.* EXCLUDE (match_id, team_id, player_id),
               g.* EXCLUDE (match_id, team_id, player_id),
               c.* EXCLUDE (match_id, team_id, player_id),
               d.* EXCLUDE (match_id, team_id, player_id),
               pr.* EXCLUDE (match_id, team_id, player_id)
        FROM pool
        LEFT JOIN p USING (match_id, team_id, player_id)
        LEFT JOIN g USING (match_id, team_id, player_id)
        LEFT JOIN c USING (match_id, team_id, player_id)
        LEFT JOIN d USING (match_id, team_id, player_id)
        LEFT JOIN pr USING (match_id, team_id, player_id)
        ORDER BY match_id, team_id, player_id
    """).df()
    for column in sums.columns.drop(INFO, errors="ignore"):
        integer = pd.api.types.is_integer_dtype(sums[column])
        sums[column] = sums[column].fillna(0).astype("int64" if integer else "float64")
    if pass_ease:
        passes = xpass.load_passes(con)
        scored = xpass.player_match_passes(passes, xpass.expected_completion(passes))
        scored = scored.set_index(PLAYER_KEYS)[["passes", "expected"]]
        scored.columns = ["xpass_passes", "xpass_expected"]
        sums = sums.join(scored, on=PLAYER_KEYS)
        sums[scored.columns] = sums[scored.columns].fillna(0).astype(scored.dtypes.to_dict())
    return sums


def team_match_sums(
    con: duckdb.DuckDBPyConnection, players: pd.DataFrame | None = None, *, pass_ease: bool = True
) -> pd.DataFrame:
    """One row per team and pool match: `competition_id`, `match_date`, `opponent_id`, the counts
    behind `NUMBERS` and the opponent's (`OPPONENT`, prefixed `opp_`), as recorded.

    The counts players' actions make are the sums of `players` (`player_match_sums`, computed when
    not given, with or without `pass_ease`); the possessions and the time with the ball are the
    team's.
    """
    if players is None:
        players = player_match_sums(con, pass_ease=pass_ease)
    sums = con.execute("""
        WITH
        sides AS (
            SELECT match_id, competition_id, match_date, home_team_id AS team_id,
                   away_team_id AS opponent_id FROM matches WHERE scouting_pool
            UNION ALL
            SELECT match_id, competition_id, match_date, away_team_id, home_team_id
            FROM matches WHERE scouting_pool),
        po AS (
            SELECT match_id, possession_team_id AS team_id, count(DISTINCT possession)
                AS possessions
            FROM events GROUP BY ALL)
        SELECT s.*, coalesce(po.possessions, 0)::BIGINT AS possessions
        FROM sides s LEFT JOIN po USING (match_id, team_id)
        ORDER BY match_id, team_id
    """).df()
    counted = players.columns.drop(INFO, errors="ignore")
    sums = sums.join(players.groupby(KEYS)[counted].sum(), on=KEYS)
    sums[counted] = sums[counted].fillna(0).astype(players[counted].dtypes.to_dict())
    sums = sums.merge(team_possession(con)[[*KEYS, "seconds"]], on=KEYS, how="left")
    sums["seconds"] = sums["seconds"].fillna(0.0)
    opponent = sums[[*KEYS, *OPPONENT]].rename(
        columns={"team_id": "opponent_id", **{c: f"opp_{c}" for c in OPPONENT}}
    )
    return sums.merge(opponent, on=["match_id", "opponent_id"], validate="1:1")


def without(team: pd.DataFrame, own: pd.DataFrame) -> pd.DataFrame:
    """A team's summed `team_match_sums` rows less a player's own actions in the same matches
    (their summed `player_match_sums` rows, aligned by index): the team without the player. The
    counts no single player makes (the opponent's, the possessions, the time with the ball) stay
    as they are."""
    counted = own.columns.intersection(team.columns).drop(INFO, errors="ignore")
    return team.assign(**{c: team[c] - own[c] for c in counted})


def numbers(sums: pd.DataFrame) -> pd.DataFrame:
    """`NUMBERS` from summed rows of `team_match_sums` (pass ease when it has the columns)."""
    s = sums
    entries = s.pass_entries + s.carry_entries
    defensive = s.tackles + s.interceptions + s.clearances + s.recoveries_blocks
    defensive_x = (
        s.sum_x_tackles + s.sum_x_interceptions + s.sum_x_clearances + s.sum_x_recoveries_blocks
    )
    out = pd.DataFrame({
        "ppda": s.opp_passes_own60 / (s.tackles_high + s.interceptions_high + s.fouls_high),
        "defence_height": defensive_x / defensive,
        "high_press_share": s.pressures_final_third / s.pressures,
        "counterpress_share": s.counterpressures / s.pressures,
        "possession": s.seconds / (s.seconds + s.opp_seconds),
        "field_tilt": s.passes_final_third / (s.passes_final_third + s.opp_passes_final_third),
        "passes_per_possession": s.passes / s.possessions,
        "tempo": s.passes / (s.seconds / 60),
        "directness": s.forward_yards / s.passes_completed,
        "long_from_back": s.long_passes_own_third / s.passes_own_third,
        "long_goal_kicks": s.long_goal_kicks / s.goal_kicks,
        "wide_entries": (s.wide_pass_entries + s.wide_carry_entries) / entries,
        "cross_share": s.crosses / s.passes_final_third,
    }, index=s.index)  # fmt: skip
    if "xpass_passes" in s:
        out["pass_ease"] = s.xpass_expected / s.xpass_passes
    return out


def recording_factors(sums: pd.DataFrame, context: pd.Series) -> pd.DataFrame:
    """One row per `RECORDED` count (`statistic`) and `context`: the factor that brings the
    context's mean per team-match to the mean over every context (`context` aligned with
    `sums`)."""
    columns = list(RECORDED)
    target = sums[columns].mean()
    per_context = sums[columns].groupby(context.to_numpy()).mean()
    return (
        (target / per_context)
        .rename_axis(index="context", columns="statistic")
        .stack()
        .rename("factor")
        .reset_index()[["statistic", "context", "factor"]]
    )


def rescale(sums: pd.DataFrame, context: pd.Series, factors: pd.DataFrame) -> pd.DataFrame:
    """`sums` with each `RECORDED` count, and the location sums that follow it, multiplied by its
    context's factor (1 for a context `factors` lacks)."""
    out = sums.copy()
    for statistic, f in factors.groupby("statistic"):
        factor = f.set_index("context").factor.reindex(context.to_numpy()).fillna(1.0).to_numpy()
        for column in (statistic, *RECORDED[statistic]):
            out[column] = sums[column] * factor
    return out


@dataclass(frozen=True)
class Seasons:
    """Every team's and player's 2015/16 counts, on one scale across recording contexts."""

    recorded: pd.DataFrame  # `team_match_sums`, as recorded
    context: pd.Series  # each team-match's recording context
    factors: pd.DataFrame  # `recording_factors` of the team-matches
    matches: pd.DataFrame  # the team-matches on one scale (`rescale`)
    season: pd.DataFrame  # each team's matches summed (index `team_id`)
    own: pd.DataFrame  # each player's own counts at each team, summed (index player, team)


def team_seasons(con: duckdb.DuckDBPyConnection, cfg: Config) -> Seasons:
    """The team-matches and the players' own counts (`player_match_sums`), rescaled by the
    team-matches' factors, and summed over the season."""
    players = player_match_sums(con)
    recorded = team_match_sums(con, players)
    context = recording_context(recorded, cfg)
    factors = recording_factors(recorded, context)
    matches = rescale(recorded, context, factors)
    own = rescale(players, recording_context(players, cfg), factors)
    return Seasons(
        recorded=recorded,
        context=context,
        factors=factors,
        matches=matches,
        season=matches.groupby("team_id").sum(numeric_only=True),
        own=own.groupby(["player_id", "team_id"]).sum(numeric_only=True),
    )


def style_axes(season: pd.DataFrame, cfg: Config) -> Axes:
    """The team style axes: `team_style.axes` varimax-rotated components of the `team_style`
    numbers of the teams' seasons (`Seasons.season`), as notebook 07 chose them."""
    return fit_axes(numbers(season)[list(cfg.team_style.numbers)], cfg.team_style.axes)


def scores_without(
    seasons: Seasons, axes: Axes, player_ids: Collection, team_ids: Collection
) -> pd.DataFrame:
    """The scores on `axes` of each player's team (`team_ids`, aligned with `player_ids`) over
    the season, without the player's own actions (`without`), indexed by the players."""
    team_rows = seasons.season.loc[team_ids].set_index(pd.Index(player_ids))
    own_rows = seasons.own.loc[list(zip(player_ids, team_ids, strict=True))]
    own_rows = own_rows.set_index(pd.Index(player_ids))
    return axes.scores(numbers(without(team_rows, own_rows)))


def whole_season_team(seasons: Seasons, players: Collection) -> pd.Series:
    """The team of each of `players` who played for one team all season (player -> team), in
    the order of `players`."""
    teams = seasons.own.index.to_frame(index=False).groupby("player_id").team_id.agg(list)
    teams = teams.loc[list(players)]
    return teams[teams.map(len) == 1].str[0]


def style_slopes(values: pd.DataFrame, scores: pd.DataFrame) -> pd.DataFrame:
    """The slope of each column of `values` on each team score (`scores`, rows aligned): least
    squares with an intercept, one row per axis and one column per column of `values`."""
    x1 = np.column_stack([np.ones(len(values)), scores])
    slopes = np.linalg.lstsq(x1, values.to_numpy(float), rcond=None)[0][1:]
    return pd.DataFrame(slopes, index=scores.columns, columns=values.columns)


def fit_distances(
    sums: pd.DataFrame,
    place: Callable[[pd.DataFrame], pd.DataFrame],
    block: Block,
    players: pd.Index,
    *,
    slopes: pd.DataFrame | None = None,
    team_scores: pd.DataFrame | None = None,
    old_scores: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """How far each of `players` is from every club's style in a position: one row per player,
    one column per club.

    `sums` has one row per player, team and match in the position's group: `team_id`,
    `player_id` and the columns `place` reads (every column is summed). `place` turns sums of
    matches into style descriptors on the season's terms, `block` (`similarity.fit_block`) puts
    them in the space distances are measured in. A club's style is read from the summed matches
    of all its players, without the player measured when they played for it.

    With `slopes` (team axes x descriptors, `style_slopes`), the team's part is taken out on both
    sides: each club's at its scores (`team_scores`, teams x axes), each player's at their old
    team's scores without them (`old_scores`, aligned with `players`), so that the distance is
    from the player as they would play at the club.
    """
    by_club = sums.groupby(["team_id", "player_id"]).sum()
    clubs = by_club.groupby(level="team_id").sum()
    theirs = by_club[by_club.index.get_level_values("player_id").isin(players)]
    rest = clubs.loc[theirs.index.get_level_values("team_id")].set_index(theirs.index) - theirs
    season = sums[sums.player_id.isin(players)].drop(columns="team_id").groupby("player_id").sum()
    at = block.coordinates(place(season.loc[players]))
    clubs_at = block.coordinates(place(clubs))
    rest_at = block.coordinates(place(rest))
    if slopes is not None:
        moves = (slopes / block.scale) @ block.transform  # per unit of each team score
        team_part = team_scores @ moves
        at = at - old_scores.loc[players].to_numpy() @ moves.to_numpy()
        clubs_at = clubs_at - team_part.loc[clubs_at.index].to_numpy()
        rest_at = rest_at - team_part.loc[rest_at.index.get_level_values("team_id")].to_numpy()
    out = pd.DataFrame(cdist(at, clubs_at), index=players, columns=clubs_at.index)
    for (team, player), row in zip(rest_at.index, rest_at.to_numpy(), strict=True):
        out.at[player, team] = np.linalg.norm(at.loc[player].to_numpy() - row)
    return out


def split_half(
    sums: pd.DataFrame,
    label: pd.Series,
    *,
    transform: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
    draws: int = 200,
    seed: int = 2016,
) -> pd.DataFrame:
    """Each number's split-half reliability over a season, one row per draw.

    Each draw shuffles every team's matches (rows of `sums`) and deals them alternately into two
    halves; each half's numbers (or `transform` of them, such as scores on style axes), centred
    within the teams' `label` (team_id -> e.g. league), are correlated across teams (Pearson), and
    the correlation r is stepped up to the whole season, twice the matches, by Spearman-Brown:
    2r / (1 + r).
    """
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(draws):
        order = sums.assign(_u=rng.random(len(sums))).sort_values(["team_id", "_u"])
        half = order.groupby("team_id").cumcount() % 2
        summed = order.drop(columns="_u").groupby([order.team_id, half]).sum(numeric_only=True)
        values = numbers(summed)
        if transform is not None:
            values = transform(values)
        values = values - values.groupby(
            [values.index.get_level_values(0).map(label), values.index.get_level_values(1)]
        ).transform("mean")
        r = values.xs(0, level=1).corrwith(values.xs(1, level=1))
        out.append(2 * r / (1 + r))
    return pd.DataFrame(out).reset_index(drop=True)


def fit(distances: pd.DataFrame, club: pd.Series, left_out: pd.Series) -> pd.Series:
    """How well each player fits `club`: the share of the other clubs they are further from.

    `distances` has one row per player and one column per club: how far the player's style is
    from the club's. `club` and `left_out` (the club the player left) are aligned with the rows.
    The other clubs are all but those two, and those with no distance (no players in the
    position); ties count half. 1: the club fits the player best, 0.5: as well as an average
    club, 0: worst; missing if `club` has no distance. A rank takes out how typical a player is:
    a player near the group's mean is near every club.
    """
    d = distances.to_numpy(float)
    rows = np.arange(len(d))
    at = distances.columns.get_indexer(club)
    others = ~np.isnan(d)
    others[rows, at] = False
    others[rows, distances.columns.get_indexer(left_out)] = False
    own = d[rows, at][:, None]
    further = np.where(others, (d > own) + 0.5 * (d == own), 0.0).sum(axis=1)
    out = np.where(np.isnan(own[:, 0]), np.nan, further / others.sum(axis=1))
    return pd.Series(out, index=distances.index, name="fit")


def position_code(position: str) -> str:
    """A StatsBomb position's short name: its initials ("Left Center Back" -> "LCB"), "GK"."""
    return "GK" if position == "Goalkeeper" else "".join(w[0] for w in position.split())


@dataclass(frozen=True)
class Network:
    """A team's passing between the positions of its most used formation."""

    formation: str  # e.g. "4-2-3-1"
    share: float  # of the team's time on the pitch spent in it
    nodes: pd.DataFrame  # one row per position: x, y (the mean start of its passes), passes per 90
    edges: pd.DataFrame  # one row per pair of positions (a, b): completed passes per 90, both ways


def pass_network(con: duckdb.DuckDBPyConnection, team_id: int) -> Network:
    """A team's open-play passing over its pool matches, in the formation it spent the most time
    in (StatsBomb's starting formations and tactical shifts).

    Positions are StatsBomb's, which follow the formation ("Left Center Back"); the eleven that
    passed most in that formation are kept. Passes are counted per 90 minutes in the formation,
    the team attacking towards x = 120; a recipient's position is read from their position stint
    at the time of the pass.
    """
    team_id = int(team_id)  # DuckDB parameters take Python integers, not numpy's
    con.execute("""
        CREATE OR REPLACE TEMP TABLE network_spells AS
        SELECT f.match_id, f.formation, f.match_seconds AS start_seconds,
               coalesce(lead(f.match_seconds) OVER (
                   PARTITION BY f.match_id ORDER BY f.match_seconds, f.event_id),
                   m.duration_seconds) AS end_seconds
        FROM formations f JOIN matches m USING (match_id)
        WHERE m.scouting_pool AND f.team_id = $1
            AND f.type IN ('Starting XI', 'Tactical Shift')
    """, [team_id])  # fmt: skip
    time = con.execute(
        "SELECT formation, sum(end_seconds - start_seconds) AS seconds FROM network_spells "
        "GROUP BY ALL ORDER BY seconds DESC, formation"
    ).df()
    formation, seconds = int(time.formation.iloc[0]), float(time.seconds.iloc[0])
    passes = con.execute(f"""
        SELECT p.position, p.x, p.y, p.completed, r.position AS recipient
        FROM passes p
        JOIN network_spells s ON s.match_id = p.match_id AND s.formation = $2
             AND p.match_seconds >= s.start_seconds AND p.match_seconds < s.end_seconds
        LEFT JOIN player_positions r ON r.match_id = p.match_id AND r.player_id = p.recipient_id
             AND p.match_seconds >= r.start_seconds AND p.match_seconds < r.end_seconds
        WHERE p.team_id = $1 AND {OPEN_PLAY.replace("pass_type", "p.pass_type")}
    """, [team_id, formation]).df()  # fmt: skip
    per_90 = 90 * 60 / seconds
    nodes = passes.groupby("position").agg(x=("x", "mean"), y=("y", "mean"), passes=("x", "size"))
    nodes = nodes.nlargest(11, "passes").assign(passes=lambda n: n.passes * per_90)
    linked = passes[passes.completed & passes.recipient.isin(nodes.index)]
    linked = linked[linked.position.isin(nodes.index) & (linked.position != linked.recipient)]
    pair = np.sort(linked[["position", "recipient"]].to_numpy(), axis=1)
    edges = (
        pd.DataFrame(pair, columns=["a", "b"]).value_counts().mul(per_90).rename("passes")
        .reset_index().sort_values(["a", "b"], ignore_index=True)
    )  # fmt: skip
    return Network(
        formation="-".join(str(formation)),
        share=seconds / time.seconds.sum(),
        nodes=nodes.sort_index(),
        edges=edges,
    )

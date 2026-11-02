"""Similarity search: which players of a comparison group are most alike.

Players are placed in a space made of blocks. A block is a table of a group's players (rows) and
some of their numbers (columns): the scores on the style axes (`style_scores`), the profile's
shrunk statistics (`profile_values`) or the shrunk style descriptors (`style_values`). Each block
is fitted on the group's regulars (`fit_block`):

- standardised by the regulars' mean and standard deviation;
- optionally whitened by their correlations, a Mahalanobis distance within the block: numbers
  that move together, such as passes and progressive passes, then count once;
- scaled so that the block's total variance over the regulars is 1, so that two blocks weigh the
  same whatever their number of columns.

Players are compared by the Euclidean distance between their coordinates (`coordinates`), and
`nearest` gives each player's nearest players. `own_rank` measures how well a space tells players
apart: where a player's own other sample (the other half of their season, their matches at
another club, a few of their matches) ranks among every candidate by distance from the first.
`listed` counts the other players' lists a candidate comes in: a sample that does not tell a
player apart from the group's mean comes in more of them.

The search (notebook 06) compares a group's players by two blocks, neither whitened: their shrunk
style descriptors and their profile (`search_values`, `search_points`). `similar` lists the
candidates nearest a player, list by list (the regulars, and the young players with fewer
minutes apart), filtered by age, league, market value, foot and side; `search_players` gives the
players' rows it reads. Two things say how a candidate is like the player: the ends of the style
axes both stand at (`style_ends`, `in_common`), and the profile statistics they differ most on
(`profile_gaps`). A player's position, team, side (`main_positions`) and line (`line`) are read
from the time they spent in their group's positions.
"""

from __future__ import annotations

from collections.abc import Collection, Hashable, Sequence
from dataclasses import dataclass

import duckdb
import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist

from football_scouting.config import Config

FOOT = 0.5  # left-footed: this share of the passes played with either foot or more with the left
THIRD = 1 / 3  # an axis's ends: the bottom and top third of the regulars' scores


@dataclass(frozen=True)
class Block:
    """A block of the space, fitted on a group's regulars."""

    mean: pd.Series  # each column's mean over the regulars
    scale: pd.Series  # and its standard deviation
    transform: pd.DataFrame  # columns x coordinates: standardised columns to coordinates

    def coordinates(self, values: pd.DataFrame) -> pd.DataFrame:
        """Each row's coordinates in the block; a missing value counts as the regulars' mean."""
        z = ((values[self.mean.index] - self.mean) / self.scale).fillna(0.0)
        return z @ self.transform


def fit_block(values: pd.DataFrame, *, whiten: bool = False) -> Block:
    """A block fitted on the rows of `values` (the regulars): standardised, whitened by the
    symmetric inverse square root of the correlation matrix if `whiten` (each coordinate stays
    closest to its own column), and scaled so that the coordinates' total variance over the rows
    is 1.
    """
    mean, scale = values.mean(), values.std(ddof=0)
    n = values.shape[1]
    transform = np.eye(n)
    if whiten:
        eigenvalues, vectors = np.linalg.eigh(np.corrcoef(values.to_numpy(), rowvar=False))
        transform = vectors @ np.diag(eigenvalues**-0.5) @ vectors.T
    columns = values.columns
    return Block(mean, scale, pd.DataFrame(transform / np.sqrt(n), index=columns, columns=columns))


def coordinates(blocks: dict[str, Block], values: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """The coordinates of the rows of `values` (one table per block, the same rows) in the space
    made of `blocks`, side by side."""
    return pd.concat({name: b.coordinates(values[name]) for name, b in blocks.items()}, axis=1)


def nearest(points: pd.DataFrame, k: int) -> pd.DataFrame:
    """Each row's `k` nearest other rows of `points` (coordinates), nearest first: their labels,
    one column per place (1 to `k`)."""
    d = cdist(points.to_numpy(), points.to_numpy())
    np.fill_diagonal(d, np.inf)
    order = np.argsort(d, axis=1, kind="stable")[:, :k]
    return pd.DataFrame(points.index.to_numpy()[order], index=points.index, columns=range(1, k + 1))


def own_rank(
    queries: pd.DataFrame, candidates: pd.DataFrame, own: pd.DataFrame | None = None
) -> pd.Series:
    """For each row of `queries`, the rank by distance (1: the nearest) of the candidate with the
    same index label among all `candidates` (coordinates; labels unique, each query's among them).
    With `own` (coordinates, a row for each query), a query's own candidate is its row of `own`
    in place of its row of `candidates`, the other candidates keeping theirs.
    """
    at = candidates.index.get_indexer(queries.index)
    if (at < 0).any() or not candidates.index.is_unique:
        raise ValueError("each query needs exactly one candidate with its label")
    q = queries.to_numpy()
    d = cdist(q, candidates.to_numpy())
    rows = np.arange(len(queries))
    if own is not None:
        d[rows, at] = np.linalg.norm(q - own.loc[queries.index, queries.columns].to_numpy(), axis=1)
    closer = (d < d[rows, at][:, None]).sum(axis=1)
    return pd.Series(closer + 1, index=queries.index, name="rank")


def listed(
    queries: pd.DataFrame, candidates: pd.DataFrame, k: int, own: pd.DataFrame | None = None
) -> pd.Series:
    """For each candidate, the number of queries whose `k` nearest candidates include it (ties at
    the edge included). A query and a candidate with the same label are one player, who is not
    listed for themselves. With `own` (coordinates, a row for each candidate), each candidate is
    placed at its row of `own` in turn, the other candidates keeping their rows of `candidates`.
    """
    d = cdist(queries.to_numpy(), candidates.to_numpy())
    at = candidates.index.get_indexer(queries.index)
    rows = np.flatnonzero(at >= 0)
    d[rows, at[rows]] = np.inf
    placed = d if own is None else cdist(queries.to_numpy(), own.loc[candidates.index].to_numpy())
    placed[rows, at[rows]] = np.inf
    s = np.sort(d, axis=1)
    # The k-th nearest of the other candidates: one further if the candidate's own row is nearer.
    edge = np.where(d <= s[:, [k - 1]], s[:, [k]], s[:, [k - 1]])
    return pd.Series((placed <= edge).sum(axis=0), index=candidates.index, name="listed")


def search_values(
    style_values: pd.DataFrame, profile_values: pd.DataFrame, group: str
) -> dict[str, pd.DataFrame]:
    """A comparison group's players in the search's two blocks, one row per player: their shrunk
    style descriptors (`style_values`) and profile statistics (`profile_values`)."""
    blocks = {"descriptors": (style_values, "descriptor"), "profile": (profile_values, "statistic")}
    return {
        block: table[table.comparison_group == group].pivot(
            index="player_id", columns=column, values="shrunk"
        )
        for block, (table, column) in blocks.items()
    }


def search_points(values: dict[str, pd.DataFrame], regulars: Collection) -> pd.DataFrame:
    """The coordinates of the players of `values` (`search_values`) in the search's space, each
    block fitted on the `regulars` among them, neither whitened."""
    blocks = {name: fit_block(v[v.index.isin(regulars)]) for name, v in values.items()}
    return coordinates(blocks, values)


def line(group: str, position: str) -> str | None:
    """The line of a recorded position within its comparison group (None if the group has one):
    central midfielders defensive or central, attacking midfielders and wingers in attacking
    midfield, on the wing or in wide midfield, centre-forwards alone or in a pair."""
    if group == "CM":
        return "Defensive" if "Defensive" in position else "Central"
    if group == "AMW":
        if "Attacking" in position:
            return "Attacking midfield"
        return "Wing" if "Wing" in position else "Wide midfield"
    if group == "CF":
        return "Alone" if position == "Center Forward" else "In a pair"
    return None


def main_positions(con: duckdb.DuckDBPyConnection, cfg: Config, group: pd.Series) -> pd.DataFrame:
    """Each player of `group` (player id -> comparison group): the `position` and the `team_id`
    they spent the most time in among their group's positions, each read on its own (a tie goes
    to the last in sort order), and their `side` ("Left" or "Right" from the position's name,
    missing in the centre)."""
    members = {m: c.code for c in cfg.comparison_groups for m in c.members}
    time_in = con.sql(
        "SELECT player_id, team_id, position, position_group, sum(seconds) AS seconds "
        "FROM player_positions GROUP BY ALL"
    ).df()
    time_in = time_in[time_in.player_id.isin(group.index)]
    time_in = time_in[
        time_in.position_group.map(members) == group.loc[time_in.player_id].to_numpy()
    ]

    def most(column: str) -> pd.Series:
        t = time_in.groupby(["player_id", column]).seconds.sum().reset_index()
        return t.sort_values(["seconds", column]).groupby("player_id")[column].last()

    out = pd.DataFrame({"position": most("position"), "team_id": most("team_id")})
    out["side"] = out.position.str.split().str[0].where(lambda s: s.isin(["Left", "Right"]))
    return out


def search_players(
    con: duckdb.DuckDBPyConnection, cfg: Config, market: pd.DataFrame, rows: pd.DataFrame
) -> pd.DataFrame:
    """One row per player of `market` (`market.market_players`, indexed by `player_id`) with the
    columns `similar` reads and those a list shows.

    `list`: "Regulars" for `compared.minutes` or more in their group's positions (the minutes the
    style is read from), "Young" for players under `compared.young_age` on the market view with
    `compared.young_minutes` or more, missing for the others; `teams`: the set of teams they played
    a pool match for; `left_foot`: the left foot's share of their passes played with either foot
    in their group's positions (from `rows`, `roles.style_matches`); `side` and `line` from their
    `main_positions`; `team` (the name of their main team), `league`, `age`, `minutes` (in their
    group's positions) and `value` (on the market view).
    """
    group = market.comparison_group
    minutes = (
        con.sql("SELECT player_id, max(minutes) AS minutes FROM style_scores GROUP BY player_id")
        .df()
        .set_index("player_id")
        .minutes.reindex(market.index)
    )
    young = (market.age < cfg.compared.young_age) & (minutes >= cfg.compared.young_minutes)
    lists = np.select([minutes >= cfg.compared.minutes, young], ["Regulars", "Young"], None)
    feet = rows.groupby("player_id")[["left_foot_passes", "foot_passes"]].sum()
    teams = con.sql(
        "SELECT DISTINCT pm.player_id, pm.team_id FROM player_matches pm "
        "JOIN matches m USING (match_id) WHERE m.scouting_pool AND pm.played"
    ).df()
    teams = teams[teams.player_id.isin(market.index)].groupby("player_id").team_id.agg(frozenset)
    names = con.sql("SELECT DISTINCT team_id, team_name FROM teams").df().set_index("team_id")
    at = main_positions(con, cfg, group)
    out = pd.DataFrame({
        "name": market.known_as, "group": group, "list": pd.Series(lists, index=market.index),
        "teams": teams, "team": market.team_id.map(names.team_name), "league": market.league,
        "age": market.age, "minutes": minutes, "value": market.value,
        "left_foot": feet.left_foot_passes / feet.foot_passes, "side": at.side,
    }).loc[market.index]  # fmt: skip
    out["line"] = [line(g, at.position[p]) for p, g in out.group.items()]
    return out


def similar(
    points: pd.DataFrame,
    players: pd.DataFrame,
    query: Hashable,
    *,
    n: int | None = 10,
    teammates: bool = False,
    younger_than: float | None = None,
    leagues: Collection[str] | None = None,
    max_value: float | None = None,
    foot: str | None = None,
    side: str | None = None,
) -> pd.DataFrame:
    """The candidates nearest `query`, list by list.

    `points` are the coordinates of a group's players (`search_points`). `players` has a row for
    each, with the columns the search reads: `list` (the list a candidate is shown in; missing
    for a player who is not a candidate), `teams` (the set of teams they played for), `age`,
    `league`, `value` (euros), `left_foot` (the left foot's share of their passes played with
    either foot) and `side` ("Left", "Right", or missing in the centre).

    A candidate is left out if they played for one of the query's teams (unless `teammates`), is
    not younger than `younger_than`, plays outside `leagues`, is valued above `max_value` or not
    valued, is not `foot`-footed ("left": a `left_foot` share of `FOOT` or more; "right": less)
    or plays on another `side`; a filter left at None keeps everyone. Returns the `n` nearest of
    each list (every candidate with `n=None`), sorted by list and distance: their rows of
    `players`, with their `distance` from the query and their `place` in their list (1: the
    nearest).
    """
    if foot not in (None, "left", "right"):
        raise ValueError(f"foot: 'left' or 'right', not {foot!r}")
    out = players.loc[points.index].assign(
        distance=np.linalg.norm(points.to_numpy() - points.loc[query].to_numpy(), axis=1)
    )
    keep = out["list"].notna() & (out.index != query)
    if not teammates:
        keep &= out.teams.map(players.at[query, "teams"].isdisjoint).astype(bool)
    if younger_than is not None:
        keep &= out.age < younger_than
    if leagues is not None:
        keep &= out.league.isin(leagues)
    if max_value is not None:
        keep &= out.value <= max_value
    if foot is not None:
        left = out.left_foot >= FOOT
        keep &= left if foot == "left" else out.left_foot.notna() & ~left
    if side is not None:
        keep &= out.side == side
    out = out[keep].sort_values(["list", "distance"], kind="stable")
    out["place"] = out.groupby("list").cumcount() + 1
    return out if n is None else out[out.place <= n]


def style_ends(
    scores: pd.DataFrame, names: Sequence[tuple[str, str]], regulars: Collection
) -> pd.DataFrame:
    """The end of each style axis each player stands at: the axis's first name (`names`, one
    pair per column of `scores`) in the bottom `THIRD` of the `regulars`' scores, its second in
    the top `THIRD`, missing in between."""
    low, high = scores[scores.index.isin(regulars)].quantile([THIRD, 1 - THIRD]).to_numpy()
    first, second = (np.array([pair[i] for pair in names], dtype=object) for i in (0, 1))
    at = np.where(scores < low, first, np.where(scores > high, second, None))
    return pd.DataFrame(at, index=scores.index, columns=scores.columns)


def in_common(ends: pd.DataFrame, query: Hashable, candidates: Sequence) -> pd.Series:
    """The axis ends (`style_ends`) each candidate stands at with `query`, joined by ", " in the
    axes' order (empty if none)."""
    mine = ends.loc[query]
    same = ends.loc[candidates].eq(mine) & mine.notna()
    return pd.Series(
        [", ".join(mine[row]) for row in same.to_numpy()], index=same.index, name="in_common"
    )


def profile_gaps(percentiles: pd.DataFrame, query: Hashable, candidates: Sequence) -> pd.DataFrame:
    """For each candidate, the profile statistic they are furthest above `query` on and the one
    they are furthest below on, in percentile points (`percentiles`: players x statistics):
    `above` and `above_by`, `below` and `below_by` (missing if they are above or below on
    none)."""
    gap = percentiles.loc[candidates] - percentiles.loc[query]
    up, down = gap.max(axis=1), gap.min(axis=1)
    return pd.DataFrame({
        "above": gap.idxmax(axis=1).where(up > 0), "above_by": up.where(up > 0),
        "below": gap.idxmin(axis=1).where(down < 0), "below_by": down.where(down < 0),
    })  # fmt: skip

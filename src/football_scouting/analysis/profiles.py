"""The player profiles: each player's statistics, comparable within the comparison group.

Players with a profile are those compared (`compared` in the config) in a group with a profile
(`profiles`). Their statistics go through four steps, in this order:

1. **Recording context.** The statistics StatsBomb recorded differently between leagues, and in
   the Premier League from match week 19 (`recording`), are rescaled per context: within each
   comparison group, a context's counts are multiplied so that its rate per 90 equals the
   group's rate over every context. A Premier League player's matches before and after the
   change are rescaled separately.
2. **Possession.** Per-90 statistics are put on an even share of possession by their
   elasticity in the comparison group, measured within players on the group's regulars
   (`analysis.possession`), with the player's share over the season while on the pitch. Ratios
   are kept as recorded. The elasticities are fitted on counts as recorded.
3. **Shrinkage.** Each value is pulled towards the group's average (weighted by minutes) with
   weight M / (M + K): M is the player's minutes, K the minutes at which the statistic is half
   signal, half noise in the group, K = 900 (1 - r) / r from the split-half reliability r of
   the adjusted rates at `RELIABILITY_MINUTES` (`analysis.reliability`). A ratio with no
   attempts (no shots, for xG per shot) takes the group's average.
4. **Percentiles** within the comparison group, the four leagues together: the share of the
   group's players at or below the player's value (ties share the average), reversed where a
   lower number is the better one.

Tables are keyed by `comparison_group` and `statistic`, as the processed profile tables are
(`build_profiles`), so that those can be passed back to the functions.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
import pandas as pd

from football_scouting.analysis.metrics import (
    LOWER_IS_BETTER,
    PER_90,
    SUMMED,
    player_match_counts,
    rates,
)
from football_scouting.analysis.players import pool_player_seasons
from football_scouting.analysis.possession import (
    SIDE,
    adjust_rates,
    elasticity,
    player_possession,
)
from football_scouting.analysis.reliability import split_half_reliability
from football_scouting.config import Config

POSSESSION = ("own_seconds", "opp_seconds")
RELIABILITY_MINUTES = 900  # two halves of 900 minutes: players with 1,800+ minutes


def compared_players(players: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """The players with a profile, from `pool_player_seasons`, with a `young` flag.

    `young`: under `compared.young_age` and compared on `compared.young_minutes`, short of
    `compared.minutes`.
    """
    c = cfg.compared
    regular = players.minutes >= c.minutes
    young = ~regular & (players.minutes >= c.young_minutes) & (players.age < c.young_age)
    profiled = players.comparison_group.astype(str).isin(list(cfg.profiles))
    return players[profiled & (regular | young)].assign(young=young)


def recording_context(counts: pd.DataFrame, cfg: Config) -> pd.Series:
    """Each player-match's recording context: its league, split at the league's change if any."""
    names = {c.competition_id: c.name for c in cfg.statsbomb.competitions}
    context = counts.competition_id.map(names)
    dates = pd.to_datetime(counts.match_date)
    for change in cfg.recording.changes:
        league = counts.competition_id == change.competition_id
        since = f"{change.since:%Y-%m-%d}"
        later = dates >= pd.Timestamp(change.since)
        context = context.mask(league & ~later, context + " before " + since)
        context = context.mask(league & later, context + " from " + since)
    return context.rename("context")


def recording_factors(
    counts: pd.DataFrame, groups: pd.Series, context: pd.Series, statistics: tuple[str, ...]
) -> pd.DataFrame:
    """One row per comparison group, statistic and context: the factor applied to its counts.

    The factor brings the context's rate per 90 to the group's rate over every context, among
    the players in `groups` (player_id -> comparison group); `context` is aligned with `counts`.
    """
    key = ["comparison_group", "context"]
    d = counts.assign(comparison_group=counts.player_id.map(groups), context=context)
    d = d.dropna(subset="comparison_group")
    columns = [*statistics, "minutes"]
    per_context = d.groupby(key)[columns].sum()
    overall = d.groupby("comparison_group")[columns].sum()
    rate = per_context[list(statistics)].div(per_context.minutes, axis=0)
    target = overall[list(statistics)].div(overall.minutes, axis=0)
    target = target.reindex(rate.index.get_level_values("comparison_group")).set_axis(rate.index)
    return (
        (target / rate)
        .rename_axis(columns="statistic")
        .stack()
        .rename("factor")
        .reset_index()[["comparison_group", "statistic", "context", "factor"]]
    )


def rescale(
    counts: pd.DataFrame, groups: pd.Series, context: pd.Series, factors: pd.DataFrame
) -> pd.DataFrame:
    """`counts` with each statistic in `factors` multiplied by its group's and context's factor.

    Rows of players outside `groups` are left as recorded.
    """
    out = counts.copy()
    key = pd.MultiIndex.from_arrays([counts.player_id.map(groups), context])
    for m, f in factors.groupby("statistic"):
        factor = f.set_index(["comparison_group", "context"]).factor.reindex(key).fillna(1.0)
        out[m] = counts[m] * factor.to_numpy()
    return out


def own_share(sums: pd.DataFrame) -> pd.Series:
    """The team's share of possession while the player was on the pitch."""
    return sums.own_seconds / (sums.own_seconds + sums.opp_seconds)


def elasticities(
    counts: pd.DataFrame, groups: pd.Series, profiles: dict[str, tuple[str, ...]]
) -> pd.DataFrame:
    """Elasticity to possession of each per-90 profile statistic, within its comparison group.

    `counts` has one row per player and match with the `POSSESSION` columns; the players fitted
    on are those in `groups` (player_id -> comparison group). One row per group and statistic:
    side, elasticity and its standard error (`possession.elasticity`).
    """
    d = counts[counts.player_id.isin(groups.index)].copy()
    d["comparison_group"] = d.player_id.map(groups)
    d["with"] = own_share(d)
    d["without"] = 1 - d["with"]
    rows = []
    for g, statistics in profiles.items():
        sub = d[d.comparison_group == g]
        for m in statistics:
            if m in PER_90:
                beta, se = elasticity(sub, m, SIDE[m])
                rows.append({"comparison_group": g, "statistic": m, "side": SIDE[m],
                             "elasticity": beta, "elasticity_se": se})  # fmt: skip
    return pd.DataFrame(rows)


def adjusted_rates(sums: pd.DataFrame, groups: pd.Series, beta: pd.DataFrame) -> pd.DataFrame:
    """Rates and ratios from summed counts, per-90 rates put on an even share of possession.

    `sums` has the `SUMMED` and `POSSESSION` columns, `groups` each row's comparison group
    (aligned with `sums`) and `beta` the elasticities (`elasticities`; rows without one, as
    ratios have in `profile_statistics`, are left out).
    """
    r = rates(sums)
    share = own_share(sums)
    out = r.copy()
    for g, b in beta.dropna(subset="elasticity").groupby("comparison_group"):
        rows = (groups == g).to_numpy()
        out.loc[rows] = adjust_rates(
            r.loc[rows], share.loc[rows], b.set_index("statistic").elasticity
        )
    return out


def reliability(
    counts: pd.DataFrame,
    players: pd.DataFrame,
    profiles: dict[str, tuple[str, ...]],
    beta: pd.DataFrame,
    *,
    minutes: float = RELIABILITY_MINUTES,
    draws: int = 50,
) -> pd.DataFrame:
    """Split-half reliability at `minutes` of each profile statistic, adjusted for possession.

    `players` is indexed by player_id with `comparison_group` and `league` (rates are centred
    within league); `counts` has the `SUMMED` and `POSSESSION` columns. One row per comparison
    group and statistic: the reliability r (mean of `draws` random splits) and
    K = minutes (1 - r) / r.
    """
    rows = []
    for g, statistics in profiles.items():
        ids = players.index[players.comparison_group == g]
        curve = split_half_reliability(
            counts[counts.player_id.isin(ids)],
            players.league.loc[ids],
            list(statistics),
            [minutes],
            draws=draws,
            columns=[*SUMMED, *POSSESSION],
            rate_fn=lambda s, g=g: adjusted_rates(s, pd.Series(g, index=s.index), beta),
        )
        r = curve[list(statistics)].mean()
        rows += [{"comparison_group": g, "statistic": m, "reliability": r[m],
                  "k": minutes * (1 - r[m]) / r[m]} for m in statistics]  # fmt: skip
    return pd.DataFrame(rows)


def shrink(values: pd.DataFrame, statistics: pd.DataFrame) -> pd.DataFrame:
    """`values` with `group_mean`, `weight` and `shrunk` columns.

    `values` has one row per player and statistic (`comparison_group`, `statistic`, `minutes`,
    `adjusted`); `statistics` one row per group and statistic with `k`. The group's mean is
    weighted by minutes; a missing value (a ratio with no attempts) takes it with weight 0.
    """
    key = ["comparison_group", "statistic"]
    d = values.merge(statistics[[*key, "k"]], on=key)
    known = d.adjusted.notna()
    by = [d.comparison_group, d.statistic]
    total = (d.adjusted * d.minutes).where(known).groupby(by).transform("sum")
    d["group_mean"] = total / d.minutes.where(known).groupby(by).transform("sum")
    d["weight"] = (d.minutes / (d.minutes + d.k)).where(known, 0.0)
    d["shrunk"] = d.group_mean + d.weight * (d.adjusted.fillna(0) - d.group_mean)
    return d.drop(columns="k")


def percentiles(values: pd.DataFrame, column: str = "shrunk") -> pd.Series:
    """Percentile of `column` within each group and statistic, 100 for the best player.

    The share of the group's players at or below the player (ties share the average), with
    the order reversed for the statistics in `LOWER_IS_BETTER`.
    """
    better = values[column].where(~values.statistic.isin(LOWER_IS_BETTER), -values[column])
    return 100 * better.groupby([values.comparison_group, values.statistic]).rank(pct=True)


@dataclass(frozen=True)
class Profiles:
    players: pd.DataFrame  # one row per player with a profile
    values: pd.DataFrame  # one row per player and profile statistic
    statistics: pd.DataFrame  # one row per comparison group and profile statistic
    recording: pd.DataFrame  # one row per comparison group, recording statistic and context


def build_profiles(con: duckdb.DuckDBPyConnection, cfg: Config) -> Profiles:
    """Every profile, from the processed tables: the four steps of the module docstring."""
    key = ["comparison_group", "statistic"]
    pool = pool_player_seasons(con, cfg, age_on=cfg.backtest.market_view)
    players = compared_players(pool, cfg).set_index("player_id")
    players["comparison_group"] = players.comparison_group.astype(str)
    group = players.comparison_group
    names = con.sql("SELECT player_id, coalesce(player_nickname, player_name) AS n FROM players")
    players["known_as"] = names.df().set_index("player_id").n.reindex(players.index)
    counts = player_match_counts(con).merge(
        player_possession(con), on=["match_id", "team_id", "player_id"], how="left"
    )
    counts = counts[counts.player_id.isin(players.index)]

    # 1. Recording context.
    context = recording_context(counts, cfg)
    factors = recording_factors(counts, group, context, cfg.recording.statistics)
    rescaled = rescale(counts, group, context, factors)
    # 2. Possession, with elasticities fitted on the regulars' counts as recorded.
    beta = elasticities(counts, group[players.minutes >= cfg.compared.minutes], cfg.profiles)
    sums = rescaled.groupby("player_id")[[*SUMMED, *POSSESSION]].sum().loc[players.index]
    adjusted = adjusted_rates(sums, group, beta)
    recorded = rates(counts.groupby("player_id")[SUMMED].sum().loc[players.index])
    players["possession"] = own_share(sums)
    # 3. Shrinkage, K from the players with two halves of RELIABILITY_MINUTES.
    long_season = players[players.minutes >= 2 * RELIABILITY_MINUTES]
    statistics = pd.DataFrame(
        [(g, m, i) for g, ms in cfg.profiles.items() for i, m in enumerate(ms)],
        columns=[*key, "order"],
    )
    statistics = statistics.merge(beta, on=key, how="left").merge(
        reliability(rescaled, long_season, cfg.profiles, beta), on=key
    )
    values = players[["comparison_group", "minutes"]].reset_index().merge(statistics[key])
    for name, frame in (("recorded", recorded), ("adjusted", adjusted)):
        values[name] = frame.to_numpy()[
            frame.index.get_indexer(values.player_id), frame.columns.get_indexer(values.statistic)
        ]
    values = shrink(values, statistics)
    # 4. Percentiles.
    values["percentile"] = percentiles(values)

    statistics = statistics.merge(values.groupby(key).group_mean.first().reset_index())
    statistics["side"] = statistics.side.fillna("ratio")
    statistics["recording_context"] = statistics.statistic.isin(cfg.recording.statistics)
    statistics["lower_is_better"] = statistics.statistic.isin(LOWER_IS_BETTER)
    order = statistics.set_index(key).order
    values["order"] = order.reindex(pd.MultiIndex.from_frame(values[key])).to_numpy()
    rank = {g.code: i for i, g in enumerate(cfg.comparison_groups)}

    def by_group(d: pd.DataFrame, *within: str) -> pd.DataFrame:
        """`d` sorted by comparison group in config order, then by `within`."""
        d = d.sort_values(list(within)) if within else d
        out = d.sort_values("comparison_group", key=lambda s: s.map(rank), kind="stable")
        return out.reset_index(drop=True)

    return Profiles(
        players=by_group(players.reset_index())[
            ["player_id", "player_name", "known_as", "comparison_group", "league", "minutes",
             "age", "young", "possession"]
        ],
        values=by_group(values, "player_id", "order")[
            ["player_id", *key, "minutes", "recorded", "adjusted", "group_mean", "weight",
             "shrunk", "percentile"]
        ],
        statistics=by_group(statistics)[
            [*key, "order", "side", "recording_context", "lower_is_better", "elasticity",
             "elasticity_se", "reliability", "k", "group_mean"]
        ],
        recording=by_group(factors, "statistic", "context"),
    )  # fmt: skip

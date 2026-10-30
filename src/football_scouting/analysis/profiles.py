"""The player profiles: each player's statistics, comparable within the comparison group.

Players with a profile are those compared (`compared` in the config) in a group with a profile
(`profiles`). The statistics are rates and ratios of `analysis.metrics` and two possession-value
numbers (`VALUES`): `xt`, the xT a player's passes and carries gain per 90 (`analysis.xt`: the
config's map and version of the credit, the map fitted on every pool match), and
`completion_above_expected`, completions less expected completions per open-play pass
(`analysis.xpass`: each pass scored by a model fitted on other matches). `value_sums` adds the
sums behind them to the player-match counts. The statistics go through four steps, in this
order:

1. **Recording context.** The statistics StatsBomb recorded differently between leagues, and in
   the Premier League from match week 19 (`recording`), are rescaled per context: within each
   comparison group, a context's counts are multiplied so that its rate per 90 equals the
   group's rate over every context. A Premier League player's matches before and after the
   change are rescaled separately.
2. **Possession.** Per-90 statistics, xT among them, are put on an even share of possession by
   their elasticity in the comparison group, measured within players on the group's regulars
   (`analysis.possession`), with the player's share over the season while on the pitch;
   completion above expected by its slope within players (`xpass.possession_slope`). Other
   ratios are kept as recorded. Elasticities and slopes are fitted on counts as recorded.
3. **Shrinkage.** Each value is pulled towards the group's average (weighted by minutes) with
   weight M / (M + K): M is the player's minutes, K the minutes at which the statistic is half
   signal, half noise in the group, K = 900 (1 - r) / r from the split-half reliability r of
   the adjusted rates at `RELIABILITY_MINUTES` (`analysis.reliability`). A ratio with no
   attempts (no shots, for xG per shot) takes the group's average.
4. **Percentiles** within the comparison group, the four leagues together: the share of the
   group's players at or below the player's value (ties share the average), reversed where a
   lower number is the better one.

Tables are keyed by `comparison_group` and `statistic`, as the processed profile tables are
(`build_profiles`), so that those can be passed back to the functions. `place` puts any sums of a
player's matches (a half season, the matches at one club) on the season's terms: the group's
elasticities and slopes, and shrinkage towards the season's group mean with the season's K.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
import numpy as np
import pandas as pd

from football_scouting.analysis import xpass, xt
from football_scouting.analysis.metrics import (
    FAMILIES,
    LOWER_IS_BETTER,
    SUMMED,
    player_match_counts,
    rates,
)
from football_scouting.analysis.metrics import LABELS as METRIC_LABELS
from football_scouting.analysis.players import pool_player_seasons
from football_scouting.analysis.possession import SIDE, adjust, elasticity, player_possession
from football_scouting.analysis.reliability import split_half_reliability
from football_scouting.config import Config

KEYS = ["match_id", "team_id", "player_id"]
POSSESSION = ("own_seconds", "opp_seconds")
RELIABILITY_MINUTES = 900  # two halves of 900 minutes: players with 1,800+ minutes
# The possession-value numbers: {statistic: label}.
VALUES = {"xt": "xT gained", "completion_above_expected": "Pass completion above expected"}
LABELS = METRIC_LABELS | VALUES
# The family of every statistic (`metrics.FAMILIES`): xT values a move by the chance it leads to.
FAMILY_OF = {m: f for f, ms in FAMILIES.items() for m in ms} | {
    "xt": "Chance creation",
    "completion_above_expected": "Passing and progression",
}
SIDES = SIDE | {"xt": "with"}  # side of possession of each per-90 statistic
# The sums behind the possession-value numbers: xT credit (the config's version), and the
# open-play passes, completions and expected completions of `xpass.player_match_passes` under
# their own names.
XPASS_SUMS = {k: f"xpass_{k}" for k in ("passes", "completed", "expected")}
VALUE_SUMS = ("xt", *XPASS_SUMS.values())


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


def value_sums(
    con: duckdb.DuckDBPyConnection, cfg: Config, statistics: set[str] | frozenset[str]
) -> pd.DataFrame:
    """One row per player and match with an action: the sums behind the possession-value
    numbers among `statistics` (`VALUE_SUMS`; `KEYS` alone when there is none)."""
    out = pd.DataFrame(columns=KEYS, dtype="int64")
    if "xt" in statistics:
        actions = xt.load_actions(con, losses=cfg.xt.losses)
        xt_map = xt.fit(actions, cfg.xt.nx, cfg.xt.ny, shot_value=cfg.xt.shot_value)
        credit = xt.player_match_credit(xt_map, actions)
        credit["xt"] = xt.total_credit(credit, cfg.xt.credit)
        out = out.merge(credit[[*KEYS, "xt"]], on=KEYS, how="outer")
    if "completion_above_expected" in statistics:
        passes = xpass.load_passes(con)
        sums = xpass.player_match_passes(passes, xpass.expected_completion(passes))
        out = out.merge(sums.rename(columns=XPASS_SUMS), on=KEYS, how="outer")
    return out.fillna(0.0)


def match_counts(
    con: duckdb.DuckDBPyConnection, cfg: Config, statistics: set[str] | frozenset[str]
) -> pd.DataFrame:
    """One row per player and pool match played: the `metrics` counts, the time with and without
    the ball (`possession.player_possession`) and the sums behind the possession-value numbers
    among `statistics` (`value_sums`), as recorded."""
    counts = player_match_counts(con).merge(player_possession(con), on=KEYS, how="left")
    worth = value_sums(con, cfg, statistics)
    counts = counts.merge(worth, on=KEYS, how="left", validate="1:1")
    return counts.fillna(dict.fromkeys(worth.columns.drop(KEYS), 0.0))


def summed_columns(counts: pd.DataFrame) -> list[str]:
    """The columns a profile sums over matches: `SUMMED`, `POSSESSION` and the `VALUE_SUMS` in
    `counts`."""
    return [*SUMMED, *POSSESSION, *(c for c in VALUE_SUMS if c in counts)]


def _passes(sums: pd.DataFrame) -> pd.DataFrame:
    """The `XPASS_SUMS` of `sums` under `xpass.player_match_passes`' names."""
    return pd.DataFrame({k: sums[v] for k, v in XPASS_SUMS.items()}, index=sums.index)


def profile_rates(sums: pd.DataFrame) -> pd.DataFrame:
    """`metrics.rates`, with `xt` per 90 and `completion_above_expected` (NaN without a pass)
    when `sums` has the columns behind them."""
    out = rates(sums)
    if "xt" in sums:
        out["xt"] = sums["xt"] / sums["minutes"] * 90
    if XPASS_SUMS["passes"] in sums:
        out["completion_above_expected"] = xpass.completion_rates(_passes(sums)).above_expected
    return out


def own_share(sums: pd.DataFrame) -> pd.Series:
    """The team's share of possession while the player was on the pitch."""
    return sums.own_seconds / (sums.own_seconds + sums.opp_seconds)


def possession_effects(
    counts: pd.DataFrame, groups: pd.Series, profiles: dict[str, tuple[str, ...]]
) -> pd.DataFrame:
    """How each profile statistic depends on possession, within players of its comparison group.

    `counts` has one row per player and match with the `POSSESSION` columns (and the
    `VALUE_SUMS` of the possession-value numbers); the players fitted on are those in `groups`
    (player_id -> comparison group). One row per group and statistic adjusted for possession:
    side, the elasticity of a per-90 statistic and its standard error
    (`possession.elasticity`), or the slope of completion above expected
    (`xpass.possession_slope`, on the team's share).
    """
    d = counts[counts.player_id.isin(groups.index)].copy()
    d["comparison_group"] = d.player_id.map(groups)
    d["with"] = own_share(d)
    d["without"] = 1 - d["with"]
    rows = []
    for g, statistics in profiles.items():
        sub = d[d.comparison_group == g]
        for m in statistics:
            row = {"comparison_group": g, "statistic": m, "side": SIDES.get(m, "with")}
            if m in SIDES:
                row["elasticity"], row["elasticity_se"] = elasticity(sub, m, SIDES[m])
            elif m == "completion_above_expected":
                passes = _passes(sub).assign(player_id=sub.player_id)
                row["slope"] = xpass.possession_slope(passes, own_share(sub))
            else:
                continue
            rows.append(row)
    columns = ["comparison_group", "statistic", "side", "elasticity", "elasticity_se", "slope"]
    return pd.DataFrame(rows, columns=columns)


def adjusted_rates(sums: pd.DataFrame, groups: pd.Series, effects: pd.DataFrame) -> pd.DataFrame:
    """Rates and ratios from summed counts (`profile_rates`), on an even share of possession:
    per-90 rates by their elasticity, completion above expected by its slope.

    `sums` has the `SUMMED` and `POSSESSION` columns (and the `VALUE_SUMS` of the
    possession-value numbers), `groups` each row's comparison group (aligned with `sums`) and
    `effects` the elasticities and slopes (`possession_effects`; rows without one, as ratios
    have in `profile_statistics`, are left out).
    """
    r = profile_rates(sums)
    share = own_share(sums)
    out = r.copy()
    for g, e in effects.groupby("comparison_group"):
        rows = (groups == g).to_numpy()
        e = e.set_index("statistic")
        for m, beta in e.elasticity.dropna().items():
            side = share[rows] if SIDES[m] == "with" else 1 - share[rows]
            out.loc[rows, m] = adjust(r.loc[rows, m], side, beta)
        for m, slope in e.get("slope", pd.Series(dtype=float)).dropna().items():
            out.loc[rows, m] = xpass.adjust_above_expected(r.loc[rows, m], share[rows], slope)
    return out


def reliability(
    counts: pd.DataFrame,
    players: pd.DataFrame,
    profiles: dict[str, tuple[str, ...]],
    effects: pd.DataFrame,
    *,
    minutes: float = RELIABILITY_MINUTES,
    draws: int = 50,
) -> pd.DataFrame:
    """Split-half reliability at `minutes` of each profile statistic, adjusted for possession.

    `players` is indexed by player_id with `comparison_group` and `league` (rates are centred
    within league); `counts` has the `summed_columns`. One row per comparison group and
    statistic: the reliability r (mean of `draws` random splits) and K = minutes (1 - r) / r.
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
            columns=summed_columns(counts),
            rate_fn=lambda s, g=g: adjusted_rates(s, pd.Series(g, index=s.index), effects),
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


def towards(
    values: pd.DataFrame, minutes: pd.Series, mean: pd.Series, k: pd.Series
) -> pd.DataFrame:
    """`values` (rows x statistics) pulled towards `mean` with weight M / (M + K), M each row's
    `minutes` and K each statistic's `k` (`shrink` with a given mean); a missing value takes the
    mean."""
    m = minutes.to_numpy()[:, None]
    weight = np.where(values.isna(), 0.0, m / (m + k.loc[values.columns].to_numpy()))
    return mean.loc[values.columns] + weight * (values.fillna(0.0) - mean.loc[values.columns])


def place(sums: pd.DataFrame, group: str, statistics: pd.DataFrame) -> pd.DataFrame:
    """The profile of `group` from any sums of a player's matches, on the season's terms.

    `sums` has the `summed_columns`, counts already rescaled for their recording context
    (`rescale`, with `profile_recording`), one row per set of matches; `statistics` is
    `profile_statistics`. Rates and ratios on an even share of possession by the group's
    elasticities and slopes (`adjusted_rates`), pulled towards the season's group mean with the
    season's K (`towards`); one column per statistic of the group, in profile order.
    """
    s = statistics[statistics.comparison_group == group].sort_values("order")
    adjusted = adjusted_rates(sums, pd.Series(group, index=sums.index), s)[list(s.statistic)]
    s = s.set_index("statistic")
    return towards(adjusted, sums.minutes, s.group_mean, s.k)


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


def build_profiles(
    con: duckdb.DuckDBPyConnection,
    cfg: Config,
    profiles: dict[str, tuple[str, ...]] | None = None,
) -> Profiles:
    """Every profile, from the processed tables: the four steps of the module docstring.

    `profiles` defaults to the config's; `cfg.count_profiles` gives the profiles as chosen from
    the event counts, without the possession-value numbers (and the time they take).
    """
    profiles = cfg.profiles if profiles is None else profiles
    key = ["comparison_group", "statistic"]
    pool = pool_player_seasons(con, cfg, age_on=cfg.backtest.market_view)
    players = compared_players(pool, cfg).set_index("player_id")
    players["comparison_group"] = players.comparison_group.astype(str)
    group = players.comparison_group
    names = con.sql("SELECT player_id, coalesce(player_nickname, player_name) AS n FROM players")
    players["known_as"] = names.df().set_index("player_id").n.reindex(players.index)
    counts = match_counts(con, cfg, {m for ms in profiles.values() for m in ms})
    counts = counts[counts.player_id.isin(players.index)]
    columns = summed_columns(counts)

    # 1. Recording context.
    context = recording_context(counts, cfg)
    factors = recording_factors(counts, group, context, cfg.recording.statistics)
    rescaled = rescale(counts, group, context, factors)
    # 2. Possession, with elasticities and slopes fitted on the regulars' counts as recorded.
    effects = possession_effects(counts, group[players.minutes >= cfg.compared.minutes], profiles)
    sums = rescaled.groupby("player_id")[columns].sum().loc[players.index]
    adjusted = adjusted_rates(sums, group, effects)
    recorded = profile_rates(counts.groupby("player_id")[columns].sum().loc[players.index])
    players["possession"] = own_share(sums)
    # 3. Shrinkage, K from the players with two halves of RELIABILITY_MINUTES.
    long_season = players[players.minutes >= 2 * RELIABILITY_MINUTES]
    statistics = pd.DataFrame(
        [(g, m, i) for g, ms in profiles.items() for i, m in enumerate(ms)],
        columns=[*key, "order"],
    )
    statistics = statistics.merge(effects, on=key, how="left").merge(
        reliability(rescaled, long_season, profiles, effects), on=key
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
             "elasticity_se", "slope", "reliability", "k", "group_mean"]
        ],
        recording=by_group(factors, "statistic", "context"),
    )  # fmt: skip

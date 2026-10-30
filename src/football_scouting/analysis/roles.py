"""Roles within a comparison group: how players differ in style, from their style descriptors.

The descriptors are those of `roles.descriptors` in the config (`analysis.style`), on an even
share of possession and shrunk towards the group's mean by their reliability (`shrink`, as the
profiles are). Two readings are fitted on the descriptors of the group's regulars:

- **Roles as groups**: a Gaussian mixture on the principal components that hold `VARIANCE` of
  the standardised descriptors' variation (`fit`), each player with the probability of each role
  (`membership`). The number of roles and the shape of the components follow a rule fixed before
  any role was seen (`candidates`, `choose`): the lowest BIC among the mixtures in which every
  role is the main role of at least `MIN_SHARE` of the regulars and that refits on random halves
  of the regulars reproduce (`stability`, a mean adjusted Rand index of `MIN_STABILITY` or more).
- **Style axes**: the principal components of the standardised descriptors, varimax-rotated so
  that each axis opposes a few descriptors (`fit_axes`); each player gets a score on each axis
  (`Axes.scores`). Axes are kept while they stand above shuffled data (`parallel_analysis`), are
  reliable within players and are found again in random halves of the regulars (`congruence`,
  averaged over `HALVES` halves).

`build_style` chains the steps for `make profiles`, with the descriptors and axes of the config
(`roles`): each player's descriptors as recorded, on an even share and shrunk, and their scores
on their group's axes, with the slopes, reliabilities, recording factors and loadings behind
them. The style is read from the matches a player spent `style.IN_GROUP` or more of in a position
of their group (`style_matches`), after the recording-context rescaling of the profiles. `place`
puts any sums of a player's matches (a half season, the matches at one club) on the season's
terms, and `axes_of` gives back a group's axes from the processed tables.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy.optimize import linear_sum_assignment
from sklearn.decomposition import PCA
from sklearn.metrics import adjusted_rand_score
from sklearn.mixture import GaussianMixture
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler

from football_scouting.analysis.metrics import player_match_counts
from football_scouting.analysis.possession import player_possession
from football_scouting.analysis.profiles import (
    KEYS,
    POSSESSION,
    RELIABILITY_MINUTES,
    XPASS_SUMS,
    own_share,
    recording_context,
    recording_factors,
    rescale,
    towards,
    value_sums,
)
from football_scouting.analysis.profiles import shrink as shrink_values
from football_scouting.analysis.reliability import split_half_reliability
from football_scouting.analysis.style import (
    IN_GROUP,
    SUMMED,
    adjust,
    descriptors,
    group_share,
    player_match_style,
    possession_slopes,
)
from football_scouting.config import Config

VARIANCE = 0.8  # share of the descriptors' variation the mixture's principal components keep
COVARIANCES = ("full", "tied", "diag")  # shapes of the mixture's components
ROLES = range(2, 8)  # numbers of roles tried
MIN_SHARE = 0.1  # every role is the main role of at least this share of the regulars
MIN_STABILITY = 0.6  # mean adjusted Rand index of refits on half the regulars
N_INIT = 10  # starts of each mixture fit, the best kept
QUANTILE = 0.95  # an axis stands above this quantile of shuffled data's eigenvalues
MIN_AXIS_RELIABILITY = 0.7  # an axis's split-half reliability at 900 minutes
MIN_CONGRUENCE = 0.85  # an axis's mean congruence with the axes of half the regulars
HALVES = 20_000  # random halves the congruence is averaged over (standard error about 0.001)


def shrink(values: pd.DataFrame, minutes: pd.Series, groups: pd.Series, k: pd.DataFrame):
    """`values` (players x descriptors) pulled towards their group's mean, weighted by minutes,
    with weight M / (M + K) (`profiles.shrink`); `k` holds K per descriptor (rows) and group
    (columns).
    """
    long = values.rename_axis(index="player_id", columns="statistic").stack(future_stack=True)
    long = long.rename("adjusted").reset_index()
    long["comparison_group"] = long.player_id.map(groups)
    long["minutes"] = long.player_id.map(minutes)
    statistics = k.rename_axis(index="statistic", columns="comparison_group").stack()
    out = shrink_values(long, statistics.rename("k").reset_index())
    return out.pivot(index="player_id", columns="statistic", values="shrunk").loc[
        values.index, values.columns
    ]


def fit(x: pd.DataFrame, roles: int, covariance: str, *, seed: int = 0) -> Pipeline:
    """Standardised descriptors, their principal components, a Gaussian mixture of `roles`."""
    mixture = GaussianMixture(roles, covariance_type=covariance, n_init=N_INIT, random_state=seed)
    model = make_pipeline(StandardScaler(), PCA(VARIANCE, svd_solver="full"), mixture)
    return model.fit(x.to_numpy())


def bic(model: Pipeline, x: pd.DataFrame) -> float:
    """The mixture's BIC on the principal components of `x`."""
    return model[-1].bic(model[:-1].transform(x.to_numpy()))


def role_means(model: Pipeline, columns: pd.Index) -> pd.DataFrame:
    """Each mixture component's mean in the descriptors' units (rows: components)."""
    scaler, pca, mixture = model
    means = scaler.inverse_transform(pca.inverse_transform(mixture.means_))
    return pd.DataFrame(means, columns=columns)


def membership(model: Pipeline, x: pd.DataFrame, order_by: str = "touch_height") -> pd.DataFrame:
    """Each player's probability of each role (columns 1, 2, ...), roles numbered by their mean
    of `order_by`, lowest first.
    """
    order = role_means(model, x.columns)[order_by].sort_values(kind="stable").index
    p = model.predict_proba(x.to_numpy())[:, order]
    return pd.DataFrame(p, index=x.index, columns=pd.RangeIndex(1, len(order) + 1, name="role"))


def stability(x: pd.DataFrame, labels: np.ndarray, roles: int, covariance: str, *,
              draws: int = 50, seed: int = 0, n_jobs: int = 4) -> np.ndarray:  # fmt: skip
    """Adjusted Rand index between `labels` and the main roles of every row of `x` under a mixture
    fitted on a random half of the rows, one per draw.
    """
    rng = np.random.default_rng(seed)
    halves = [rng.choice(len(x), len(x) // 2, replace=False) for _ in range(draws)]

    def refit(d: int) -> float:
        model = fit(x.iloc[halves[d]], roles, covariance, seed=seed + d)
        return adjusted_rand_score(labels, model.predict(x.to_numpy()))

    return np.array(Parallel(n_jobs=n_jobs)(delayed(refit)(d) for d in range(draws)))


def candidates(x: pd.DataFrame, *, draws: int = 50, seed: int = 0, n_jobs: int = 4) -> pd.DataFrame:
    """One row per number of roles (`ROLES`) and covariance (`COVARIANCES`): the principal
    components kept, the BIC, the smallest share of rows whose main role a role is, and the
    stability (mean and 5th percentile of the adjusted Rand index over `draws` refits).
    """
    rows = []
    for roles in ROLES:
        for covariance in COVARIANCES:
            model = fit(x, roles, covariance, seed=seed)
            labels = model.predict(x.to_numpy())
            ari = stability(x, labels, roles, covariance, draws=draws, seed=seed, n_jobs=n_jobs)
            rows.append({
                "roles": roles, "covariance": covariance, "components": model[1].n_components_,
                "bic": bic(model, x),
                "smallest": np.bincount(labels, minlength=roles).min() / len(x),
                "stability": ari.mean(), "stability_low": np.percentile(ari, 5),
            })  # fmt: skip
    return pd.DataFrame(rows)


def choose(table: pd.DataFrame) -> pd.Series | None:
    """The candidate with the lowest BIC among those whose every role holds `MIN_SHARE` of the
    rows and whose stability is `MIN_STABILITY` or more; None if no candidate qualifies.
    """
    ok = table[(table.smallest >= MIN_SHARE) & (table.stability >= MIN_STABILITY)]
    return None if ok.empty else ok.loc[ok.bic.idxmin()]


def _eigenvalues(z: np.ndarray) -> np.ndarray:
    return np.sort(np.linalg.eigvalsh(np.corrcoef(z, rowvar=False)))[::-1]


def parallel_analysis(x: pd.DataFrame, *, draws: int = 200, seed: int = 0) -> pd.DataFrame:
    """The eigenvalues of the descriptors' correlation matrix against the `QUANTILE` of those of
    `draws` shuffles, each descriptor shuffled on its own (Horn, 1965). One row per component.
    """
    rng = np.random.default_rng(seed)
    z = x.to_numpy()
    shuffled = [
        _eigenvalues(np.column_stack([rng.permutation(c) for c in z.T])) for _ in range(draws)
    ]
    return pd.DataFrame(
        {"observed": _eigenvalues(z), "threshold": np.quantile(shuffled, QUANTILE, axis=0)},
        index=pd.RangeIndex(1, z.shape[1] + 1, name="component"),
    )


def retained(table: pd.DataFrame) -> int:
    """The leading components of `parallel_analysis` that stand above shuffled data."""
    return int((table.observed > table.threshold).cummin().sum())


def varimax(loadings: np.ndarray, *, max_iter: int = 500, tol: float = 1e-10) -> np.ndarray:
    """The orthogonal rotation that maximises the variance of the squared loadings, with rows
    normalised by their communality (Kaiser, 1958).
    """
    norm = np.sqrt((loadings**2).sum(axis=1, keepdims=True))
    a = loadings / norm
    p, k = a.shape
    rotation, objective = np.eye(k), 0.0
    for _ in range(max_iter):
        b = a @ rotation
        u, s, vt = np.linalg.svd(a.T @ (b**3 - b * (b**2).sum(axis=0) / p))
        rotation = u @ vt
        if s.sum() <= objective * (1 + tol):
            break
        objective = s.sum()
    return rotation


@dataclass(frozen=True)
class Axes:
    """Style axes: varimax-rotated principal components of standardised descriptors."""

    mean: pd.Series  # each descriptor's mean over the rows fitted
    scale: pd.Series  # and its standard deviation
    loadings: pd.DataFrame  # descriptors x axes: each descriptor's correlation with each axis
    weights: pd.DataFrame  # descriptors x axes: standardised descriptors to scores

    def scores(self, values: pd.DataFrame) -> pd.DataFrame:
        """Each row's score on each axis (mean 0, standard deviation 1 over the rows fitted); a
        missing descriptor counts as the mean.
        """
        z = (values[self.mean.index] - self.mean) / self.scale
        return z.fillna(0.0) @ self.weights


def fit_axes(x: pd.DataFrame, n: int) -> Axes:
    """`n` style axes from the rows of `x` (players x descriptors): the leading principal
    components of the standardised descriptors, varimax-rotated, each signed so that its largest
    loading is positive and numbered by the variation it holds, largest first.
    """
    mean, scale = x.mean(), x.std(ddof=0)
    values, vectors = np.linalg.eigh(np.corrcoef(x.to_numpy(), rowvar=False))
    top = np.argsort(values)[::-1][:n]
    values, vectors = values[top], vectors[:, top]
    rotation = varimax(vectors * np.sqrt(values)) if n > 1 else np.eye(1)
    loadings = (vectors * np.sqrt(values)) @ rotation
    weights = (vectors / np.sqrt(values)) @ rotation
    sign = np.sign(loadings[np.abs(loadings).argmax(axis=0), range(n)])
    order = np.argsort(-(loadings**2).sum(axis=0), kind="stable")
    axes = pd.RangeIndex(1, n + 1, name="axis")
    return Axes(
        mean=mean,
        scale=scale,
        loadings=pd.DataFrame((loadings * sign)[:, order], index=x.columns, columns=axes),
        weights=pd.DataFrame((weights * sign)[:, order], index=x.columns, columns=axes),
    )


def congruence(x: pd.DataFrame, axes: Axes, *, draws: int = HALVES, seed: int = 0,
               n_jobs: int = 4) -> pd.DataFrame:  # fmt: skip
    """Tucker's congruence between each axis's loadings and those of the matching axis fitted on
    a random half of the rows, one row per draw. Axes are matched by the assignment with the
    largest total congruence, regardless of sign.
    """
    rng = np.random.default_rng(seed)
    halves = [rng.choice(len(x), len(x) // 2, replace=False) for _ in range(draws)]
    a = axes.loadings.to_numpy()
    n = a.shape[1]

    def match(half: np.ndarray) -> np.ndarray:
        b = fit_axes(x.iloc[half], n).loadings.to_numpy()
        phi = np.abs(a.T @ b) / np.outer(np.linalg.norm(a, axis=0), np.linalg.norm(b, axis=0))
        rows, cols = linear_sum_assignment(-phi)
        return phi[rows, cols]

    out = Parallel(n_jobs=n_jobs)(delayed(match)(h) for h in halves)
    return pd.DataFrame(out, columns=axes.loadings.columns)


@dataclass(frozen=True)
class Style:
    values: pd.DataFrame  # one row per player and descriptor of their group
    descriptors: pd.DataFrame  # one row per comparison group and descriptor
    axes: pd.DataFrame  # one row per comparison group and axis
    loadings: pd.DataFrame  # one row per comparison group, axis and descriptor
    scores: pd.DataFrame  # one row per player and axis
    recording: pd.DataFrame  # one row per comparison group, recording statistic and context


def axes_of(descriptors: pd.DataFrame, loadings: pd.DataFrame, group: str) -> Axes:
    """A group's `Axes` back from the processed style tables (`style_descriptors`,
    `style_loadings`)."""
    d = descriptors[descriptors.comparison_group == group].sort_values("order")
    w = loadings[loadings.comparison_group == group]
    wide = {c: w.pivot(index="descriptor", columns="axis", values=c).loc[d.descriptor]
            for c in ("loading", "weight")}  # fmt: skip
    return Axes(
        mean=d.set_index("descriptor").regulars_mean,
        scale=d.set_index("descriptor").regulars_sd,
        loadings=wide["loading"].rename_axis(index=None),
        weights=wide["weight"].rename_axis(index=None),
    )


def style_matches(con: duckdb.DuckDBPyConnection, cfg: Config, group: pd.Series) -> pd.DataFrame:
    """One row per player of `group` (player id -> comparison group) and pool match they spent
    `style.IN_GROUP` or more of in a position of their group: the sums behind the descriptors
    (`style.SUMMED`), the minutes and the time with and without the ball, as recorded."""
    rows = (
        player_match_counts(con)
        .merge(player_match_style(con), on=KEYS, validate="1:1")
        .merge(player_possession(con), on=KEYS, validate="1:1")
        .merge(value_sums(con, cfg, {"completion_above_expected"}), on=KEYS, how="left")
        .merge(group_share(con, cfg, group), on=KEYS, validate="1:1")
    )
    rows = rows[rows.player_id.isin(group.index) & (rows.group_share >= IN_GROUP)]
    return rows.fillna(dict.fromkeys(XPASS_SUMS.values(), 0.0))


def place(sums: pd.DataFrame, group: str, table: pd.DataFrame) -> pd.DataFrame:
    """The style descriptors of `group` from any sums of a player's matches in the group's
    positions, on the season's terms.

    `sums` has the `style.SUMMED` columns, the minutes and the `profiles.POSSESSION` columns,
    counts already rescaled for their recording context (`profiles.rescale`, with
    `style_recording`), one row per set of matches; `table` is `style_descriptors`. The
    descriptors on an even share of possession by the group's slopes, pulled towards the season's
    group mean with the season's K (`profiles.towards`); one column per descriptor of the group, in
    order. Scores follow from `axes_of(...).scores`.
    """
    d = table[table.comparison_group == group].sort_values("order").set_index("descriptor")
    slopes = d.slope.rename(group).to_frame().T
    values = adjust(descriptors(sums)[d.index], own_share(sums), pd.Series(group, index=sums.index),
                    slopes)  # fmt: skip
    return towards(values, sums.minutes, d.group_mean, d.k)


def build_style(con: duckdb.DuckDBPyConnection, cfg: Config, players: pd.DataFrame) -> Style:
    """Every player's style, from the processed tables: the descriptors of their group
    (`roles.descriptors` in the config) on an even share of possession and shrunk, and their
    scores on the group's `roles.axes` axes, fitted on the group's regulars (`cfg.compared.minutes`
    or more in the group's positions).

    `players` has `player_id`, `comparison_group` and `league` (`profiles.Profiles.players`).
    """
    players = players.set_index("player_id")
    group = players.comparison_group
    rows = style_matches(con, cfg, group)
    context = recording_context(rows, cfg)
    factors = recording_factors(rows, group, context, cfg.recording.statistics)
    rows = rescale(rows, group, context, factors)
    columns = [*SUMMED, "minutes", *POSSESSION]
    season = rows.groupby("player_id")[columns].sum().loc[group.index]
    minutes = season.minutes  # in the group's positions
    recorded = descriptors(season)
    regulars = group[minutes >= cfg.compared.minutes]
    slopes = possession_slopes(rows, regulars)
    adjusted = adjust(recorded, own_share(season), group, slopes)
    long_season = group[minutes >= 2 * RELIABILITY_MINUTES]

    values, statistics, axes_rows, loadings, scores = [], [], [], [], []
    for g, names in cfg.roles.descriptors.items():
        names, ids = list(names), group.index[group == g].sort_values()
        halves = long_season.index[long_season == g]

        def even(s: pd.DataFrame, g: str = g) -> pd.DataFrame:
            return adjust(descriptors(s), own_share(s), pd.Series(g, index=s.index), slopes)

        curve = split_half_reliability(
            rows[rows.player_id.isin(halves)], players.league.loc[halves], names,
            [RELIABILITY_MINUTES], columns=columns, rate_fn=even,
        )  # fmt: skip
        r = curve[names].mean().to_numpy()
        stats = pd.DataFrame({
            "comparison_group": g, "statistic": names, "order": range(len(names)),
            "slope": slopes.loc[g, names].to_numpy(), "reliability": r,
            "k": RELIABILITY_MINUTES * (1 - r) / r,
        })  # fmt: skip
        long = shrink_values(
            pd.DataFrame({
                "player_id": np.repeat(ids, len(names)), "comparison_group": g,
                "statistic": np.tile(names, len(ids)),
                "minutes": np.repeat(minutes.loc[ids].to_numpy(), len(names)),
                "recorded": recorded.loc[ids, names].to_numpy().ravel(),
                "adjusted": adjusted.loc[ids, names].to_numpy().ravel(),
            }),
            stats,
        )  # fmt: skip
        shrunk = long.pivot(index="player_id", columns="statistic", values="shrunk").loc[ids, names]
        axes = fit_axes(shrunk.loc[shrunk.index.isin(regulars.index)], cfg.roles.axes[g])
        n = axes.loadings.shape[1]
        stats["group_mean"] = long.groupby("statistic").group_mean.first().loc[names].to_numpy()
        stats["regulars_mean"] = axes.mean.loc[names].to_numpy()
        stats["regulars_sd"] = axes.scale.loc[names].to_numpy()
        low, high = zip(*cfg.roles.names[g], strict=True)
        axes_rows.append(pd.DataFrame({
            "comparison_group": g, "axis": axes.loadings.columns, "low": low, "high": high,
            "variation": ((axes.loadings**2).sum() / len(names)).to_numpy(),
        }))  # fmt: skip
        loadings.append(pd.DataFrame({
            "comparison_group": g, "axis": np.repeat(axes.loadings.columns, len(names)),
            "descriptor": np.tile(names, n),
            "loading": axes.loadings.loc[names].to_numpy().T.ravel(),
            "weight": axes.weights.loc[names].to_numpy().T.ravel(),
        }))  # fmt: skip
        scores.append(pd.DataFrame({
            "player_id": np.repeat(ids, n), "comparison_group": g,
            "minutes": np.repeat(minutes.loc[ids].to_numpy(), n),
            "axis": np.tile(axes.loadings.columns, len(ids)),
            "score": axes.scores(shrunk).to_numpy().ravel(),
        }))  # fmt: skip
        values.append(long)
        statistics.append(stats)

    descriptor = {"statistic": "descriptor"}
    return Style(
        values=pd.concat(values, ignore_index=True).rename(columns=descriptor)[
            ["player_id", "comparison_group", "descriptor", "minutes", "recorded", "adjusted",
             "group_mean", "weight", "shrunk"]
        ],
        descriptors=pd.concat(statistics, ignore_index=True).rename(columns=descriptor),
        axes=pd.concat(axes_rows, ignore_index=True),
        loadings=pd.concat(loadings, ignore_index=True),
        scores=pd.concat(scores, ignore_index=True),
        recording=factors.sort_values(["statistic", "context"]).sort_values(
            "comparison_group", key=lambda c: c.map({g: i for i, g in enumerate(cfg.roles.axes)}),
            kind="stable",
        ).reset_index(drop=True),
    )  # fmt: skip

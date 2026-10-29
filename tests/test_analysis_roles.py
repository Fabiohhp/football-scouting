import numpy as np
import pandas as pd
import pytest

from football_scouting.analysis import roles
from football_scouting.analysis.roles import (
    candidates,
    choose,
    congruence,
    fit,
    fit_axes,
    membership,
    parallel_analysis,
    retained,
    shrink,
    varimax,
)


def factors(n: int = 300, seed: int = 0) -> pd.DataFrame:
    """Eight descriptors: two latent factors behind three each, two of pure noise."""
    rng = np.random.default_rng(seed)
    f = rng.normal(size=(n, 2))
    x = np.column_stack([f[:, [0]] + 0.5 * rng.normal(size=(n, 3)),
                         f[:, [1]] + 0.5 * rng.normal(size=(n, 3)),
                         rng.normal(size=(n, 2))])  # fmt: skip
    return pd.DataFrame(x, columns=[f"d{i}" for i in range(8)])


def test_shrink_pulls_values_towards_the_group_mean_by_minutes():
    values = pd.DataFrame({"a": [0.0, 10.0, np.nan, 3.0]}, index=[1, 2, 3, 4])
    minutes = pd.Series([900.0, 900.0, 900.0, 900.0], index=values.index)
    groups = pd.Series(["CB", "CB", "CB", "FB"], index=values.index)
    k = pd.DataFrame({"CB": [900.0], "FB": [900.0]}, index=["a"])
    out = shrink(values, minutes, groups, k)
    # Weight 900 / (900 + 900); a missing value takes the group's mean, 5.
    assert out.a.tolist() == pytest.approx([2.5, 7.5, 5.0, 3.0])


def test_mixture_finds_separated_roles_and_numbers_them_by_height(monkeypatch):
    rng = np.random.default_rng(1)
    heights = np.repeat([70.0, 30.0, 50.0], 60)
    x = pd.DataFrame({
        "touch_height": heights + rng.normal(0, 2, 180),
        "touch_width": np.repeat([10.0, 25.0, 15.0], 60) + rng.normal(0, 2, 180),
        "pass_share": np.repeat([0.4, 0.6, 0.5], 60) + rng.normal(0, 0.02, 180),
    })  # fmt: skip
    monkeypatch.setattr(roles, "ROLES", range(2, 5))
    monkeypatch.setattr(roles, "COVARIANCES", ("diag",))
    table = candidates(x, draws=5, n_jobs=1)
    best = choose(table)
    assert best.roles == 3 and best.stability > 0.95
    p = membership(fit(x, 3, "diag"), x)
    main = p.idxmax(axis=1)
    assert (main[heights == 30] == 1).all() and (main[heights == 70] == 3).all()
    assert p.sum(axis=1).to_numpy() == pytest.approx(1)
    # No candidate qualifies when every role must hold more than any role can.
    monkeypatch.setattr(roles, "MIN_SHARE", 0.6)
    assert choose(table) is None


def test_parallel_analysis_keeps_the_components_above_shuffled_data():
    table = parallel_analysis(factors(), draws=50)
    assert retained(table) == 2
    assert (table.observed.diff().dropna() <= 0).all()


def varimax_criterion(loadings: np.ndarray) -> float:
    a = loadings / np.sqrt((loadings**2).sum(axis=1, keepdims=True))
    return ((a**4).mean(axis=0) - (a**2).mean(axis=0) ** 2).sum()


def turn(degrees: float) -> np.ndarray:
    t = np.deg2rad(degrees)
    return np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])


def test_varimax_finds_the_best_rotation():
    simple = np.array([[0.8, 0.1], [0.7, 0], [0.9, -0.1], [0.1, 0.8], [0, 0.6], [0.05, 0.7]])
    rotated = simple @ turn(30)
    r = varimax(rotated)
    assert r @ r.T == pytest.approx(np.eye(2))
    best = max(varimax_criterion(rotated @ turn(d)) for d in np.linspace(0, 90, 9001))
    assert varimax_criterion(rotated @ r) >= best - 1e-9
    assert rotated @ r == pytest.approx(simple, abs=0.15)  # back to simple structure


def test_axes_scores_are_standardised_uncorrelated_and_signed():
    x = factors()
    axes = fit_axes(x, 2)
    s = axes.scores(x)
    assert s.mean().to_numpy() == pytest.approx(0, abs=1e-12)
    assert s.std(ddof=0).to_numpy() == pytest.approx(1)
    assert np.corrcoef(s.T)[0, 1] == pytest.approx(0, abs=1e-12)
    # Loadings are the descriptors' correlations with the axes; the largest is positive.
    corr = pd.concat([x, s.add_prefix("axis")], axis=1).corr().loc[x.columns, ["axis1", "axis2"]]
    assert corr.to_numpy() == pytest.approx(axes.loadings.to_numpy())
    assert (axes.loadings.max() == axes.loadings.abs().max()).all()
    assert (axes.loadings**2).sum().is_monotonic_decreasing
    # Each axis gathers one factor's three descriptors, the noise loads on neither.
    tops = {frozenset(axes.loadings[a].abs().nlargest(3).index) for a in axes.loadings.columns}
    assert tops == {frozenset(["d0", "d1", "d2"]), frozenset(["d3", "d4", "d5"])}
    assert (axes.loadings.loc[["d6", "d7"]].abs() < 0.2).all().all()
    # A missing descriptor scores as its mean.
    row = x.iloc[[0]].copy()
    filled = row.assign(d0=axes.mean.d0)
    row.loc[:, "d0"] = np.nan
    assert axes.scores(row).to_numpy() == pytest.approx(axes.scores(filled).to_numpy())


def test_clear_axes_are_found_again_in_halves():
    x = factors()
    c = congruence(x, fit_axes(x, 2), draws=10)
    assert c.shape == (10, 2) and (c > 0.95).all().all()

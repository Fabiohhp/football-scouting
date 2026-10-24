"""The processed profiles follow their rules. Run with `make dq`."""

import numpy as np
import pytest

from football_scouting.analysis.players import pool_player_seasons
from football_scouting.analysis.possession import REFERENCE_SHARE
from football_scouting.analysis.profiles import compared_players
from football_scouting.config import load_config
from football_scouting.model.database import connect_readonly, database_path

pytestmark = pytest.mark.data
CFG = load_config()


@pytest.fixture(scope="module")
def con():
    if not database_path(CFG).exists():
        pytest.skip("database not built (run `make model`)")
    return connect_readonly(CFG)


@pytest.fixture(scope="module")
def values(con):
    return con.sql(
        'SELECT v.*, s."order", s.k, s.side, s.elasticity, s.slope, s.recording_context, p.possession '
        "FROM profile_values v JOIN profile_statistics s USING (comparison_group, statistic) "
        "JOIN profile_players p USING (player_id, comparison_group)"
    ).df()


def test_every_compared_player_has_their_groups_statistics(con, values):
    pool = pool_player_seasons(con, CFG, age_on=CFG.backtest.market_view)
    players = con.sql("SELECT * FROM profile_players").df()
    assert sorted(players.player_id) == sorted(compared_players(pool, CFG).player_id)
    assert len(values) == sum(len(CFG.profiles[g]) for g in players.comparison_group)
    in_order = values.sort_values(["player_id", "order"])
    for (_, group), stats in in_order.groupby(["player_id", "comparison_group"]).statistic:
        assert tuple(stats) == CFG.profiles[group]


def test_shrunk_values_lie_between_the_player_and_the_group(values):
    known = values[values.adjusted.notna()]
    assert np.allclose(known.weight, known.minutes / (known.minutes + known.k))
    low = np.minimum(known.adjusted, known.group_mean) - 1e-12
    high = np.maximum(known.adjusted, known.group_mean) + 1e-12
    assert known.shrunk.between(low, high).all()
    missing = values[values.adjusted.isna()]
    assert (missing.weight == 0).all() and np.allclose(missing.shrunk, missing.group_mean)


def test_adjusted_follows_the_elasticity_or_the_slope(values):
    """Per-90 statistics outside recording context: rate x (0.5 / share on its side) ^ beta;
    completion above expected: less slope x (share - 0.5)."""
    d = values[values.elasticity.notna() & ~values.recording_context]
    share = np.where(d.side == "with", d.possession, 1 - d.possession)
    assert np.allclose(d.adjusted, d.recorded * (REFERENCE_SHARE / share) ** d.elasticity)
    s = values[values.slope.notna()]
    assert set(s.statistic) == {"completion_above_expected"} and (s.side == "with").all()
    assert np.allclose(s.adjusted, s.recorded - s.slope * (s.possession - REFERENCE_SHARE))
    ratios = values[values.side == "ratio"]
    assert np.allclose(ratios.adjusted, ratios.recorded, equal_nan=True)


def test_percentiles_run_up_to_100_for_the_best(values):
    per_stat = values.groupby(["comparison_group", "statistic"]).percentile
    assert (per_stat.max() == 100).all() and (per_stat.min() > 0).all()

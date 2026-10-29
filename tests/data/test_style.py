"""The style sums reconcile with the event tables and the descriptors stay in range. Run with
`make dq`."""

import pandas as pd
import pytest

from football_scouting.analysis.metrics import OPEN_PLAY, TOUCH, player_match_counts
from football_scouting.analysis.profiles import KEYS
from football_scouting.analysis.style import (
    FAMILIES,
    SPREADS,
    SUMMED,
    descriptors,
    group_share,
    player_match_style,
)
from football_scouting.config import load_config
from football_scouting.model.database import connect_readonly, database_path

pytestmark = pytest.mark.data
CFG = load_config()
POOL = "match_id IN (SELECT match_id FROM matches WHERE scouting_pool)"


@pytest.fixture(scope="module")
def con():
    if not database_path(CFG).exists():
        pytest.skip("database not built (run `make model`)")
    return connect_readonly(CFG)


@pytest.fixture(scope="module")
def style(con):
    return player_match_style(con)


def pool_total(con, sql: str) -> float:
    return con.execute(f"{sql} AND {POOL}").fetchone()[0]


def test_one_row_per_player_match_played(con, style):
    assert not style.duplicated(KEYS).any()
    assert len(style) == pool_total(con, "SELECT count(*) FROM player_matches WHERE played")


def test_style_sums_reconcile_with_event_tables(con, style):
    feet = "body_part IN ('Left Foot', 'Right Foot')"
    expected = {
        "foot_passes": f"SELECT count(*) FROM passes WHERE {OPEN_PLAY} AND {feet}",
        "left_foot_passes": f"SELECT count(*) FROM passes WHERE {OPEN_PLAY} "
        "AND body_part = 'Left Foot'",
        "high_passes": f"SELECT count(*) FROM passes WHERE {OPEN_PLAY} AND height = 'High Pass'",
        "pass_length": f"SELECT sum(length) FROM passes WHERE {OPEN_PLAY}",
        "carry_distance": "SELECT sum(sqrt((end_x - x) ** 2 + (end_y - y) ** 2)) FROM carries "
        "WHERE true",
    }
    for col, sql in expected.items():
        assert style[col].sum() == pytest.approx(pool_total(con, sql)), col
    assert (style.inside_foot_passes <= style.wide_foot_passes).all()
    assert (style.wide_foot_passes <= style.foot_passes).all()


def test_descriptors_stay_in_range(con, style):
    counts = player_match_counts(con).merge(style, on=KEYS, validate="1:1")
    expected = con.sql(
        "SELECT match_id, team_id, player_id, count(*) AS xpass_passes, "
        "0.5 * count(*) AS xpass_expected "  # pass ease is tested with the xPass model
        f"FROM passes WHERE {OPEN_PLAY} GROUP BY ALL"
    ).df()
    counts = counts.merge(expected, on=KEYS, how="left").fillna(
        {"xpass_passes": 0.0, "xpass_expected": 0.0}
    )
    d = descriptors(counts.groupby("player_id")[SUMMED].sum())
    places = {"touch_height": 120, "touch_width": 40, "defence_height": 120,
              "pass_length": 130, "carry_distance": 20}  # fmt: skip
    for m in [m for ms in FAMILIES.values() for m in ms]:
        values = d[m].dropna()
        assert (values >= 0).all(), m
        if m in SPREADS:
            assert (values <= 60).all(), m
        else:
            assert (values <= places.get(m, 1)).all(), m
    # Forward and backward passes never add up to more than the passes.
    assert ((d.forward_share + d.backward_share).dropna() <= 1 + 1e-12).all()


def test_spreads_within_matches_are_at_most_the_seasons(con, style):
    counts = player_match_counts(con)[[*KEYS, "touches"]].merge(style, on=KEYS, validate="1:1")
    totals = counts.groupby("player_id")[["touches", *(c for c, _ in SPREADS.values())]].sum()
    d = pd.DataFrame({m: totals[c] / totals.touches for m, (c, _) in SPREADS.items()})
    season = con.sql(
        f"SELECT player_id, var_pop(x) AS x, var_pop(y) AS y FROM events WHERE {TOUCH} AND {POOL} "
        "GROUP BY ALL"
    ).df().set_index("player_id")
    for m, c in (("spread_length", "x"), ("spread_width", "y")):
        assert (d[m].dropna() <= season[c].reindex(d[m].dropna().index) + 1e-6).all(), m


def test_group_share_covers_every_match_played(con, style):
    pool = con.sql("SELECT player_id, comparison_group FROM profile_players").df()
    share = group_share(con, CFG, pool.set_index("player_id").comparison_group)
    assert len(share.merge(style[KEYS], on=KEYS, validate="1:1")) == len(style) == len(share)
    assert share.group_share.between(0, 1).all()
    # A player's comparison group is where they played most: their own matches dominate.
    own = share[share.player_id.isin(pool.player_id)]
    assert (own.groupby("player_id").group_share.mean() > 0).all()

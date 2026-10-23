"""The expected pass completion inputs reconcile with the event tables. Run with `make dq`."""

import numpy as np
import pytest

from football_scouting.analysis.metrics import player_match_counts
from football_scouting.analysis.xpass import (
    CATEGORICAL,
    FEATURES,
    KEYS,
    load_passes,
    next_opponent_action,
)
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
def passes(con):
    return load_passes(con)


def test_passes_add_up_to_the_counts_of_players_who_played(con, passes):
    counts = player_match_counts(con).set_index(KEYS)
    sums = passes.groupby(KEYS).agg(n=("completed", "size"), completed=("completed", "sum"))
    assert sums.index.isin(counts.index).all()
    counts = counts.loc[sums.index]
    assert (sums.completed == counts.passes_completed).all()
    # Open-play passes in the counts include injury clearances, never completed.
    clearances = con.sql(
        "SELECT count(*) FROM passes WHERE outcome = 'Injury Clearance' AND match_id IN "
        "(SELECT match_id FROM matches WHERE scouting_pool) AND (pass_type IS NULL OR "
        "pass_type IN ('Recovery', 'Interception'))"
    ).fetchone()[0]
    assert (counts.passes >= sums.n).all()
    assert (counts.passes - sums.n).sum() == clearances


def test_features_are_complete(passes):
    assert passes[list(FEATURES)].notna().all().all()
    for c in CATEGORICAL:
        assert passes[c].dtype == "category"


def test_an_incomplete_pass_ends_where_the_opponent_cut_it_out(con):
    nxt = next_opponent_action(con)
    soon = nxt[(nxt.gap <= 3) & ~nxt.completed]
    at_end = np.hypot(soon.opp_x - soon.end_x, soon.opp_y - soon.end_y) < 2
    assert len(soon) > 100_000 and at_end.mean() > 0.95
    done = nxt[(nxt.gap <= 3) & nxt.completed]
    assert (np.hypot(done.opp_x - done.end_x, done.opp_y - done.end_y) < 2).mean() < 0.1


def test_a_switch_is_flagged_only_when_the_ball_crossed_40_yards(passes):
    switches = passes[passes.switch == 1]
    assert (~switches.completed).sum() > 5_000
    assert (abs(switches.end_y - switches.y) >= 40).all()

"""The expected threat inputs reconcile with the event tables. Run with `make dq`."""

import numpy as np
import pytest

from football_scouting.analysis.xt import (
    LENGTH,
    WIDTH,
    chain_outcomes,
    fit,
    load_actions,
    move_credit,
    player_match_credit,
    zones,
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
def actions(con):
    a = load_actions(con, losses=True)
    types = con.sql(
        "SELECT match_id, event_index, type AS event_type FROM events "
        "WHERE match_id IN (SELECT match_id FROM matches WHERE scouting_pool)"
    ).df()
    return a.merge(types, on=["match_id", "event_index"], how="left", validate="one_to_one")


def test_actions_are_pool_events_of_their_kind(actions):
    kinds = {
        "move": {"Pass", "Carry"},
        "shot": {"Shot"},
        "loss": {"Dispossessed", "Miscontrol", "Dribble"},
    }
    for kind, rows in actions.groupby("kind"):
        assert set(rows.event_type) == kinds[kind]
    assert (actions.type == actions.event_type).all()
    shots = actions[actions.kind == "shot"]
    assert shots.xg.between(0, 1).all() and shots.goal.notna().all()
    moves = actions[actions.kind == "move"]
    assert moves[["end_x", "end_y"]].notna().all().all() and moves.success.notna().all()
    assert actions.success[actions.type == "Carry"].all()


def test_chain_outcomes_cover_every_action(con, actions):
    out = chain_outcomes(con)
    a = actions.merge(out, on=["match_id", "event_index", "team_id"], how="left")
    assert a.outcome.notna().all() and a.outcome.between(0, 1).all()
    shots = a[a.kind == "shot"]
    assert np.allclose(shots.outcome, shots.xg)  # a shot's chain ends with itself


def test_the_map_peaks_in_front_of_goal_and_mirrors_left_and_right(actions):
    xt = CFG.xt
    m = fit(actions if xt.losses else actions[actions.kind != "loss"], xt.nx, xt.ny)
    assert (m > 0).all() and (m < 1).all()
    row, col = np.unravel_index(m.argmax(), m.shape)
    assert (col + 1) * LENGTH / xt.nx > 114 and 36 <= row * WIDTH / xt.ny < 44
    weight = np.bincount(zones(actions.x, actions.y, xt.nx, xt.ny), minlength=m.size)
    weight = weight.reshape(m.shape)
    assert np.sum(weight * np.abs(m - m[::-1])) / np.sum(weight * m) < 0.1


def test_player_credit_adds_up_to_the_moves_of_players_who_played(con, actions):
    xt = CFG.xt
    m = fit(actions, xt.nx, xt.ny)
    sums = player_match_credit(m, actions)
    played = con.sql(
        "SELECT match_id, team_id, player_id FROM player_matches "
        "WHERE played AND match_id IN (SELECT match_id FROM matches WHERE scouting_pool)"
    ).df()
    keys = ["match_id", "team_id", "player_id"]
    assert len(sums.merge(played, on=keys)) == len(sums) == len(sums.drop_duplicates(keys))
    gain = move_credit(m, actions)
    assert sums.passes_net.sum() + sums.carries_net.sum() == pytest.approx(np.nansum(gain))
    assert sums.passes_gained.sum() + sums.carries_gained.sum() == pytest.approx(
        np.nansum(np.maximum(gain, 0))
    )
    assert (sums.passes_failed >= 0).all() and (sums.lost >= 0).all()

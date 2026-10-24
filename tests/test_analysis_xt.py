import numpy as np
import pandas as pd
import pytest

from football_scouting.analysis.xt import (
    _chain_outcome,
    credit_rates,
    fit,
    move_credit,
    player_match_credit,
    total_credit,
    value_at,
    zones,
)


def test_zones_cover_the_pitch():
    x = np.array([0.1, 59.9, 60.0, 120.0, 121.0, -1.0])
    y = np.array([0.1, 39.9, 40.0, 80.0, 80.5, 0.0])
    # 2 zones along the length, 2 across: index = row across * 2 + column along
    assert zones(x, y, 2, 2).tolist() == [0, 0, 3, 3, 3, 0]
    assert zones([7.4, 7.5], [6.6, 6.7], 16, 12).tolist() == [0, 17]


def actions(losses=False):
    """Two zones along the length (0 below x = 60, 1 above), worked out by hand in the tests."""
    rows = [
        ("shot", 30, 40, None, None, None, 0.1, False),
        ("move", 30, 40, 90, 40, True, None, None),
        ("move", 30, 40, 90, 40, True, None, None),
        ("move", 30, 40, 90, 40, False, None, None),
        ("shot", 90, 40, None, None, None, 0.2, False),
        ("shot", 90, 40, None, None, None, 0.3, True),
        ("move", 90, 40, 30, 40, True, None, None),
        ("move", 90, 40, 30, 40, False, None, None),
    ]
    if losses:
        rows.append(("loss", 90, 40, None, None, False, None, None))
    a = pd.DataFrame(rows, columns=["kind", "x", "y", "end_x", "end_y", "success", "xg", "goal"])
    return a.astype({"success": "boolean", "goal": "boolean"})


def test_fit_solves_the_chain():
    # xT0 = 0.1/4 + 2/4 xT1 and xT1 = 0.5/4 + 1/4 xT0
    assert fit(actions(), 2, 1) == pytest.approx(np.array([[0.1, 0.15]]))
    # a loss in zone 1: xT1 = 0.5/5 + 1/5 xT0
    assert fit(actions(losses=True), 2, 1) == pytest.approx(np.array([[0.075 / 0.9, 0.35 / 3]]))
    # one goal in zone 1: xT1 = 1/4 + 1/4 xT0, xT0 = 2/4 xT1
    assert fit(actions(), 2, 1, shot_value="goal") == pytest.approx(np.array([[1 / 7, 2 / 7]]))


def test_moves_are_credited_with_the_xt_they_gain():
    xt = np.array([[0.1, 0.15]])
    a = actions()
    assert value_at(xt, a.x, a.y).tolist() == [0.1] * 4 + [0.15] * 4
    credit = move_credit(xt, a)
    assert credit[[1, 2, 6]] == pytest.approx([0.05, 0.05, -0.05])
    assert np.isnan(credit[[0, 3, 4, 5, 7]]).all()  # shots and failed moves


def test_player_credit_in_three_versions():
    xt = np.array([[0.1, 0.15]])
    rows = [  # player, kind, type, x, end_x, success
        (1, "move", "Pass", 30, 90, True),  # +0.05
        (1, "move", "Pass", 90, 30, True),  # -0.05
        (1, "move", "Carry", 30, 90, True),  # +0.05
        (1, "move", "Pass", 90, 30, False),  # failed where the ball was worth 0.15
        (1, "loss", "Miscontrol", 30, None, False),  # lost where it was worth 0.1
        (1, "shot", "Shot", 90, None, None),
        (2, "move", "Carry", 90, 30, True),  # -0.05
    ]
    a = pd.DataFrame(rows, columns=["player_id", "kind", "type", "x", "end_x", "success"])
    a = a.assign(match_id=7, team_id=3, y=40.0, end_y=a.end_x.notna() * 40.0)
    a = a.astype({"success": "boolean"})
    sums = player_match_credit(xt, a).set_index("player_id")
    assert sums.loc[
        1, ["passes_gained", "carries_gained", "passes_net", "carries_net"]
    ].tolist() == (pytest.approx([0.05, 0.05, 0.0, 0.05]))
    assert sums.loc[1, ["passes_failed", "lost"]].tolist() == pytest.approx([0.15, 0.1])
    assert sums.loc[2, ["carries_gained", "carries_net"]].tolist() == pytest.approx([0, -0.05])
    r = credit_rates(sums.assign(minutes=45.0)).loc[1]  # per 90: twice the sums
    assert r[["gained", "net", "charged"]].tolist() == pytest.approx([0.2, 0.1, -0.4])
    assert r[["charged_passes", "charged_carries"]].tolist() == pytest.approx([-0.3, -0.1])
    totals = [total_credit(sums, v).loc[1] for v in ("gained", "net", "charged")]
    assert totals == pytest.approx([0.1, 0.05, -0.2])  # the sums behind the rates


def test_chain_outcome_is_the_next_open_play_shot_before_the_chain_breaks():
    rows = [  # match, period, team, set piece, xG of an open-play shot, expected outcome
        (1, 1, "A", False, None, 0.0),  # the opponent acts next
        (1, 1, "B", False, None, 0.0),
        (1, 1, "A", False, None, 0.2),
        (1, 1, "A", False, 0.2, 0.2),
        (1, 1, "A", False, 0.1, 0.1),  # a rebound: its own shot
        (1, 1, "A", False, None, 0.0),  # a set piece next
        (1, 1, "A", True, None, 0.3),
        (1, 1, "A", False, 0.3, 0.3),
        (1, 1, "A", False, None, 0.0),  # the half ends
        (1, 2, "A", False, 0.4, 0.4),
        (2, 1, "A", False, None, 0.6),  # another match, same team id
        (2, 1, "A", False, 0.6, 0.6),
    ]
    ev = pd.DataFrame(rows, columns=["match_id", "period", "team_id", "set_piece", "xg", "want"])
    assert _chain_outcome(ev, "xg") == pytest.approx(ev.want.to_numpy())

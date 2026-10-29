import duckdb
import numpy as np
import pandas as pd
import pytest

from football_scouting.analysis.style import (
    FAMILIES,
    LABELS,
    NAMES,
    RATIOS,
    SPREADS,
    SUMMED,
    adjust,
    descriptors,
    group_share,
    possession_slopes,
    touch_map,
    weights,
)
from football_scouting.config import load_config


def sums(**columns) -> pd.DataFrame:
    """Summed rows with every `SUMMED` column, 0 unless given."""
    n = len(next(iter(columns.values())))
    return pd.DataFrame({c: columns.get(c, np.zeros(n)) for c in SUMMED}, dtype=float)


def test_every_descriptor_has_a_family_and_a_label():
    assert sorted(NAMES) == sorted([*RATIOS, *SPREADS]) == sorted(LABELS)
    assert len(NAMES) == len(set(NAMES)) == sum(len(ms) for ms in FAMILIES.values())


def test_descriptors_are_shares_and_places():
    s = sums(
        touches=[100, 0],
        sum_x=[6000, 0],
        sum_width=[1500, 0],
        passes=[40, 0],
        crosses=[4, 0],
        long_passes=[10, 0],
        left_foot_passes=[9, 0],
        foot_passes=[36, 0],
    )
    d = descriptors(s)
    assert d.loc[0, ["touch_height", "touch_width", "pass_share"]].tolist() == [60, 15, 0.4]
    assert d.loc[0, ["cross_share", "long_share", "left_foot_share"]].tolist() == [0.1, 0.25, 0.25]
    assert d.loc[1].isna().all()  # no touch, no pass: nothing to describe


def test_spreads_are_standard_deviations_within_matches():
    # Two matches summed: touches at x = 10 and 30, then at 70 and 90 (sd 10 within each, 32
    # over both); at y = 20 and 60 in both (sd 20).
    s = sums(touches=[4], sum_x=[200], within_x=[200 + 200], within_y=[800 + 800])
    d = descriptors(s)
    assert d.loc[0, ["spread_length", "spread_width"]].tolist() == pytest.approx([10, 20])


def test_group_share_is_the_time_in_a_position_of_the_players_group():
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE matches AS SELECT * FROM (VALUES (1, true), (2, true), (3, false)) "
        "t(match_id, scouting_pool)"
    )
    con.execute("""
        CREATE TABLE player_positions AS SELECT * FROM (VALUES
            (1, 10, 7, 'CB', 3000.0), (1, 10, 7, 'FB', 1000.0),  -- 3/4 at centre-back
            (2, 10, 7, 'FB', 5400.0),                            -- a match at full-back
            (3, 10, 7, 'CB', 5400.0),                            -- outside the pool
            (1, 20, 8, 'AM', 2000.0), (1, 20, 8, 'W', 2000.0)    -- one comparison group
        ) t(match_id, team_id, player_id, position_group, seconds)
    """)
    out = group_share(con, load_config(), pd.Series({7: "CB", 8: "AMW"}))
    out = out.set_index(["match_id", "player_id"]).group_share.sort_index()
    assert out.to_dict() == {(1, 7): 0.75, (1, 8): 1.0, (2, 7): 0.0}


def test_touch_map_mirrors_each_match_to_the_same_side():
    con = duckdb.connect()
    con.execute("""
        CREATE TABLE events AS SELECT * FROM (VALUES
            (1, 1, 7, 'Pass', 10.0, 20.0), (2, 1, 7, 'Carry', 30.0, 20.0),  -- left: mirrored
            (3, 2, 7, 'Pass', 50.0, 70.0),                                  -- right: as it is
            (4, 2, 7, 'Ball Receipt*', 60.0, 70.0),                         -- not received
            (5, 3, 7, 'Pass', 110.0, 70.0),                                 -- not in `played`
            (6, 1, 8, 'Shot', 120.0, 50.0), (7, 1, 8, 'Pass', 110.0, 10.0), -- mean y 30
            (8, 1, 8, 'Pressure', 60.0, 40.0)                               -- not a touch
        ) t(event_id, match_id, player_id, type, x, y)
    """)
    con.execute("CREATE TABLE ball_receipts AS SELECT 4 AS event_id, 'Incomplete' AS outcome")
    con.execute("CREATE TABLE ball_recoveries AS SELECT 0 AS event_id, false AS recovery_failure")
    played = pd.DataFrame({"match_id": [1, 2, 1], "player_id": [7, 7, 8]})
    out = touch_map(con, played, zone=40)  # 3 zones along the pitch, 2 across
    assert out.shape == (2, 6)
    assert out.loc[7].to_dict() == {(0, 0): 0, (0, 1): 0, (0, 2): 0, (1, 0): 2 / 3,
                                    (1, 1): 1 / 3, (1, 2): 0}  # fmt: skip
    assert out.loc[8].to_dict() == {(0, 0): 0, (0, 1): 0, (0, 2): 0.5, (1, 0): 0, (1, 1): 0,
                                    (1, 2): 0.5}  # fmt: skip


def test_defensive_shares_are_built_from_their_parts():
    # Rescaled interceptions change the denominators; the height keeps the recorded count.
    s = sums(
        tackles=[2], interceptions=[6.5], recoveries=[1], clearances=[0.5], blocks=[0],
        pressures=[10], defensive_actions=[8], sum_defence_x=[400],
    )  # fmt: skip
    d = descriptors(s)
    assert d.loc[0, "tackle_share"] == pytest.approx(2 / 10)
    assert d.loc[0, "clearance_share"] == pytest.approx(0.5 / 10)
    assert d.loc[0, "press_share"] == pytest.approx(10 / 20)
    assert d.loc[0, "defence_height"] == pytest.approx(50)
    w = weights(s)
    assert w.loc[0, ["tackle_share", "press_share", "defence_height"]].tolist() == [10, 20, 8]


def test_possession_slopes_are_within_players():
    # Players who pass more play for teams with more of the ball (a between-player slope of
    # about 1), and each passes 0.2 more per touch per unit of share from match to match.
    rng = np.random.default_rng(1)
    players = np.repeat(np.arange(30), 20)
    habit = np.linspace(0.2, 0.4, 30)[players]
    share = 0.5 + (habit - 0.3) + rng.uniform(-0.1, 0.1, len(players))
    touches = rng.integers(40, 90, len(players)).astype(float)
    pass_share = habit + 0.2 * (share - 0.5)
    rows = sums(touches=touches, passes=pass_share * touches).assign(
        player_id=players, own_seconds=share * 3000, opp_seconds=(1 - share) * 3000
    )
    groups = pd.Series("CM", index=np.arange(30))
    slopes = possession_slopes(rows, groups)
    assert slopes.loc["CM", "pass_share"] == pytest.approx(0.2)
    assert np.isnan(slopes.loc["CM", "tackle_share"])  # no defensive action at all

    values = pd.DataFrame({"pass_share": pass_share, "box_share": 0.1})
    out = adjust(values, pd.Series(share), pd.Series("CM", index=values.index), slopes)
    assert out.pass_share.to_numpy() == pytest.approx(habit)
    assert (out.box_share == 0.1).all()  # slope 0: as it was

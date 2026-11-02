import numpy as np
import pandas as pd
import pytest

from football_scouting.analysis.recruitment import (
    FIFTHS,
    candidates,
    ceiling,
    long_list,
    recommend,
    shortlist,
    team_fifths,
)


def found_rows() -> pd.DataFrame:
    """Candidates as `similarity.similar` returns them: sorted by list and distance."""
    rows = pd.DataFrame({
        "list": ["Regulars"] * 6 + ["Young"] * 3,
        "distance": [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.05, 1.15, 1.25],
        "side": ["Right", "Left", "Right", "Right", "Right", "Right", "Right", None, "Right"],
        "age": [24, 25, 29, 26, 27.9, 22, 19, 20, 21],
        "value": [5e6, 1e6, 1e6, 9e6, 2e6, 3e6, 1e6, 1e6, 1e6],
    }, index=pd.Index([10, 11, 12, 13, 14, 15, 20, 21, 22], name="player_id"))  # fmt: skip
    return rows.assign(place=rows.groupby("list").cumcount() + 1)


def test_the_candidates_are_filtered_in_turn_and_counted_step_by_step():
    found = found_rows()
    fifth = pd.Series(1, index=found.index).where(found.index != 15, FIFTHS)
    steps = candidates(found, side="Right", younger_than=28, max_value=8e6, fifth=fifth)
    assert list(steps) == [
        "Not a teammate", "On the right", "27 or under", "Within the budget",
        "Outside the strongest fifth",
    ]  # fmt: skip
    assert {k: list(v.index) for k, v in steps.items()} == {
        "Not a teammate": [10, 11, 12, 13, 14, 15, 20, 21, 22],
        "On the right": [10, 12, 13, 14, 15, 20, 22],  # no side: in the centre
        "27 or under": [10, 13, 14, 15, 20, 22],  # 27.9 is 27
        "Within the budget": [10, 14, 15, 20, 22],
        "Outside the strongest fifth": [10, 14, 20, 22],
    }
    assert "On the left" in candidates(found, side="Left", younger_than=28, max_value=8e6,
                                       fifth=fifth)  # fmt: skip


def test_each_lists_nearer_half_is_rounded_up():
    kept = found_rows().drop(columns="place")
    listed = long_list(kept)
    assert listed.place.tolist() == [1, 2, 3, 4, 5, 6, 1, 2, 3]
    # Six regulars: the nearer three; three young players: the nearer two.
    assert listed.nearer_half.tolist() == [True] * 3 + [False] * 3 + [True, True, False]
    assert "place" not in kept  # the input is left as it was


def test_the_shortlist_is_the_largest_gaps_of_the_nearer_half_and_fit_decides():
    listed = long_list(found_rows()).assign(
        gap=[0.1, 0.9, 0.5, 2.0, 0.0, 0.0, 0.7, 0.3, 3.0],
        fit=[0.9, 0.2, 0.8, 0.1, 0.0, 0.0, 0.8, 0.5, 0.0],
    )
    short = shortlist(listed, 3)
    assert list(short.index) == [11, 20, 12]  # 13 and 22 are in the further halves
    assert recommend(short) == 20  # fit 0.8 for 20 and 12: the larger gap


def test_team_fifths_split_teams_by_strength_ties_by_order():
    strength = pd.Series([0.5, -1.0, 0.0, 0.0, 2.0, 1.0, -0.5, 0.3, -0.2, 1.5],
                         index=range(100, 110))  # fmt: skip
    fifths = team_fifths(strength)
    assert fifths.value_counts().to_dict() == dict.fromkeys(range(1, FIFTHS + 1), 2)
    assert fifths[104] == FIFTHS and fifths[109] == FIFTHS and fifths[101] == 1
    assert (fifths[102], fifths[103]) == (2, 3)  # tied, split by order


def test_the_ceiling_is_the_fee_over_the_median_ratio_of_profiled_transfers_to_the_league():
    ratios = pd.DataFrame({
        "league": ["GB1", "GB1", "GB1", "GB1", "ES1"],
        "ratio": [1.0, 2.0, 3.0, 100.0, 9.0],
        "profiled": [True, True, True, False, True],
    })  # fmt: skip
    assert ceiling(12e6, ratios, "GB1") == pytest.approx(6e6)
    assert np.isnan(ceiling(12e6, ratios, "IT1"))

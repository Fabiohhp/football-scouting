import pandas as pd
import pytest

from football_scouting.analysis.backtest import lexicographic, pick_means, pick_weights


def test_a_pick_takes_the_top_share_of_each_group():
    key = pd.Series([5.0, 4.0, 3.0, 2.0, 1.0, 9.0, 8.0, 7.0, 6.0, 0.0])
    groups = pd.Series(list("aaaaabbbbb"))
    weights = pick_weights(key, groups, 0.4)  # two places in each group
    assert weights.tolist() == [1, 1, 0, 0, 0, 1, 1, 0, 0, 0]
    assert pick_weights(key, groups, 0.05).sum() == 0  # no place in a group of five


def test_a_pick_can_take_a_set_number_of_each_group():
    key = pd.Series([5.0, 4.0, 3.0, 2.0, 1.0, 9.0, 8.0])
    groups = pd.Series(list("aaaaabb"))
    weights = pick_weights(key, groups, places=3)  # group b has only two rows
    assert weights.tolist() == [1, 1, 1, 0, 0, 1, 1]
    with pytest.raises(ValueError):
        pick_weights(key, groups, 0.4, places=3)
    with pytest.raises(ValueError):
        pick_weights(key, groups)


def test_rows_tied_at_the_edge_share_the_places_left():
    key = pd.Series([3, 2, 2, 2, 1])
    weights = pick_weights(key, pd.Series(["a"] * 5), 0.4)
    assert weights.tolist() == pytest.approx([1, 1 / 3, 1 / 3, 1 / 3, 0])
    assert weights.sum() == pytest.approx(2)


def test_lexicographic_breaks_ties_with_the_next_key():
    first, second = pd.Series([1, 1, 2, 2, 0]), pd.Series([5, 3, 1, 1, 9])
    assert lexicographic(first, second).tolist() == [3, 2, 4, 4, 1]


def test_pick_means_rank_each_resample_afresh():
    data = pd.DataFrame(
        {
            "comparison_group": ["a"] * 4,
            "gap": [4, 3, 2, 1],
            "minutes": [1, 2, 3, 4],
            "score": [90, 70, 30, 10],
        }
    )
    keys = {"gap": lambda d: d.gap, "minutes": lambda d: d.minutes}
    means = pick_means(data, keys, "score", 0.5)
    assert means.to_dict() == {"gap": 80, "minutes": 20}
    assert pick_means(data.iloc[[1, 2, 3, 3]], keys, "score", 0.5).to_dict() == {
        "gap": 50,
        "minutes": 10,
    }
    assert pick_means(data, keys, "score", places=1).to_dict() == {"gap": 90, "minutes": 10}

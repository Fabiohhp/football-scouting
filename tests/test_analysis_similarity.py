import duckdb
import numpy as np
import pandas as pd
import pytest

from football_scouting.analysis.similarity import (
    coordinates,
    fit_block,
    in_common,
    line,
    listed,
    main_positions,
    nearest,
    own_rank,
    profile_gaps,
    search_points,
    search_values,
    similar,
    style_ends,
)
from football_scouting.config import load_config


def correlated(n: int = 500, seed: int = 0) -> pd.DataFrame:
    """Three numbers on different scales, the first two strongly correlated."""
    rng = np.random.default_rng(seed)
    a, b = rng.normal(size=(2, n))
    return pd.DataFrame({"x": 10 * a, "y": 3 * (a + 0.3 * b), "z": rng.normal(5, 2, n)})


@pytest.mark.parametrize("whiten", [False, True])
def test_a_block_has_total_variance_1_on_the_rows_it_is_fitted_on(whiten):
    values = correlated()
    c = fit_block(values, whiten=whiten).coordinates(values)
    cov = np.cov(c.to_numpy(), rowvar=False, ddof=0)
    assert np.trace(cov) == pytest.approx(1)
    if whiten:  # uncorrelated, each coordinate a third of the variance
        assert cov == pytest.approx(np.eye(3) / 3, abs=1e-12)
    else:  # standardised columns, scaled down
        assert c.x.corr(values.x) == pytest.approx(1) and c.x.var(ddof=0) == pytest.approx(1 / 3)
    assert (fit_block(values).coordinates(values.assign(z=np.nan)).z == 0).all()  # the mean


def test_blocks_weigh_the_same_whatever_their_columns():
    values = correlated()
    one = pd.DataFrame({"w": np.random.default_rng(1).normal(size=len(values))})
    blocks = {"three": fit_block(values), "one": fit_block(one)}
    c = coordinates(blocks, {"three": values, "one": one})
    variance = c.var(ddof=0).groupby(level=0).sum()
    assert variance.to_dict() == pytest.approx({"three": 1, "one": 1})


def test_own_rank_counts_the_candidates_nearer_than_the_players_own():
    candidates = pd.DataFrame({"x": [0.0, 1.0, 5.0, 9.0]}, index=["a", "b", "c", "d"])
    queries = pd.DataFrame({"x": [0.2, 4.0, 9.5]}, index=["a", "b", "d"])
    # b, at 4: its own candidate (1) is 3 away, c (5) only 1.
    assert own_rank(queries, candidates).tolist() == [1, 2, 1]
    with pytest.raises(ValueError):
        own_rank(queries.rename(index={"a": "e"}), candidates)
    # Each query's own candidate replaced: b's own now at 4.5, nearer than c; d's at -1, behind all.
    own = pd.DataFrame({"x": [0.0, 4.5, -1.0]}, index=["a", "b", "d"])
    assert own_rank(queries, candidates, own).tolist() == [1, 1, 4]


def test_nearest_lists_the_other_rows_nearest_first():
    points = pd.DataFrame({"x": [0.0, 1.0, 4.0, 9.0], "y": 0.0}, index=["a", "b", "c", "d"])
    near = nearest(points, 2)
    assert near.loc["a"].tolist() == ["b", "c"] and near.loc["c"].tolist() == ["b", "a"]
    assert near.loc["d"].tolist() == ["c", "b"] and list(near.columns) == [1, 2]


def test_listed_counts_the_other_players_lists_a_candidate_comes_in():
    points = pd.DataFrame({"x": [0.0, 1.0, 5.0, 11.0]}, index=["a", "b", "c", "d"])
    # Nearest other: a -> b, b -> a, c -> b, d -> c.
    assert listed(points, points, 1).tolist() == [1, 2, 1, 0]
    # c placed at 0.5 comes first for a and b; d placed at 4.8 first for c.
    own = points.assign(x=[0.0, 1.0, 0.5, 4.8])
    assert listed(points, points, 1, own).tolist() == [1, 2, 2, 1]
    assert listed(points, points, 2).sum() == 2 * len(points)  # k places in each list


def test_search_values_are_the_groups_shrunk_values_block_by_block():
    style = pd.DataFrame({
        "player_id": [1, 1, 2, 2, 3], "comparison_group": ["CB", "CB", "CB", "CB", "FB"],
        "descriptor": ["width", "height", "width", "height", "width"],
        "shrunk": [1.0, 2.0, 3.0, 4.0, 5.0],
    })  # fmt: skip
    profile = style.rename(columns={"descriptor": "statistic"}).assign(shrunk=lambda t: -t.shrunk)
    values = search_values(style, profile, "CB")
    assert list(values) == ["descriptors", "profile"]
    assert values["descriptors"].loc[2].to_dict() == {"height": 4.0, "width": 3.0}
    assert values["profile"].loc[1, "width"] == -1.0 and 3 not in values["profile"].index


def test_search_points_are_fitted_on_the_regulars():
    values = {"descriptors": correlated(), "profile": correlated(seed=1)[["z"]]}
    regulars = values["profile"].index[:300]
    points = search_points(values, regulars)
    assert len(points) == 500  # every player placed
    variance = points.loc[regulars].var(ddof=0).groupby(level=0).sum()
    assert variance.to_dict() == pytest.approx({"descriptors": 1, "profile": 1})


# Six players on a line; a (the query) and b played for team 1.
POINTS = pd.DataFrame({"x": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]}, index=list("abcdef"))
PLAYERS = pd.DataFrame(
    {
        "list": ["Regulars", "Regulars", "Young", "Regulars", None, "Regulars"],
        "teams": [frozenset({1}), frozenset({1, 2}), frozenset({3}), frozenset({4}),
                  frozenset({5}), frozenset({6})],
        "age": [25.0, 30.0, 20.0, 27.0, 21.0, np.nan],
        "league": ["A", "A", "B", "B", "A", "A"],
        "value": [10e6, 5e6, 1e6, 20e6, 1e6, np.nan],
        "left_foot": [0.1, 0.2, 0.7, 0.5, 0.0, np.nan],
        "side": ["Left", None, "Left", "Right", None, "Left"],
    },
    index=list("abcdef"),
)  # fmt: skip


def test_similar_lists_the_nearest_candidates_list_by_list():
    out = similar(POINTS, PLAYERS, "a")
    # b is a teammate, e not a candidate; the young player is listed apart.
    assert out.index.tolist() == ["d", "f", "c"]
    assert out.place.tolist() == [1, 2, 1] and out.distance.tolist() == [3.0, 5.0, 2.0]
    assert similar(POINTS, PLAYERS, "a", teammates=True).index.tolist() == ["b", "d", "f", "c"]
    assert similar(POINTS, PLAYERS, "a", n=1).index.tolist() == ["d", "c"]
    assert similar(POINTS, PLAYERS, "d", n=None).index.tolist() == ["b", "f", "a", "c"]


@pytest.mark.parametrize(
    ("filters", "kept"),
    [
        ({"younger_than": 27}, ["c"]),  # not 27 itself, nor a missing age
        ({"leagues": ["B"]}, ["d", "c"]),
        ({"max_value": 5e6}, ["c"]),  # nor a player not valued
        ({"foot": "left"}, ["d", "c"]),
        ({"foot": "right"}, []),  # a missing share is neither foot
        ({"side": "Left"}, ["f", "c"]),
    ],
)
def test_similar_filters_the_candidates(filters, kept):
    assert similar(POINTS, PLAYERS, "a", **filters).index.tolist() == kept


def test_similar_takes_only_the_two_feet():
    with pytest.raises(ValueError):
        similar(POINTS, PLAYERS, "a", foot="both")


def test_style_ends_and_what_two_players_have_in_common():
    scores = pd.DataFrame(
        {1: [-2.0, -1.0, 0.0, 1.0, 2.0, -3.0], 2: [1.0, 2.0, 3.0, -1.0, -2.0, -1.5]},
        index=list("abcdef"),
    )
    regulars = list("abcde")  # thirds of axis 1 at -0.67 and 0.67, of axis 2 at -0.33 and 1.67
    ends = style_ends(scores, [("Deep", "High"), ("Short", "Long")], regulars)
    assert ends.loc["a"].tolist() == ["Deep", None] and ends.loc["e"].tolist() == ["High", "Short"]
    assert ends.loc["f"].tolist() == ["Deep", "Short"]  # placed by the regulars' thirds
    assert in_common(ends, "f", ["a", "b", "c", "d", "e"]).tolist() == [
        "Deep", "Deep", "", "Short", "Short",
    ]  # fmt: skip
    assert in_common(ends, "c", ["c"]).tolist() == ["Long"]


def test_profile_gaps_are_the_largest_percentile_differences_each_way():
    percentiles = pd.DataFrame(
        {"passes": [50.0, 80.0, 40.0], "tackles": [50.0, 30.0, 45.0], "xt": [50.0, 55.0, 50.0]},
        index=list("abc"),
    )
    gaps = profile_gaps(percentiles, "a", ["b", "c"])
    assert gaps.loc["b"].tolist() == ["passes", 30.0, "tackles", -20.0]
    assert gaps.loc["c", "below"] == "passes" and pd.isna(gaps.loc["c", "above"])


def test_line_reads_the_position_within_its_group():
    assert line("CM", "Left Defensive Midfield") == "Defensive"
    assert line("CM", "Right Center Midfield") == "Central"
    assert line("AMW", "Center Attacking Midfield") == "Attacking midfield"
    assert line("AMW", "Right Wing") == "Wing" and line("AMW", "Left Midfield") == "Wide midfield"
    assert (
        line("CF", "Center Forward") == "Alone" and line("CF", "Left Center Forward") == "In a pair"
    )
    assert line("CB", "Left Center Back") is None


def test_main_positions_count_only_time_in_the_groups_positions():
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE player_positions AS SELECT * FROM (VALUES "
        "(1, 10, 'Right Wing', 'W', 600), (1, 10, 'Right Midfield', 'W', 300), "
        "(1, 11, 'Right Midfield', 'W', 400), (1, 10, 'Center Forward', 'CF', 5000), "
        "(2, 20, 'Center Attacking Midfield', 'AM', 900)) "
        "t(player_id, team_id, position, position_group, seconds)"
    )
    out = main_positions(con, load_config(), pd.Series({1: "AMW", 2: "AMW"}))
    # player 1: 700 seconds at right midfield against 600 on the wing; the centre-forward time is
    # outside the group; team 10 with 900 seconds in the group's positions
    assert out.loc[1].tolist() == ["Right Midfield", 10, "Right"]
    assert out.loc[2, "position"] == "Center Attacking Midfield" and pd.isna(out.loc[2, "side"])

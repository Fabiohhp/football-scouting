import numpy as np
import pandas as pd
import pytest

from football_scouting.analysis.roles import Axes
from football_scouting.analysis.similarity import Block
from football_scouting.analysis.teams import (
    NUMBERS,
    RECORDED,
    Seasons,
    fit,
    fit_distances,
    numbers,
    position_code,
    recording_factors,
    rescale,
    scores_without,
    split_half,
    style_slopes,
    whole_season_team,
    without,
)

COUNTS = [
    "passes", "passes_completed", "forward_yards", "passes_own60", "passes_own_third",
    "long_passes_own_third", "passes_final_third", "crosses", "pass_entries",
    "wide_pass_entries", "goal_kicks", "long_goal_kicks", "carry_entries", "wide_carry_entries",
    "sum_x_recoveries_blocks", "recoveries_blocks", "possessions", "seconds", "opp_passes_own60",
    "opp_passes_final_third", "opp_seconds", "xpass_passes", "xpass_expected",
    *RECORDED, *(c for follow in RECORDED.values() for c in follow),
]  # fmt: skip


def one_match(**counts) -> pd.DataFrame:
    """A team-match with every count at 1, except `counts`."""
    return pd.DataFrame([dict.fromkeys(COUNTS, 1.0) | counts])


def test_numbers_are_ratios_of_the_summed_counts():
    row = one_match(
        opp_passes_own60=60, tackles_high=2, interceptions_high=3, fouls_high=5,
        tackles=2, sum_x_tackles=100, interceptions=2, sum_x_interceptions=60, clearances=0,
        sum_x_clearances=0, recoveries_blocks=0, sum_x_recoveries_blocks=0,
        seconds=1800, opp_seconds=1200, passes_final_third=30, opp_passes_final_third=10,
        passes=480, possessions=96, forward_yards=500, passes_completed=100,
        wide_pass_entries=3, wide_carry_entries=1, pass_entries=6, carry_entries=2,
        xpass_passes=480, xpass_expected=360,
    )  # fmt: skip
    out = numbers(row).iloc[0]
    assert list(out.index) == list(NUMBERS)
    assert out.ppda == 6  # 60 passes over 10 actions
    assert out.defence_height == 40  # (100 + 60) / 4
    assert out.possession == 0.6 and out.field_tilt == 0.75
    assert out.passes_per_possession == 5 and out.tempo == 16  # 480 passes in 30 minutes
    assert out.directness == 5 and out.wide_entries == 0.5 and out.pass_ease == 0.75
    assert "pass_ease" not in numbers(row.drop(columns=["xpass_passes", "xpass_expected"]))


def test_rescaling_brings_each_context_to_the_mean_and_keeps_its_heights():
    sums = pd.concat(
        [
            one_match(interceptions=2, sum_x_interceptions=80),
            one_match(interceptions=6, sum_x_interceptions=180),
        ],
        ignore_index=True,
    )
    context = pd.Series(["before", "after"])
    factors = recording_factors(sums, context)
    f = factors[factors.statistic == "interceptions"].set_index("context").factor
    assert f.to_dict() == pytest.approx({"after": 4 / 6, "before": 4 / 2})
    out = rescale(sums, context, factors)
    assert out.interceptions.tolist() == pytest.approx([4, 4])
    # the mean height of each context's interceptions is kept: 40 and 30
    assert (out.sum_x_interceptions / out.interceptions).tolist() == pytest.approx([40, 30])
    assert out.passes.tolist() == sums.passes.tolist()  # counts recorded alike are untouched
    other = rescale(sums, pd.Series(["elsewhere", "elsewhere"]), factors)
    assert other.interceptions.tolist() == sums.interceptions.tolist()  # no factor: 1


def test_split_half_finds_stable_differences_between_teams():
    rng = np.random.default_rng(0)
    rows = []
    for team, tempo in enumerate(np.linspace(8, 16, 12)):
        for _ in range(38):  # passes per minute with the ball: the team's own, plus noise
            rows.append(
                one_match(team_id=team, seconds=1800, passes=30 * (tempo + rng.normal(0, 1))).iloc[
                    0
                ]
            )
    sums = pd.DataFrame(rows)
    league = pd.Series({t: t % 2 for t in range(12)})
    reliability = split_half(sums, league, draws=20).mean()
    assert reliability.tempo > 0.95
    assert np.isnan(reliability.ppda)  # the same in every match: nothing to tell apart


def test_without_takes_a_players_own_counts_out_of_the_team():
    team = one_match(passes=500, long_passes_own_third=40, opp_passes_own60=300, seconds=1800)
    own = pd.DataFrame([{"match_id": 7, "passes": 50.0, "long_passes_own_third": 10.0}])
    out = without(team, own)
    assert out.passes[0] == 450 and out.long_passes_own_third[0] == 30
    # the opponent's counts and the time with the ball are no single player's
    assert out.opp_passes_own60[0] == 300 and out.seconds[0] == 1800
    assert "match_id" not in out and out.crosses[0] == 1


def test_fit_is_the_share_of_the_other_clubs_further_away():
    distances = pd.DataFrame(
        [[1.0, 2.0, 3.0, 4.0, 5.0], [5.0, 4.0, 3.0, 2.0, 2.0]], columns=list("abcde"), index=[7, 8]
    )
    out = fit(distances, pd.Series(["b", "d"], index=[7, 8]), pd.Series(["a", "e"], index=[7, 8]))
    # player 7: of c, d and e (a was left), all further than b; player 8: a, b, c further than d
    assert out.to_dict() == {7: 1.0, 8: 1.0}
    out = fit(distances, pd.Series(["c", "e"], index=[7, 8]), pd.Series(["a", "a"], index=[7, 8]))
    assert out[7] == pytest.approx(2 / 3)  # b nearer, d and e further
    assert out[8] == pytest.approx(2.5 / 3)  # b and c further, d tied
    distances.loc[8, "b"] = distances.loc[7, "d"] = np.nan  # no players in the position
    out = fit(distances, pd.Series(["d", "d"], index=[7, 8]), pd.Series(["a", "a"], index=[7, 8]))
    assert np.isnan(out[7])
    assert out[8] == pytest.approx(1.5 / 2)  # c further, e tied, b left out


def test_position_codes_are_the_initials():
    assert position_code("Left Center Back") == "LCB" and position_code("Center Forward") == "CF"
    assert position_code("Goalkeeper") == "GK"


def seasons_of(season: pd.DataFrame, own: pd.DataFrame) -> Seasons:
    """Seasons with only the season sums and the players' own sums."""
    empty = pd.DataFrame()
    return Seasons(empty, pd.Series(dtype=str), empty, empty, season, own)


def test_scores_without_take_the_players_own_actions_out_of_the_team():
    season = pd.concat([one_match(passes=600.0, seconds=1800.0), one_match(passes=300.0)])
    season.index = pd.Index([10, 11], name="team_id")
    own = pd.DataFrame({"passes": [60.0, 30.0, 1.0]},
                       index=pd.MultiIndex.from_tuples([(1, 10), (2, 10), (3, 11)],
                                                       names=["player_id", "team_id"]))  # fmt: skip
    tempo = Axes(mean=pd.Series({"tempo": 0.0}), scale=pd.Series({"tempo": 1.0}),
                 loadings=pd.DataFrame({1: [1.0]}, index=["tempo"]),
                 weights=pd.DataFrame({1: [1.0]}, index=["tempo"]))  # fmt: skip
    out = scores_without(seasons_of(season, own), tempo, [1, 2], [10, 10])
    assert out[1].tolist() == pytest.approx([18, 19])  # 540 and 570 passes in 30 minutes
    assert out.index.tolist() == [1, 2]


def test_whole_season_team_keeps_the_players_with_one_team():
    own = pd.DataFrame({"passes": [1.0, 1.0, 1.0, 1.0]},
                       index=pd.MultiIndex.from_tuples([(1, 10), (2, 10), (2, 11), (3, 12)],
                                                       names=["player_id", "team_id"]))  # fmt: skip
    out = whole_season_team(seasons_of(pd.DataFrame(), own), [3, 2, 1])
    assert out.to_dict() == {3: 12, 1: 10} and out.index.tolist() == [3, 1]


def test_style_slopes_are_least_squares_slopes_on_each_axis():
    rng = np.random.default_rng(0)
    scores = pd.DataFrame(rng.normal(size=(50, 2)), columns=[1, 2])
    values = pd.DataFrame({"a": 2 + 3 * scores[1] - scores[2], "b": 1 + 0.5 * scores[2]})
    out = style_slopes(values, scores)
    assert out.loc[1].tolist() == pytest.approx([3, 0]) and out.loc[2].tolist() == pytest.approx(
        [-1, 0.5]
    )


def test_fit_distances_read_each_club_without_the_player_and_take_the_teams_part_out():
    sums = pd.DataFrame(
        {
            "team_id": [1, 1, 2, 2, 3],
            "player_id": [7, 8, 9, 10, 11],
            "a": [10.0, 30.0, 20.0, 20.0, 50.0],
            "minutes": [10.0] * 5,
        }
    )

    def place(s):  # a rate per minute
        return pd.DataFrame({"a": s.a / s.minutes})

    block = Block(pd.Series({"a": 0.0}), pd.Series({"a": 1.0}), pd.DataFrame({"a": [1.0]}, ["a"]))
    out = fit_distances(sums, place, block, pd.Index([7, 9]))
    # player 7 (1 a minute) against club 1 without them (player 8: 3), club 2 (2) and club 3 (5)
    assert out.loc[7].tolist() == pytest.approx([2, 1, 4])
    assert out.loc[9].tolist() == pytest.approx([0, 0, 3])  # club 1 (2), club 2 without them (2)
    team_scores = pd.DataFrame({1: [0.0, 1.0, -1.0]}, index=pd.Index([1, 2, 3], name="team_id"))
    shift = {
        "slopes": pd.DataFrame({"a": [1.0]}, index=[1]),
        "team_scores": team_scores,
        "old_scores": pd.DataFrame({1: [0.5]}, index=[7]),
    }
    shifted = fit_distances(sums, place, block, pd.Index([7]), **shift)
    # player 7 at 1 - 0.5; club 1 without them at 3 - 0, club 2 at 2 - 1, club 3 at 5 + 1
    assert shifted.loc[7].tolist() == pytest.approx([2.5, 0.5, 5.5])

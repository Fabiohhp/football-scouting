import numpy as np
import pandas as pd
import pytest

from football_scouting.analysis.teams import (
    NUMBERS,
    RECORDED,
    fit,
    numbers,
    position_code,
    recording_factors,
    rescale,
    split_half,
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

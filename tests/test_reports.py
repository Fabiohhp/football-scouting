import base64
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from football_scouting.reports import (
    MOST,
    STRONG,
    WEAK,
    by_family,
    natural,
    pizza,
    render,
    role,
    shot_figure,
    slug,
    strengths,
    style_figure,
    svg,
    touch_figure,
)


def test_strengths_and_weaknesses_are_the_extremes_past_the_cuts_at_most_three_each():
    p = pd.Series({"a": 95, "b": STRONG, "c": 79.9, "d": 99, "e": 81, "f": 10, "g": WEAK,
                   "h": 20.1, "i": 50})  # fmt: skip
    strong, weak = strengths(p)
    assert list(strong.index) == ["d", "a", "e"]  # b also qualifies: at most MOST
    assert len(strong) == MOST and list(weak.index) == ["f", "g"]
    none_strong, none_weak = strengths(pd.Series({"a": 50.0, "b": 60.0}))
    assert none_strong.empty and none_weak.empty


def test_statistics_in_their_own_units_and_by_family():
    assert natural("completion_above_expected", -0.026) == "-2.6%"
    assert natural("ball_losses_per_touch", 0.015) == "1.5% of touches"
    assert natural("xg_per_shot", 0.0912) == "0.09 per shot"
    assert natural("aerial_win_rate", 0.55) == "55% won"
    assert natural("pressures", 19.444) == "19.44 per 90"
    order = by_family(["pressures", "xg", "completion_above_expected", "key_passes", "shots"])
    assert order == ["xg", "shots", "key_passes", "completion_above_expected", "pressures"]


def test_file_names_are_ascii_words_joined_by_hyphens():
    assert slug("Adri Embarba") == "adri-embarba"
    assert slug("Álvaro Cejudo") == "alvaro-cejudo"
    assert slug("Suso") == "suso"
    assert slug("N'Golo  Kanté") == "n-golo-kante"


def test_a_figure_becomes_the_same_svg_data_uri_every_time():
    def figure():
        return style_figure(
            pd.DataFrame({1: [0.0, 1.0, -1.0, 2.0], 2: [0.5, -0.5, 0.0, 1.0]}, index=list("abcd")),
            [("Low one", "High one"), ("Low two", "High two")], list("abcd"), "a", "b",
        )  # fmt: skip

    first, second = svg(figure()), svg(figure())
    assert first == second and first.startswith("data:image/svg+xml;base64,")
    text = base64.b64decode(first.split(",", 1)[1]).decode()
    assert "<svg" in text and "dc:date" not in text and "High two" in text  # text kept as text


def test_the_figures_draw_on_any_player():
    rng = np.random.default_rng(0)
    p = pd.Series(rng.uniform(0, 100, 4), index=["xg", "shots", "key_passes", "pressures"])
    shots = pd.DataFrame({"x": [100.0, 110.0], "y": [40.0, 30.0], "xg": [0.05, 0.4],
                          "goal": [False, True]})  # fmt: skip
    for fig in (
        pizza(p),
        pizza(p, compare=p[::-1]),
        touch_figure(pd.Series(np.full(16 * 24, 1 / (16 * 24)))),
        shot_figure(shots),
        shot_figure(pd.DataFrame({"x": [], "y": [], "xg": [], "goal": []})),
    ):
        assert svg(fig).startswith("data:image/svg+xml")


def test_a_players_role_in_the_case_study():
    listed = pd.DataFrame({"list": ["Regulars"] * 3 + ["Young"], "place": [1, 2, 3, 1]},
                          index=[5, 6, 8, 7])  # fmt: skip
    case = SimpleNamespace(
        player=1, shortlist=pd.DataFrame(index=[5, 6, 7]), recommended=6, long_list=listed
    )
    assert role(case, 1) == "The player to replace"
    assert role(case, 6) == "Shortlist: the recommendation, 2nd of 3 by the gap"
    assert role(case, 7) == "Shortlist: 3rd of 3 by the gap"
    assert role(case, 8) == "Long list: regulars, 3rd of 3 by distance"
    assert role(case, 9) == "Candidate"


def context(**changes) -> dict:
    """A report's context, every key the template reads."""
    row = {"label": "Pressures", "percentile": 85, "value": "20.76 per 90"}
    out = {
        "name": "A <Player>", "as_of": "30 June 2016", "club": "A Club", "reference": "B Player",
        "reference_short": "Player", "is_reference": False, "role": "Shortlist",
        "recommended": True, "group": "Wingers", "group_size": 300, "regulars": 250,
        "facts": [("Team", "A Team (A League)")],
        "tiles": [{"label": "Fit to A Club", "value": "0.92", "note": "nearer than 92%"}],
        "strengths": [row], "weaknesses": [], "strong": STRONG, "weak": WEAK,
        "profile": [{"family": "Defending", "color": "#CC79A7", "label": "Pressures",
                     "value": "20.76 per 90", "percentile": 85, "reference": 69}],
        "families": [("Defending", "#CC79A7")],
        "alike": {"ends": "Forward passer", "above": "Tackles (+36 points)", "below": "none"},
        "ends": ["Forward passer"], "nearest": [{"name": "C", "team": "D", "league": "E",
                                                  "distance": "0.84"}],
        "shots": "11 non-penalty shots, 0.9 xG, 1 goal", "notes": ["A note."],
        "figures": dict.fromkeys(["pizza", "touches", "shots", "style"], "data:image/svg+xml;x"),
    }  # fmt: skip
    return out | changes


def test_a_report_renders_every_part_and_escapes_text():
    html = render(context())
    assert html.startswith("<!doctype html>") and "A &lt;Player&gt;" in html
    assert "<title>A &lt;Player&gt;: scouting report, 30 June 2016</title>" in html
    for part in ("Strengths", "No statistic at the 20th percentile or below.", "A note.",
                 "Against B Player", "role pick", "left: calc(69% - 1px)", "1 goal"):  # fmt: skip
        assert part in html
    reference = render(context(is_reference=True, alike=None, notes=[]))
    assert "Against" not in reference and "dashed" not in reference


def test_a_template_reading_a_missing_key_fails():
    with pytest.raises(Exception, match="undefined"):
        render({k: v for k, v in context().items() if k != "tiles"})

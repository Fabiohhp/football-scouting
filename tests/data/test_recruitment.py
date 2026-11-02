"""The recruitment case study and its scouting reports. Run with `make dq`."""

import re

import numpy as np
import pytest

from football_scouting.analysis.profiles import recording_context, rescale
from football_scouting.analysis.recruitment import (
    FIFTHS,
    STYLE_SUMS,
    case_study,
    fee_ratios,
    signings,
)
from football_scouting.analysis.roles import place, style_matches
from football_scouting.config import load_config
from football_scouting.model.database import connect_readonly, database_path
from football_scouting.reports import report, write_reports

pytestmark = pytest.mark.data
CFG = load_config()


@pytest.fixture(scope="module")
def con():
    if not database_path(CFG).exists():
        pytest.skip("database not built (run `make model`)")
    return connect_readonly(CFG)


@pytest.fixture(scope="module")
def rows(con):
    groups = con.sql("SELECT * FROM profile_players").df().set_index("player_id").comparison_group
    rows = style_matches(con, CFG, groups)
    recorded = con.sql("SELECT * FROM style_recording").df()
    return rescale(rows, groups, recording_context(rows, CFG), recorded)


@pytest.fixture(scope="module")
def case(con, rows):
    return case_study(con, CFG, rows=rows)


def test_fit_reads_a_players_season_as_the_stored_style_values(con, rows, case):
    descriptors = con.sql("SELECT * FROM style_descriptors").df()
    stored = con.sql("SELECT * FROM style_values").df()
    stored = stored[stored.comparison_group == case.group].pivot(
        index="player_id", columns="descriptor", values="shrunk"
    )
    mine = rows[rows.player_id.isin(case.players.index)]
    season = place(mine.groupby("player_id")[STYLE_SUMS].sum(), case.group, descriptors)
    assert len(season) == len(case.players)
    assert np.allclose(season, stored.loc[season.index, season.columns])


def test_the_budget_reads_the_summer_before_the_market_view(con, case):
    year = CFG.backtest.market_view.year
    before = fee_ratios(con, CFG, case.players.index, year - 1)
    assert before.transfer_date.max().year == year - 1
    assert before.ratio.gt(0).all() and before.league.isin(["GB1", "ES1", "IT1", "FR1"]).all()
    assert case.fee > case.ceiling > 0
    # Summer transfers are dated from 1 July: none of the summer of the market view was known.
    during = fee_ratios(con, CFG, case.players.index, year)
    assert (during.transfer_date.dt.date > CFG.backtest.market_view).all()


def test_every_player_on_the_long_list_passes_every_rule(case):
    listed, me = case.long_list, case.players.loc[case.player]
    assert len(listed) > 0 and case.player not in listed.index
    assert (listed.side == me.side).all() and (listed.age < CFG.case_study.younger_than).all()
    assert (listed.value <= case.ceiling).all() and (listed.team_fifth != FIFTHS).all()
    assert not listed.teams.map(lambda t: bool(t & me.teams)).any()
    assert set(listed["list"]) <= {"Regulars", "Young"}
    for _, d in listed.groupby("list"):
        assert d.distance.is_monotonic_increasing and d.nearer_half.sum() == (len(d) + 1) // 2
    counts = [len(d) for d in case.steps.values()]
    assert counts == sorted(counts, reverse=True) and counts[-1] == len(listed)


def test_the_shortlist_and_the_recommendation_follow_the_rules(case):
    short, nearer = case.shortlist, case.long_list[case.long_list.nearer_half]
    assert len(short) == CFG.case_study.shortlist and short.nearer_half.all()
    assert short.gap.min() >= nearer.drop(short.index).gap.max()
    assert case.recommended in short.index and case.fit[case.recommended] == short.fit.max()
    assert case.fit.between(0, 1).all() and case.fit.index.is_unique
    assert set(case.long_list.index) | {case.player} <= set(case.fit.index)


def test_the_club_signed_a_player_of_the_group_who_never_played_for_it_in_2015_16(con, case):
    signed = signings(con, case, CFG.backtest.market_view.year)
    assert len(signed) >= 1 and case.player not in signed
    assert not case.players.teams[signed].map(lambda t: case.club in t).any()


def test_the_reports_cover_the_shortlist_the_player_and_the_signings(con, case, tmp_path):
    signed = signings(con, case, CFG.backtest.market_view.year)
    paths = write_reports(con, CFG, case, signed, out=tmp_path)
    expected = len(set(case.shortlist.index) | {case.player} | set(signed)) + 1
    assert len(paths) == expected and paths[-1].name == "index.html"
    index = paths[-1].read_text()
    for path in paths[:-1]:
        html = path.read_text()
        text = re.sub(r'src="data:[^"]*"', "", html)  # the figures
        assert path.name in index and not re.search(r"\bnan\b", text, re.IGNORECASE)
        assert "StatsBomb" in html and html.count('<img class="figure"') == 4
    again = report(con, CFG, case, case.recommended)
    first = report(con, CFG, case, case.recommended)
    assert again == first  # a report rebuilds the same
    assert np.isclose(float(first["tiles"][2]["value"]), case.fit[case.recommended], atol=0.005)

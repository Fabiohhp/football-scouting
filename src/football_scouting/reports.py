"""One-page scouting reports (HTML) of a recruitment case study's players, as the club could see
them on the back-test's market view.

`report` gathers what a page shows of one player of a case study (`recruitment.CaseStudy`):

- who they are: team, league, age, main position, foot, minutes;
- their profile as percentiles within the comparison group, as a pizza (`pizza`) and as a table
  in each statistic's own unit (`natural`) beside the player the club is replacing;
- their strengths and weaknesses (`strengths`): the statistics at a percentile of `STRONG` or more
  and of `WEAK` or less, at most `MOST` of each;
- where they touched the ball and where they shot from (`touch_figure`, `shot_figure`);
- where they stand on the group's style axes (`style_figure`), the axis ends they share with the
  player replaced and the statistics they are furthest above and below them on;
- their market value against the market model's (`market.gap`), their fit to the club's style
  (`teams.fit`) and the regulars nearest them in the search's space;
- notes on what the numbers leave out: a young player's fewer minutes, a team next to the
  strongest fifth, a team in the relegation places.

`render` fills the template (`templates/scouting_report.html.j2`) with the figures inline as SVG,
so that a report is one file and rebuilds the same; `write_reports` writes a case study's reports
and an index page (`templates/scouting_index.html.j2`). Nothing after the market view is read.
"""

from __future__ import annotations

import base64
import io
import re
import textwrap
from collections.abc import Hashable, Sequence
from datetime import date
from pathlib import Path

import duckdb
import jinja2
import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from anyascii import anyascii
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from mplsoccer import Pitch, PyPizza, VerticalPitch
from scipy.ndimage import gaussian_filter

from football_scouting.analysis.metrics import LOWER_IS_BETTER
from football_scouting.analysis.profiles import FAMILY_OF, LABELS
from football_scouting.analysis.recruitment import FIFTHS, CaseStudy, league_table
from football_scouting.analysis.similarity import (
    FOOT,
    THIRD,
    in_common,
    profile_gaps,
    similar,
)
from football_scouting.analysis.style import touch_map
from football_scouting.config import Config
from football_scouting.plots import GREY, OKABE_ITO

STRONG, WEAK = 80, 20  # percentiles: a strength at or above, a weakness at or below
MOST = 3  # strengths and weaknesses shown, of each
NEAREST = 5  # the regulars nearest a player shown
ZONE = 5  # yards, touch maps
RELEGATED = 3  # the bottom places of each pool league, relegated in 2015/16
FAMILY_COLORS = {
    "Shooting": OKABE_ITO[5],
    "Chance creation": OKABE_ITO[1],
    "Passing and progression": OKABE_ITO[0],
    "Carrying and ball security": OKABE_ITO[2],
    "Defending": OKABE_ITO[3],
    "Aerial duels": OKABE_ITO[4],
    "Position": GREY,
}
FAMILY_ORDER = list(FAMILY_COLORS)
INK, MUTED, LINE = "#1F1F1F", "#6B6B6B", "#9A9A9A"
FONT = {
    "font.family": "DejaVu Sans",
    "font.size": 9,
    "svg.fonttype": "none",
    "svg.hashsalt": "football-scouting",
}  # text as text: a smaller file
TEMPLATES = jinja2.Environment(
    loader=jinja2.PackageLoader("football_scouting", "templates"),
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
    undefined=jinja2.StrictUndefined,
)


def natural(statistic: str, value: float) -> str:
    """A profile statistic in its own unit."""
    if statistic == "completion_above_expected":
        return f"{value:+.1%}"
    if statistic == "ball_losses_per_touch":
        return f"{value:.1%} of touches"
    if statistic == "aerial_win_rate":
        return f"{value:.0%} won"
    if statistic == "xg_per_shot":
        return f"{value:.2f} per shot"
    return f"{value:.2f} per 90"


def label(statistic: str) -> str:
    """A profile statistic's label, with "(fewer: higher)" where a lower value is the better."""
    return LABELS[statistic] + (" (fewer: higher)" if statistic in LOWER_IS_BETTER else "")


def by_family(statistics: Sequence[str]) -> list[str]:
    """`statistics` grouped by family (`FAMILY_ORDER`), in their order within each."""
    return sorted(statistics, key=lambda s: FAMILY_ORDER.index(FAMILY_OF[s]))


def strengths(percentiles: pd.Series) -> tuple[pd.Series, pd.Series]:
    """A profile's strengths and weaknesses (`percentiles`: statistic -> percentile, higher always
    better): the statistics at `STRONG` or more, highest first, and at `WEAK` or less, lowest
    first, at most `MOST` of each."""
    high = percentiles.sort_values(ascending=False, kind="stable")
    low = percentiles.sort_values(kind="stable")
    return high[high >= STRONG].head(MOST), low[low <= WEAK].head(MOST)


def svg(fig: Figure) -> str:
    """`fig` as an SVG data URI, without a date, so that a report rebuilds the same."""
    out = io.BytesIO()
    with mpl.rc_context(FONT):
        fig.savefig(out, format="svg", bbox_inches="tight", pad_inches=0.04, dpi=200,
                    metadata={"Date": None, "Creator": None})  # fmt: skip
    plt.close(fig)
    return "data:image/svg+xml;base64," + base64.b64encode(out.getvalue()).decode("ascii")


def pizza(percentiles: pd.Series, compare: pd.Series | None = None) -> Figure:
    """A profile's percentiles (statistic -> percentile, in the order shown) as a pizza, slices
    coloured by family; with `compare`, another player's percentiles as dashed outlines."""
    statistics = list(percentiles.index)
    colors = [FAMILY_COLORS[FAMILY_OF[s]] for s in statistics]
    params = ["\n".join(textwrap.wrap(label(s), 18)) for s in statistics]
    baker = PyPizza(
        params=params, background_color="white", straight_line_color="white",
        straight_line_lw=1, last_circle_color=LINE, last_circle_lw=0.8, other_circle_lw=0,
        inner_circle_size=14,
    )  # fmt: skip
    kwargs = {}
    if compare is not None:
        kwargs = {
            "compare_values": [round(v) for v in compare[statistics]],
            "kwargs_compare": {"facecolor": "none", "edgecolor": INK, "linewidth": 1.1,
                               "linestyle": (0, (3, 2)), "zorder": 4},
            "kwargs_compare_values": {"color": "none", "zorder": 0, "bbox": {
                "facecolor": "none", "edgecolor": "none"}},
        }  # fmt: skip
    with mpl.rc_context(FONT):
        fig, _ = baker.make_pizza(
            [round(v) for v in percentiles], figsize=(5.2, 5.4), color_blank_space="same",
            slice_colors=colors, value_colors=["white"] * len(colors), value_bck_colors=colors,
            blank_alpha=0.16,
            kwargs_slices={"edgecolor": "white", "zorder": 2, "linewidth": 1.2},
            kwargs_params={"color": INK, "fontsize": 8, "va": "center"},
            kwargs_values={"color": "white", "fontsize": 8, "fontweight": "bold", "zorder": 5,
                           "bbox": {"edgecolor": "white", "boxstyle": "round,pad=0.25",
                                    "lw": 0.8}},
            **kwargs,
        )  # fmt: skip
    return fig


def touch_figure(shares: pd.Series, zone: float = ZONE) -> Figure:
    """Where a player touched the ball: `shares` of their touches by zone (`style.touch_map`, one
    row), smoothed, on a pitch attacking left to right with the player's side at the bottom."""
    pitch = Pitch(pitch_type="statsbomb", line_color=LINE, linewidth=0.7, line_zorder=2)
    with mpl.rc_context(FONT):
        fig, ax = pitch.draw(figsize=(5.2, 3.6))
        rows, cols = round(80 / zone), round(120 / zone)
        grid = pitch.bin_statistic(np.array([60.0]), np.array([40.0]), bins=(cols, rows))
        grid["statistic"] = gaussian_filter(
            shares.to_numpy(float).reshape(rows, cols), 0.8, mode="nearest"
        )
        pitch.heatmap(grid, ax=ax, cmap="Blues", edgecolors="none", rasterized=True)
        ax.annotate("", xy=(78, -3), xytext=(42, -3), annotation_clip=False,
                    arrowprops={"arrowstyle": "->", "color": MUTED, "lw": 1})  # fmt: skip
        ax.text(60, -5, "attacking", ha="center", va="bottom", fontsize=7.5, color=MUTED)
    return fig


def shot_figure(shots: pd.DataFrame) -> Figure:
    """A player's non-penalty shots (`x`, `y`, `xg`, `goal`) on half a pitch, sized by xG."""
    pitch = VerticalPitch(pitch_type="statsbomb", half=True, line_color=LINE, linewidth=0.7,
                          pad_bottom=-8)  # fmt: skip
    with mpl.rc_context(FONT):
        fig, ax = pitch.draw(figsize=(4.4, 3.6))
        for scored, face, edge in ((False, "white", OKABE_ITO[0]), (True, OKABE_ITO[5], INK)):
            d = shots[shots.goal == scored]
            pitch.scatter(d.x, d.y, s=20 + 700 * d.xg, color=face, edgecolors=edge,
                          linewidth=0.9, alpha=0.9, zorder=3 + scored, ax=ax)  # fmt: skip
        handles = [
            Line2D([], [], marker="o", ls="", markerfacecolor="white",
                   markeredgecolor=OKABE_ITO[0], label="No goal"),
            Line2D([], [], marker="o", ls="", markerfacecolor=OKABE_ITO[5],
                   markeredgecolor=INK, label="Goal"),
        ]  # fmt: skip
        ax.legend(handles=handles, loc="lower left", fontsize=7.5, frameon=False,
                  title="Size: xG", title_fontsize=7.5, handletextpad=0.2)  # fmt: skip
    return fig


def style_figure(
    scores: pd.DataFrame,
    names: Sequence[tuple[str, str]],
    regulars: Sequence,
    player: Hashable,
    reference: Hashable | None = None,
) -> Figure:
    """Where `player` stands on each style axis (`scores`: players x axes, in standard
    deviations), among the `regulars` (their spread in grey; the band their middle third, between
    the two ends), with `reference` as a ring."""
    on = scores.loc[scores.index.isin(regulars)]
    low, high = on.quantile([THIRD, 1 - THIRD]).to_numpy()
    n = len(scores.columns)
    with mpl.rc_context(FONT):
        fig, ax = plt.subplots(figsize=(4.6, 0.5 * n + 0.3))
        for i, axis in enumerate(scores.columns):
            y = n - 1 - i
            ax.axvspan(low[i], high[i], ymin=(y + 0.3) / n, ymax=(y + 0.7) / n,
                       color="#ECECEC", zorder=1)  # fmt: skip
            density, edges = np.histogram(on[axis].clip(-3, 3), bins=48, range=(-3, 3))
            density = gaussian_filter(density.astype(float), 1.5) / len(on) * 48 / 6
            centres = (edges[:-1] + edges[1:]) / 2
            ax.fill_between(centres, y - density * 0.5, y + density * 0.5, color="#C9C9C9",
                            linewidth=0, zorder=2)  # fmt: skip
            if reference is not None and reference != player:
                ax.plot(np.clip(scores.at[reference, axis], -3, 3), y, "o", markersize=9,
                        markerfacecolor="none", markeredgecolor=INK, markeredgewidth=1.3,
                        zorder=4)  # fmt: skip
            ax.plot(np.clip(scores.at[player, axis], -3, 3), y, "o", markersize=8,
                    color=OKABE_ITO[0], markeredgecolor="white", zorder=5)  # fmt: skip
            ax.text(-3.15, y, names[i][0], ha="right", va="center", fontsize=9, color=INK)
            ax.text(3.15, y, names[i][1], ha="left", va="center", fontsize=9, color=INK)
        ax.set_xlim(-3, 3)
        ax.set_ylim(-0.6, n - 0.4)
        ax.axis("off")
    return fig


def _money(euros: float) -> str:
    return f"€{euros / 1e6:.1f}M"


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _count(n: int, thing: str) -> str:
    return f"{n} {thing}" + ("" if n == 1 else "s")


def _day(d: date) -> str:
    return f"{d.day} {d:%B %Y}"


def slug(name: str) -> str:
    """A file name for a player: their name in lower-case ASCII, words joined by hyphens."""
    return re.sub(r"[^a-z0-9]+", "-", anyascii(name).lower()).strip("-")


def role(case: CaseStudy, player: Hashable) -> str:
    """Where a player stands in the case study."""
    if player == case.player:
        return "The player to replace"
    if player in case.shortlist.index:
        rank = list(case.shortlist.index).index(player) + 1
        pick = "the recommendation, " if player == case.recommended else ""
        return f"Shortlist: {pick}{_ordinal(rank)} of {len(case.shortlist)} by the gap"
    if player in case.long_list.index:
        row = case.long_list.loc[player]
        size = (case.long_list["list"] == row["list"]).sum()
        return f"Long list: {row['list'].lower()}, {_ordinal(row.place)} of {size} by distance"
    return "Candidate"


def report(con: duckdb.DuckDBPyConnection, cfg: Config, case: CaseStudy, player: int) -> dict:
    """What a player's page shows (the template's context): see the module's docstring."""
    who, ref = case.players, case.player
    me = who.loc[player]
    ref_name = who.name[ref].split()[-1]
    group_name = {g.code: g.name for g in cfg.comparison_groups}[case.group]
    pct = case.profile.pivot(index="player_id", columns="statistic", values="percentile")
    shrunk = case.profile.pivot(index="player_id", columns="statistic", values="shrunk")
    statistics = by_family(cfg.profiles[case.group])
    mine = pct.loc[player, statistics]
    regulars = who.index[who["list"] == "Regulars"]

    facts = [
        ("Team", f"{me.team} ({me.league})"),
        ("Age", f"{int(me.age)} on {_day(cfg.backtest.market_view)}"),
        ("Position", f"{me.position}, the position played most among the group's"),
        ("Foot", f"{'Left' if me.left_foot >= FOOT else 'Right'} ({me.left_foot:.0%} of the passes "
                 "played with either foot with the left)"),
        ("Minutes", f"{me.pool_minutes:,.0f} in the league, {me.minutes:,.0f} in the group's "
                    "positions"),
    ]  # fmt: skip

    ratio = float(np.exp(case.gap[player]))
    gap_pct = 100 * case.gap.rank(pct=True)[player]
    tiles = [
        {"label": "Market value", "value": _money(me.value),
         "note": f"Transfermarkt, latest on {_day(cfg.backtest.market_view)}"},
        {"label": "The model's value", "value": _money(me.value * ratio),
         "note": f"×{ratio:.2f} the market's; a gap larger than {gap_pct:.0f}% of the group's"},
    ]  # fmt: skip
    if player in case.fit.index:
        f = case.fit[player]
        tiles.append({
            "label": f"Fit to {case.club_name}", "value": f"{f:.2f}",
            "note": (f"{case.club_name}'s style without {ref_name}" if player == ref else
                     f"{case.club_name}'s style") + f" is nearer than {f:.0%} of the other clubs'",
        })  # fmt: skip
    if player != ref:
        row = case.found.loc[player]
        size = (case.found["list"] == row["list"]).sum()
        tiles.append({
            "label": f"Distance from {ref_name}", "value": f"{row.distance:.2f}",
            "note": f"the {_ordinal(row.place)} nearest of {size} "
                    f"{'regulars' if row['list'] == 'Regulars' else 'young players'}",
        })  # fmt: skip

    strong, weak = strengths(mine)
    listed = [
        [{"label": label(s), "percentile": round(p), "value": natural(s, shrunk.at[player, s])}
         for s, p in part.items()]
        for part in (strong, weak)
    ]  # fmt: skip
    profile = [
        {"family": FAMILY_OF[s], "color": FAMILY_COLORS[FAMILY_OF[s]], "label": label(s),
         "value": natural(s, shrunk.at[player, s]), "percentile": round(pct.at[player, s]),
         "reference": None if player == ref else round(pct.at[ref, s])}
        for s in statistics
    ]  # fmt: skip

    alike = None
    if player != ref:
        gaps = profile_gaps(pct, ref, [player]).iloc[0]
        alike = {
            "ends": in_common(case.ends, ref, [player]).iloc[0] or "none",
            "above": f"{LABELS[gaps.above]} (+{gaps.above_by:.0f} points)"
            if isinstance(gaps.above, str) else "none",
            "below": f"{LABELS[gaps.below]} ({gaps.below_by:.0f} points)"
            if isinstance(gaps.below, str) else "none",
        }  # fmt: skip
    names = cfg.roles.names[case.group]

    nearest = similar(case.points, who, player, n=NEAREST, teammates=True)
    nearest = nearest[nearest["list"] == "Regulars"]
    near = [{"name": r["name"], "team": r.team, "league": r.league, "distance": f"{r.distance:.2f}"}
            for _, r in nearest.iterrows()]  # fmt: skip

    notes = []
    if me["list"] == "Young":
        notes.append(
            f"Profiled from {me.pool_minutes:,.0f} league minutes as a player under "
            f"{cfg.compared.young_age:g} ({cfg.compared.minutes:,.0f} for the others): the numbers "
            "are pulled further towards the group's mean, the fewer the minutes."
        )
    if me.team_fifth == FIFTHS - 1:
        notes.append(
            f"{me.team} are in the fourth fifth of the 80 teams by goal difference per match, next "
            "to the strongest fifth the rules leave out as clubs that do not sell at their market "
            "value: whether the club would sell at it is for the scouts to judge."
        )
    table = league_table(con)
    at = table.loc[me.team_id]
    size = (table.competition_id == at.competition_id).sum()
    if at.place > size - RELEGATED:
        notes.append(
            f"{me.team} finished {_ordinal(int(at.place))} of {size} in {me.league}, in the "
            "relegation places."
        )

    shots = con.execute(f"""
        SELECT s.x, s.y, s.statsbomb_xg AS xg, s.outcome = 'Goal' AS goal
        FROM shots s JOIN matches m USING (match_id)
        WHERE m.scouting_pool AND s.player_id = {int(player)} AND s.shot_type <> 'Penalty'
    """).df()
    touches = touch_map(con, case.matches[case.matches.player_id == player], zone=ZONE)
    figures = {
        "pizza": svg(pizza(mine, None if player == ref else pct.loc[ref, statistics])),
        "touches": svg(touch_figure(touches.loc[player])),
        "shots": svg(shot_figure(shots)),
        "style": svg(style_figure(case.scores, names, regulars, player,
                                  None if player == ref else ref)),
    }  # fmt: skip
    return {
        "name": me["name"],
        "as_of": _day(cfg.backtest.market_view),
        "club": case.club_name,
        "reference": who.name[ref],
        "reference_short": ref_name,
        "is_reference": player == ref,
        "role": role(case, player),
        "recommended": player == case.recommended,
        "group": group_name,
        "group_size": len(pct),
        "regulars": len(regulars),
        "facts": facts,
        "tiles": tiles,
        "strengths": listed[0],
        "weaknesses": listed[1],
        "strong": STRONG,
        "weak": WEAK,
        "profile": profile,
        "families": [(f, FAMILY_COLORS[f]) for f in dict.fromkeys(map(FAMILY_OF.get, statistics))],
        "alike": alike,
        "ends": list(case.ends.loc[player].dropna()),
        "nearest": near,
        "shots": f"{_count(len(shots), 'non-penalty shot')}, {shots.xg.sum():.1f} xG, "
                 f"{_count(int(shots.goal.sum()), 'goal')}",
        "notes": notes,
        "figures": figures,
    }  # fmt: skip


def render(context: dict, template: str = "scouting_report.html.j2") -> str:
    """A page from its context (`report`)."""
    return TEMPLATES.get_template(template).render(**context)


def write_reports(
    con: duckdb.DuckDBPyConnection,
    cfg: Config,
    case: CaseStudy,
    signed: Sequence[int] = (),
    out: Path | None = None,
) -> list[Path]:
    """The reports of the shortlisted players, the player replaced and the players the club
    `signed` (as of the market view), and an index page, written to `out` (default
    `paths.scouting`). Returns the paths written, the index last."""
    out = cfg.paths.scouting if out is None else out
    out.mkdir(parents=True, exist_ok=True)
    players = list(dict.fromkeys([*case.shortlist.index, case.player, *signed]))
    rows, paths = [], []
    for player in players:
        context = report(con, cfg, case, player)
        path = out / f"{slug(context['name'])}.html"
        path.write_text(render(context), encoding="utf-8")
        paths.append(path)
        me = case.players.loc[player]
        signing = player in signed and player not in case.shortlist.index
        why = "The player the club signed" if signing else context["role"]
        rows.append({
            "name": context["name"], "file": path.name, "why": why, "team": me.team,
            "age": int(me.age), "value": _money(me.value),
            "ratio": f"×{np.exp(case.gap[player]):.2f}",
            "fit": f"{case.fit[player]:.2f}" if player in case.fit.index else "–",
            "distance": f"{case.found.distance[player]:.2f}" if player in case.found.index else "–",
            "recommended": player == case.recommended,
        })  # fmt: skip
    index = out / "index.html"
    index.write_text(render({
        "club": case.club_name, "reference": case.players.name[case.player],
        "fee": f"€{case.fee / 1e6:.0f}M", "sold_to": case.sold_to, "sold_on": _day(case.sold_on),
        "as_of": _day(cfg.backtest.market_view), "ceiling": f"€{case.ceiling / 1e6:.2f}M",
        "rows": rows,
    }, "scouting_index.html.j2"), encoding="utf-8")  # fmt: skip
    return [*paths, index]

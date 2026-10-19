import duckdb
import numpy as np
import pandas as pd
import pytest

from football_scouting.analysis.metrics import (
    FAMILIES,
    LABELS,
    PER_90,
    PROGRESSIVE_RULES,
    RATIOS,
    progressive,
    rates,
)
from football_scouting.config import load_config


def test_rates_per_90_and_ratios():
    columns = set(PER_90) | {c for num, den, _ in RATIOS.values() for c in (num, den)}
    sums = pd.DataFrame(0.0, index=[0, 1], columns=sorted(columns))
    sums["minutes"] = [180.0, 45.0]
    sums["shots"] = [4, 1]
    sums["xg"], sums["goals_minus_xg"] = [0.6, 0.1], [0.4, -0.1]  # 1 goal from 4 shots
    sums["passes"], sums["passes_completed"] = [50, 0], [40, 0]
    sums["touches"], sums["sum_x"] = [10, 0], [700, 0]
    sums["tackles_won"], sums["dribbler_duels"] = [3, 0], [4, 0]
    out = rates(sums)
    assert out["shots"].tolist() == [2.0, 2.0]
    assert out.loc[0, "pass_completion"] == pytest.approx(0.8)
    assert np.isnan(out.loc[1, "pass_completion"])  # no passes: ratio undefined, not 0
    assert out.loc[0, "mean_x"] == 70
    assert out.loc[0, "xg_per_shot"] == pytest.approx(0.15)
    assert out["finishing"].tolist() == pytest.approx([0.1, -0.1])
    assert out.loc[0, "dribblers_tackled"] == pytest.approx(0.75)


def test_every_metric_has_one_family():
    members = [m for ms in FAMILIES.values() for m in ms]
    assert sorted(members) == sorted(LABELS)


def test_profiles_name_distinct_metrics_for_every_outfield_group():
    cfg = load_config()
    assert sorted(cfg.profiles) == sorted(g.code for g in cfg.comparison_groups if g.code != "GK")
    for statistics in cfg.profiles.values():
        assert len(set(statistics)) == len(statistics) == 12
        assert set(statistics) <= set(LABELS)


def test_recording_statistics_are_per_90_counts():
    recording = load_config().recording
    assert set(recording.statistics) <= set(PER_90)
    assert {"interceptions", "pressures", "clearances"} <= set(recording.statistics)


# (x, y, end_x, end_y): progressive by rule ("10y" for a pass, "10y" for a carry, "zones",
# "25pct"). Zones thresholds in units: 34.3 within the own half, 17.1 across halfway, 11.4 in
# the other half.
MOVES = [
    ((50, 40, 61, 40), (True, True, False, False)),  # 11 forward across halfway
    ((10, 40, 50, 40), (False, False, True, True)),  # 40 forward in the own half
    ((100, 40, 108, 40), (False, False, False, True)),  # short, near the goal
    ((70, 10, 82, 30), (True, True, True, True)),  # 19 closer to goal in the other half
    ((55, 40, 75, 40), (True, True, True, True)),  # 20 forward across halfway
    ((90, 40, 50, 40), (False, False, False, False)),  # backwards
]


def test_progressive_rules():
    con = duckdb.connect()
    con.execute("CREATE TABLE m (x DOUBLE, y DOUBLE, end_x DOUBLE, end_y DOUBLE)")
    con.executemany("INSERT INTO m VALUES (?, ?, ?, ?)", [list(p) for p, _ in MOVES])
    rules = [progressive("10y", "pass"), progressive("10y", "carry")]
    rules += [progressive(r, "pass") for r in PROGRESSIVE_RULES[1:]]
    got = con.execute(f"SELECT {', '.join(rules)} FROM m").fetchall()
    assert [tuple(row) for row in got] == [expected for _, expected in MOVES]
    with pytest.raises(ValueError):
        progressive("5y", "pass")

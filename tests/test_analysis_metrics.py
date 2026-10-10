import numpy as np
import pandas as pd
import pytest

from football_scouting.analysis.metrics import PER_90, RATIOS, rates


def test_rates_per_90_and_ratios():
    columns = set(PER_90) | {c for num, den, _ in RATIOS.values() for c in (num, den)}
    sums = pd.DataFrame(0.0, index=[0, 1], columns=sorted(columns))
    sums["minutes"] = [180.0, 45.0]
    sums["shots"] = [4, 1]
    sums["passes"], sums["passes_completed"] = [50, 0], [40, 0]
    sums["touches"], sums["sum_x"] = [10, 0], [700, 0]
    out = rates(sums)
    assert out["shots"].tolist() == [2.0, 2.0]
    assert out.loc[0, "pass_completion"] == pytest.approx(0.8)
    assert np.isnan(out.loc[1, "pass_completion"])  # no passes: ratio undefined, not 0
    assert out.loc[0, "mean_x"] == 70

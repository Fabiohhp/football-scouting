import pandas as pd

from football_scouting.analysis.values import value_at

VALUATIONS = pd.DataFrame(
    {
        "player_id": [1, 1, 1, 2],
        "date": pd.to_datetime(["2016-02-09", "2016-06-01", "2016-08-01", "2015-01-05"]),
        "value": [10_000_000, 20_000_000, 30_000_000, 500_000],
        "club": ["Leicester City", "Leicester City", "Chelsea FC", "Carpi FC 1909"],
    }
)


def test_latest_valuation_on_or_before_the_date():
    out = value_at(VALUATIONS, "2016-06-30")
    assert out.loc[1, "value"] == 20_000_000 and out.loc[1, "club"] == "Leicester City"
    assert out.loc[1, "age_days"] == 29
    assert value_at(VALUATIONS, "2016-08-01").loc[1, "value"] == 30_000_000  # same day counts


def test_players_not_yet_or_no_longer_valued():
    assert list(value_at(VALUATIONS, "2015-12-31").index) == [2]  # player 1 not valued yet
    recent = value_at(VALUATIONS, "2016-06-30", max_age_days=365)
    assert list(recent.index) == [1]  # player 2's last value is 542 days old

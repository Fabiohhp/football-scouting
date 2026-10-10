import duckdb
import pandas as pd
import pytest

from football_scouting.model.transfermarkt_tables import fill_dates_of_birth, load_dob_overrides

PLAYERS = (
    "SELECT * FROM (VALUES (1, DATE '1990-01-01'), (2, NULL::DATE)) t(player_id, date_of_birth)"
)


def overrides(*rows):
    df = pd.DataFrame(rows, columns=["tm_player_id", "date_of_birth", "source"])
    return df.astype({"date_of_birth": "datetime64[s]"})


def test_fills_only_missing_dates():
    con = duckdb.connect()
    sql = fill_dates_of_birth(con, PLAYERS, overrides((2, "1986-04-16", "test")))
    out = dict(con.execute(f"SELECT player_id, date_of_birth FROM ({sql})").fetchall())
    assert str(out[1]) == "1990-01-01" and str(out[2]) == "1986-04-16"


@pytest.mark.parametrize("player", [1, 3])  # already dated, unknown
def test_rejects_stale_or_unknown_overrides(player):
    with pytest.raises(ValueError, match="unknown or already dated"):
        fill_dates_of_birth(duckdb.connect(), PLAYERS, overrides((player, "1986-04-16", "x")))


def test_project_overrides_file_parses():
    df = load_dob_overrides()
    assert df["tm_player_id"].is_unique and df["source"].str.len().gt(0).all()

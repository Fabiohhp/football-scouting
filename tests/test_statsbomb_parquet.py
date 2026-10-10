import json

import duckdb
import pytest

from football_scouting.ingest.statsbomb_parquet import (
    copy_json_to_parquet,
    infer_columns,
    json_key_paths,
    keep_strings,
    table_paths,
)

# Two "matches" with heterogeneous event keys, a UUID-like id and time-like strings.
EVENTS = {
    101: [
        {
            "id": "8f1b6a4e-1111-4c6b-9e0a-0d7f5c1a2b3c",
            "index": 1,
            "timestamp": "00:00:00.000",
            "type": {"id": 35, "name": "Starting XI"},
            "tactics": {"lineup": [{"player": {"id": 1, "name": "A"}, "jersey_number": 9}]},
        },
        {
            "id": "8f1b6a4e-2222-4c6b-9e0a-0d7f5c1a2b3c",
            "index": 2,
            "timestamp": "00:00:01.500",
            "type": {"id": 30, "name": "Pass"},
            "location": [60.0, 40.0],
            "pass": {"length": 12.5, "end_location": [70.0, 35.0]},
        },
    ],
    102: [
        {
            "id": "8f1b6a4e-3333-4c6b-9e0a-0d7f5c1a2b3c",
            "index": 1,
            "timestamp": "00:10:00.000",
            "type": {"id": 16, "name": "Shot"},
            "shot": {"statsbomb_xg": 0.07, "key_pass_id": "8f1b6a4e-2222-4c6b-9e0a-0d7f5c1a2b3c"},
        }
    ],
}


@pytest.mark.parametrize(
    ("detected", "expected"),
    [
        ("UUID", "VARCHAR"),
        ("TIME", "VARCHAR"),
        ("UUID[]", "VARCHAR[]"),
        ("STRUCT(id UUID, ts TIMESTAMP, d DATE)", "STRUCT(id VARCHAR, ts VARCHAR, d VARCHAR)"),
        ('STRUCT("time" VARCHAR, period BIGINT)', 'STRUCT("time" VARCHAR, period BIGINT)'),
        ("DOUBLE[]", "DOUBLE[]"),
    ],
)
def test_keep_strings(detected, expected):
    assert keep_strings(detected) == expected


def test_json_key_paths_walks_dicts_and_lists():
    obj = {"a": 1, "b": {"c": [1, 2]}, "d": [{"e": {"f": 1}}, {"g": 2}]}
    assert json_key_paths(obj) == {"a", "b", "b.c", "d", "d[].e", "d[].e.f", "d[].g"}


@pytest.fixture
def event_files(tmp_path):
    files = []
    for match_id, rows in EVENTS.items():
        f = tmp_path / "events" / f"{match_id}.json"
        f.parent.mkdir(exist_ok=True)
        f.write_text(json.dumps(rows))
        files.append(f)
    return files


def test_parquet_copy_is_faithful(tmp_path, event_files):
    con = duckdb.connect()
    columns = infer_columns(con, event_files)
    assert columns["id"] == "VARCHAR"
    assert columns["timestamp"] == "VARCHAR"

    out = tmp_path / "out" / "events.parquet"
    n = copy_json_to_parquet(
        con, event_files, columns, out, extra_select="7 AS competition_id, ", with_match_id=True
    )
    assert n == 3
    assert not out.with_name(out.name + ".part").exists()

    rows = con.execute(
        f"SELECT competition_id, match_id, id, timestamp, shot.key_pass_id "
        f"FROM read_parquet('{out}')"
    ).fetchall()
    assert [(r[0], r[1]) for r in rows] == [(7, 101), (7, 101), (7, 102)]
    assert [r[2] for r in rows] == [e["id"] for es in EVENTS.values() for e in es]
    assert rows[0][3] == "00:00:00.000"
    assert rows[2][4] == "8f1b6a4e-2222-4c6b-9e0a-0d7f5c1a2b3c"

    json_paths = set().union(*(json_key_paths(e) for es in EVENTS.values() for e in es))
    assert table_paths(con, str(out)) == json_paths | {"competition_id", "match_id"}

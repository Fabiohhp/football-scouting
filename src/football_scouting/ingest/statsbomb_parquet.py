"""Convert cached StatsBomb raw JSON to Parquet (interim layer) with DuckDB.

The interim layer is a faithful copy of the raw JSON: one Parquet row per element of each JSON
array, nested objects kept as STRUCT/LIST columns, plus `match_id` (taken from the file name)
and `competition_id` / `season_id`. No cleaning or renaming happens here (that is Phase 2).

Two details keep the copy faithful:
- The schema is inferred over *all* files, not a sample: event keys vary by event type, and a
  sample can miss rare fields.
- DuckDB auto-detects strings that look like UUIDs, times or dates and converts them (event
  `id` would become UUID, `timestamp` TIME). Those types are mapped back to VARCHAR so values
  stay exactly as in the JSON.

Outputs, under `<interim>/statsbomb/`:
    competitions.parquet, matches.parquet,
    lineups/<competition_id>_<season_id>.parquet, events/<competition_id>_<season_id>.parquet
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import duckdb
from duckdb.sqltypes import DuckDBPyType

from football_scouting.config import Competition, Config
from football_scouting.ingest.statsbomb import raw_dir

log = logging.getLogger(__name__)

# Types DuckDB may auto-detect from JSON strings. Upper-case match only: field names in
# StatsBomb data are lower-case, so a field called e.g. "time" is never rewritten.
_DETECTED_STRING_TYPES = re.compile(r"\b(?:TIMESTAMP WITH TIME ZONE|TIMESTAMP|TIME|DATE|UUID)\b")
_JSON_TYPE = re.compile(r"\bJSON\b")

# JSON reader options shared by inference and conversion. MAP inference is disabled so sparse
# nested objects (e.g. `pass`, with many optional keys) stay STRUCTs with named fields.
_READ_OPTIONS = "format = 'array', map_inference_threshold = -1, field_appearance_threshold = 0"


def interim_dir(cfg: Config) -> Path:
    return cfg.paths.interim / "statsbomb"


def match_table_path(cfg: Config, directory: str, comp: Competition) -> Path:
    """Parquet file for a per-match directory (events, lineups) of one competition-season."""
    return interim_dir(cfg) / directory / f"{comp.competition_id}_{comp.season_id}.parquet"


def keep_strings(duckdb_type: str) -> str:
    """Rewrite auto-detected string-derived types (UUID, TIME, DATE, TIMESTAMP) to VARCHAR."""
    return _DETECTED_STRING_TYPES.sub("VARCHAR", duckdb_type)


def connect(cfg: Config, memory_limit: str = "3GB", threads: int = 4) -> duckdb.DuckDBPyConnection:
    """DuckDB connection with bounded memory. The JSON reader buffers whole files per thread
    outside `memory_limit`; with 12 threads peak RSS reached 4.9 GB, so threads are capped."""
    con = duckdb.connect()
    con.execute(f"SET threads = {threads}")
    tmp = cfg.paths.interim / ".duckdb_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET memory_limit = '{memory_limit}'")
    con.execute(f"SET temp_directory = '{tmp}'")
    return con


def _sql_list(items: Sequence[str]) -> str:
    return "[" + ", ".join("'" + s.replace("'", "''") + "'" for s in items) + "]"


def infer_columns(con: duckdb.DuckDBPyConnection, files: Sequence[Path]) -> dict[str, str]:
    """Infer one schema over all files ({column: DuckDB type}) with string types preserved."""
    rows = con.execute(
        f"DESCRIBE SELECT * FROM read_json({_sql_list([str(f) for f in files])}, "
        f"{_READ_OPTIONS}, union_by_name = true, sample_size = -1)"
    ).fetchall()
    columns = {name: keep_strings(dtype) for name, dtype, *_ in rows}
    maps = {c: t for c, t in columns.items() if "MAP(" in t}
    if maps:
        raise ValueError(f"Columns inferred as MAP: {maps}")
    # DuckDB types a field as JSON when it is null in every file or mixes value types. Store
    # those values as their JSON text (lossless) and say which columns are affected.
    json_cols = sorted(c for c, t in columns.items() if _JSON_TYPE.search(t))
    if json_cols:
        log.warning("JSON-typed fields (all-null or mixed) kept as JSON text in: %s", json_cols)
    return {c: _JSON_TYPE.sub("VARCHAR", t) for c, t in columns.items()}


def _columns_sql(columns: dict[str, str]) -> str:
    return "{" + ", ".join(f"'{name}': '{dtype}'" for name, dtype in columns.items()) + "}"


def copy_json_to_parquet(
    con: duckdb.DuckDBPyConnection,
    files: Sequence[Path],
    columns: dict[str, str],
    out: Path,
    *,
    extra_select: str = "",
    with_match_id: bool = False,
) -> int:
    """Write the JSON arrays in `files` to one Parquet file atomically; return the row count.

    Rows keep file order and, within a file, array order.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    match_id = (
        r"CAST(regexp_extract(filename, '(\d+)\.json$', 1) AS BIGINT) AS match_id, "
        if with_match_id
        else ""
    )
    source = (
        f"read_json({_sql_list([str(f) for f in files])}, {_READ_OPTIONS}, "
        f"columns = {_columns_sql(columns)}, filename = true)"
    )
    con.execute(
        f"COPY (SELECT {extra_select}{match_id}* EXCLUDE (filename) FROM {source}) "
        f"TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)"
    )
    tmp.replace(out)
    return con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]


def match_files(cfg: Config, directory: str, match_ids: Sequence[int]) -> list[Path]:
    """Raw per-match files for `match_ids`, failing loudly if any is missing."""
    files = [raw_dir(cfg) / directory / f"{i}.json" for i in sorted(match_ids)]
    missing = [f for f in files if not f.exists()]
    if missing:
        raise FileNotFoundError(f"{len(missing)} {directory} files missing, e.g. {missing[0]}")
    return files


def json_key_paths(obj: Any, prefix: str = "") -> set[str]:
    """Every key path in a JSON value: `pass.end_location`, `tactics.lineup[].player.id`, ..."""
    paths: set[str] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else key
            paths.add(path)
            paths |= json_key_paths(value, path)
    elif isinstance(obj, list):
        for item in obj:
            paths |= json_key_paths(item, f"{prefix}[]")
    return paths


def column_paths(dtype: DuckDBPyType, prefix: str = "") -> set[str]:
    """Key paths of a DuckDB column type, in the same notation as `json_key_paths`."""
    paths: set[str] = set()
    if dtype.id == "struct":
        for name, child in dtype.children:
            path = f"{prefix}.{name}" if prefix else name
            paths.add(path)
            paths |= column_paths(child, path)
    elif dtype.id == "list":
        paths |= column_paths(dtype.child, f"{prefix}[]")
    return paths


def table_paths(con: duckdb.DuckDBPyConnection, parquet_glob: str) -> set[str]:
    """Key paths of all columns of a Parquet table."""
    rel = con.sql(f"SELECT * FROM read_parquet('{parquet_glob}') LIMIT 0")
    paths: set[str] = set()
    for name, dtype in zip(rel.columns, rel.types, strict=True):
        paths.add(name)
        paths |= column_paths(dtype, name)
    return paths

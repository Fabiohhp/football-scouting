from dataclasses import replace

import pytest

from football_scouting.config import Config, HttpConfig, Paths, load_config


@pytest.fixture
def tmp_config(tmp_path) -> Config:
    """Project config with data paths under tmp_path and no retry backoff."""
    cfg = load_config()
    paths = Paths(
        raw=tmp_path / "raw",
        interim=tmp_path / "interim",
        processed=tmp_path / "processed",
        figures=tmp_path / "figures",
        scouting=tmp_path / "scouting",
    )
    http = HttpConfig(timeout_seconds=5, max_retries=0, backoff_seconds=0, max_workers=2)
    return replace(cfg, paths=paths, http=http)

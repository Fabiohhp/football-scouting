"""Load the pipeline configuration (config/pipeline.yaml) into typed objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "pipeline.yaml"


@dataclass(frozen=True)
class Competition:
    name: str
    competition_id: int
    season_id: int
    expected_matches: int | None
    scouting_pool: bool
    transfermarkt_competition_id: str
    transfermarkt_season: int


@dataclass(frozen=True)
class StatsBombConfig:
    repo: str
    ref: str
    season_name: str
    competitions: tuple[Competition, ...]

    @property
    def raw_base_url(self) -> str:
        return f"https://raw.githubusercontent.com/{self.repo}/{self.ref}/data"


@dataclass(frozen=True)
class PositionGroup:
    code: str
    name: str
    position_ids: tuple[int, ...]


@dataclass(frozen=True)
class ComparisonGroup:
    code: str
    name: str
    members: tuple[str, ...]  # position group codes


@dataclass(frozen=True)
class TransfermarktConfig:
    base_url: str
    tables: tuple[str, ...]


@dataclass(frozen=True)
class BacktestConfig:
    market_view: date  # market values a club could see when deciding (a feature)
    outcome_base: date  # value growth is measured from here
    horizons: tuple[date, ...]  # dates outcomes are read on
    still_valued_days: int  # older latest valuation at a horizon: no longer valued


@dataclass(frozen=True)
class HttpConfig:
    timeout_seconds: float
    max_retries: int
    backoff_seconds: float
    max_workers: int


@dataclass(frozen=True)
class Paths:
    raw: Path
    interim: Path
    processed: Path
    figures: Path


@dataclass(frozen=True)
class Config:
    paths: Paths
    statsbomb: StatsBombConfig
    transfermarkt: TransfermarktConfig
    position_groups: tuple[PositionGroup, ...]
    comparison_groups: tuple[ComparisonGroup, ...]
    backtest: BacktestConfig
    http: HttpConfig

    def comparison_group_of(self) -> dict[str, str]:
        """{position group code: comparison group code}."""
        return {m: g.code for g in self.comparison_groups for m in g.members}


def _resolve(path: str, root: Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else root / p


def load_config(path: Path | str = DEFAULT_CONFIG_PATH, root: Path = PROJECT_ROOT) -> Config:
    with open(path, encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f)

    paths = Paths(**{k: _resolve(v, root) for k, v in raw["paths"].items()})
    sb = raw["statsbomb"]
    competitions = tuple(Competition(**c) for c in sb["competitions"])
    statsbomb = StatsBombConfig(
        repo=sb["repo"],
        ref=sb["ref"],
        season_name=sb["season_name"],
        competitions=competitions,
    )
    tm = raw["transfermarkt"]
    transfermarkt = TransfermarktConfig(base_url=tm["base_url"], tables=tuple(tm["tables"]))
    position_groups = tuple(
        PositionGroup(code=g["code"], name=g["name"], position_ids=tuple(g["position_ids"]))
        for g in raw["position_groups"]
    )
    comparison_groups = tuple(
        ComparisonGroup(code=g["code"], name=g["name"], members=tuple(g["members"]))
        for g in raw["comparison_groups"]
    )
    members = sorted(m for g in comparison_groups for m in g.members)
    if members != sorted(g.code for g in position_groups):
        raise ValueError("every position group must belong to exactly one comparison group")
    bt = raw["backtest"]
    backtest = BacktestConfig(
        market_view=bt["market_view"],
        outcome_base=bt["outcome_base"],
        horizons=tuple(bt["horizons"]),
        still_valued_days=bt["still_valued_days"],
    )
    if [backtest.market_view, backtest.outcome_base, *backtest.horizons] != sorted(
        {backtest.market_view, backtest.outcome_base, *backtest.horizons}
    ):
        raise ValueError("back-test dates must be distinct and in order")
    return Config(
        paths=paths,
        statsbomb=statsbomb,
        transfermarkt=transfermarkt,
        position_groups=position_groups,
        comparison_groups=comparison_groups,
        backtest=backtest,
        http=HttpConfig(**raw["http"]),
    )

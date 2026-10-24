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
class ComparedConfig:
    minutes: float  # real minutes in the pool
    young_minutes: float  # the same for players under `young_age`
    young_age: float  # years, on the back-test's market view


@dataclass(frozen=True)
class RecordingChange:
    competition_id: int
    since: date  # first match date recorded the new way


@dataclass(frozen=True)
class RecordingConfig:
    statistics: tuple[str, ...]  # compared within recording context (metric names)
    changes: tuple[RecordingChange, ...]


@dataclass(frozen=True)
class XtConfig:
    nx: int  # zones along the length of the pitch
    ny: int  # zones across it
    losses: bool  # ball losses end a chain like failed moves
    shot_value: str  # "xg" or "goal"
    credit: str  # a player's xT: "gained", "net" or "charged" (`analysis.xt.CREDITS`)


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
    compared: ComparedConfig
    profiles: dict[str, tuple[str, ...]]  # comparison group code -> statistics
    replaced: dict[str, dict[str, str]]  # group -> {possession-value number: statistic replaced}
    recording: RecordingConfig
    xt: XtConfig
    backtest: BacktestConfig
    http: HttpConfig

    def comparison_group_of(self) -> dict[str, str]:
        """{position group code: comparison group code}."""
        return {m: g.code for g in self.comparison_groups for m in g.members}

    @property
    def count_profiles(self) -> dict[str, tuple[str, ...]]:
        """The profiles as chosen from the event counts: `profiles` with `replaced` put back."""
        return {
            g: tuple(self.replaced.get(g, {}).get(m, m) for m in ms)
            for g, ms in self.profiles.items()
        }


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
    profiles = {g: tuple(ms) for g, ms in raw["profiles"].items()}
    if not set(profiles) <= {g.code for g in comparison_groups}:
        raise ValueError("profiles must be keyed by comparison group codes")
    replaced = {g: dict(r) for g, r in raw["replaced"].items()}
    if any(m not in profiles.get(g, ()) for g, r in replaced.items() for m in r):
        raise ValueError("replaced: each number must be in its group's profile")
    rec = raw["recording"]
    recording = RecordingConfig(
        statistics=tuple(rec["statistics"]),
        changes=tuple(RecordingChange(**c) for c in rec["changes"]),
    )
    changed = [c.competition_id for c in recording.changes]
    if len(set(changed)) < len(changed) or not set(changed) <= {
        c.competition_id for c in competitions
    }:
        raise ValueError("recording changes: at most one per configured competition")
    nx, ny = raw["xt"]["grid"]
    xt = XtConfig(nx=nx, ny=ny, **{k: raw["xt"][k] for k in ("losses", "shot_value", "credit")})
    if (
        xt.shot_value not in ("xg", "goal")
        or xt.credit not in ("gained", "net", "charged")
        or min(nx, ny) < 1
    ):
        raise ValueError(
            "xt: a grid of at least one zone, shot_value xg or goal, credit gained, net or charged"
        )
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
        compared=ComparedConfig(**raw["compared"]),
        profiles=profiles,
        replaced=replaced,
        recording=recording,
        xt=xt,
        backtest=backtest,
        http=HttpConfig(**raw["http"]),
    )

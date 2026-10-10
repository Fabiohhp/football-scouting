"""StatsBomb Open Data: competitions, match lists and the repository file inventory.

Raw files are mirrored under `<raw>/statsbomb/` with the same layout as the open-data repo
(`competitions.json`, `matches/<competition_id>/<season_id>.json`, `events/<match_id>.json`, ...).
"""

from __future__ import annotations

import itertools
import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from football_scouting.config import Competition, Config
from football_scouting.http import (
    download_file,
    fetch_json_cached,
    get,
    github_api_headers,
    is_cached,
)

log = logging.getLogger(__name__)

# Per-match files in the open-data repo, keyed by directory name.
MATCH_FILE_DIRS = ("events", "lineups", "three-sixty")


def raw_dir(cfg: Config) -> Path:
    return cfg.paths.raw / "statsbomb"


def load_competitions(client: httpx.Client, cfg: Config) -> list[dict[str, Any]]:
    url = f"{cfg.statsbomb.raw_base_url}/competitions.json"
    return fetch_json_cached(client, url, raw_dir(cfg) / "competitions.json", cfg.http)


def load_matches(client: httpx.Client, cfg: Config, comp: Competition) -> list[dict[str, Any]]:
    rel = f"matches/{comp.competition_id}/{comp.season_id}.json"
    url = f"{cfg.statsbomb.raw_base_url}/{rel}"
    return fetch_json_cached(client, url, raw_dir(cfg) / rel, cfg.http)


def team_names(match: dict[str, Any]) -> tuple[str, str]:
    return match["home_team"]["home_team_name"], match["away_team"]["away_team_name"]


@dataclass(frozen=True)
class FixtureCheck:
    teams: frozenset[str]
    missing: tuple[tuple[str, str], ...]  # (home, away) pairs absent from the match list
    duplicated: tuple[tuple[str, str], ...]  # (home, away) pairs present more than once


def check_fixtures(matches: list[dict[str, Any]]) -> FixtureCheck:
    """Compare a match list against a full double round-robin between the teams it contains."""
    pairs = Counter(team_names(m) for m in matches)
    teams = frozenset(t for pair in pairs for t in pair)
    expected = set(itertools.permutations(sorted(teams), 2))
    missing = tuple(sorted(expected - set(pairs)))
    duplicated = tuple(sorted(p for p, n in pairs.items() if n > 1))
    return FixtureCheck(teams=teams, missing=missing, duplicated=duplicated)


def teams_in_every_match(matches: list[dict[str, Any]]) -> set[str]:
    """Teams that play in every match of the list (e.g. a single-team season sample)."""
    sets = [set(team_names(m)) for m in matches]
    return set.intersection(*sets) if sets else set()


def _tree(client: httpx.Client, cfg: Config, sha: str) -> list[dict[str, Any]]:
    url = f"https://api.github.com/repos/{cfg.statsbomb.repo}/git/trees/{sha}"
    body = get(client, url, cfg.http, headers=github_api_headers()).json()
    if body.get("truncated"):
        raise RuntimeError(f"GitHub tree listing truncated for {url}")
    return body["tree"]


def list_match_files(client: httpx.Client, cfg: Config) -> dict[str, dict[int, int]]:
    """Return {directory: {match_id: size_in_bytes}} for the per-match directories at the ref.

    Uses the git trees API (blob sizes are the uncompressed file sizes), so nothing is downloaded.
    """
    root = {e["path"]: e["sha"] for e in _tree(client, cfg, cfg.statsbomb.ref)}
    data = {e["path"]: e["sha"] for e in _tree(client, cfg, root["data"])}
    out: dict[str, dict[int, int]] = {}
    for directory in MATCH_FILE_DIRS:
        entries = _tree(client, cfg, data[directory]) if directory in data else []
        out[directory] = {
            int(e["path"].removesuffix(".json")): e["size"]
            for e in entries
            if e["type"] == "blob" and e["path"].endswith(".json")
        }
    return out


@dataclass(frozen=True)
class FileTask:
    url: str
    dest: Path
    expected_size: int


def match_file_tasks(
    cfg: Config, match_ids: list[int], sizes: dict[str, dict[int, int]]
) -> list[FileTask]:
    """One task per per-match file that exists in the repo for the given matches."""
    return [
        FileTask(
            url=f"{cfg.statsbomb.raw_base_url}/{directory}/{match_id}.json",
            dest=raw_dir(cfg) / directory / f"{match_id}.json",
            expected_size=sizes[directory][match_id],
        )
        for directory in MATCH_FILE_DIRS
        for match_id in match_ids
        if match_id in sizes[directory]
    ]


@dataclass(frozen=True)
class DownloadSummary:
    downloaded: int
    skipped: int
    failed: tuple[str, ...]
    bytes_written: int


def download_tasks(client: httpx.Client, cfg: Config, tasks: list[FileTask]) -> DownloadSummary:
    """Download tasks in parallel; files already on disk with the expected size are skipped."""
    todo = [t for t in tasks if not is_cached(t.dest, t.expected_size)]
    skipped = len(tasks) - len(todo)
    log.info("%d files: %d already cached, %d to download", len(tasks), skipped, len(todo))
    downloaded, bytes_written, failed = 0, 0, []
    with ThreadPoolExecutor(max_workers=cfg.http.max_workers) as pool:
        futures = {
            pool.submit(
                download_file, client, t.url, t.dest, cfg.http, expected_size=t.expected_size
            ): t
            for t in todo
        }
        for i, future in enumerate(as_completed(futures), start=1):
            task = futures[future]
            try:
                future.result()
            except Exception as exc:
                log.error("failed %s: %s", task.url, exc)
                failed.append(task.url)
                continue
            downloaded += 1
            bytes_written += task.expected_size
            if i % 100 == 0 or i == len(todo):
                log.info("%d/%d done (%.0f MB written)", i, len(todo), bytes_written / 1024**2)
    return DownloadSummary(downloaded, skipped, tuple(sorted(failed)), bytes_written)

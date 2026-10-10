"""HTTP helpers: retries with exponential backoff and an on-disk JSON cache."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

from football_scouting.config import HttpConfig

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


def make_client(cfg: HttpConfig) -> httpx.Client:
    return httpx.Client(
        timeout=cfg.timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": "football-scouting/0.1"},
    )


def get(client: httpx.Client, url: str, cfg: HttpConfig, **kwargs: Any) -> httpx.Response:
    """GET with retries on transport errors and 429/5xx responses."""
    for attempt in range(cfg.max_retries + 1):
        try:
            resp = client.get(url, **kwargs)
            if resp.status_code not in RETRY_STATUS:
                resp.raise_for_status()
                return resp
            error: Exception = httpx.HTTPStatusError(
                f"HTTP {resp.status_code}", request=resp.request, response=resp
            )
        except httpx.TransportError as exc:
            error = exc
        if attempt == cfg.max_retries:
            raise error
        wait = cfg.backoff_seconds * 2**attempt
        log.warning("GET %s failed (%s); retry %d in %.1fs", url, error, attempt + 1, wait)
        time.sleep(wait)
    raise AssertionError("unreachable")


def github_api_headers() -> dict[str, str]:
    """Headers for api.github.com; uses GITHUB_TOKEN if set (raises the 60 req/h limit)."""
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def write_atomic(dest: Path, content: bytes) -> None:
    """Write via a temporary file + rename so an interrupted run never leaves a partial file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(content)
    tmp.replace(dest)


def fetch_json_cached(
    client: httpx.Client, url: str, dest: Path, cfg: HttpConfig, *, force: bool = False
) -> Any:
    """Return the JSON at `url`, downloading it to `dest` only if not already cached."""
    if dest.exists() and not force:
        return json.loads(dest.read_bytes())
    resp = get(client, url, cfg)
    data = resp.json()  # validate before writing to the cache
    write_atomic(dest, resp.content)
    return data


def is_cached(dest: Path, expected_size: int | None = None) -> bool:
    """True if `dest` exists (and has `expected_size` bytes, when given)."""
    return dest.exists() and (expected_size is None or dest.stat().st_size == expected_size)


def download_file(
    client: httpx.Client,
    url: str,
    dest: Path,
    cfg: HttpConfig,
    *,
    expected_size: int | None = None,
) -> httpx.Response:
    """Download `url` to `dest` atomically, checking the byte count when `expected_size` is given.

    The check runs on the decoded body, i.e. what is written to disk. Without `expected_size`,
    an unencoded response is checked against its Content-Length header.
    """
    resp = get(client, url, cfg)
    if expected_size is None and "content-encoding" not in resp.headers:
        length = resp.headers.get("content-length")
        expected_size = int(length) if length is not None else None
    if expected_size is not None and len(resp.content) != expected_size:
        raise ValueError(f"{url}: got {len(resp.content)} bytes, expected {expected_size}")
    write_atomic(dest, resp.content)
    return resp

"""Transfermarkt datasets (dcaribou/transfermarkt-datasets): gzipped CSV tables.

Raw files are stored as downloaded under `<raw>/transfermarkt/<table>.csv.gz`, with a
`manifest.json` recording where and when each file came from.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from football_scouting.config import Config
from football_scouting.http import download_file, is_cached, write_atomic

log = logging.getLogger(__name__)


def raw_dir(cfg: Config) -> Path:
    return cfg.paths.raw / "transfermarkt"


def manifest_path(cfg: Config) -> Path:
    return raw_dir(cfg) / "manifest.json"


def load_manifest(cfg: Config) -> dict[str, dict[str, Any]]:
    path = manifest_path(cfg)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def download_tables(client: httpx.Client, cfg: Config) -> dict[str, dict[str, Any]]:
    """Download each configured table once; return the manifest (one entry per table)."""
    manifest = load_manifest(cfg)
    for table in cfg.transfermarkt.tables:
        dest = raw_dir(cfg) / f"{table}.csv.gz"
        entry = manifest.get(table)
        if entry and is_cached(dest, entry["bytes"]):
            log.info("%s: cached (%d bytes)", table, entry["bytes"])
            continue
        url = f"{cfg.transfermarkt.base_url}/{table}.csv.gz"
        resp = download_file(client, url, dest, cfg.http)
        manifest[table] = {
            "url": url,
            "bytes": len(resp.content),
            "sha256": hashlib.sha256(resp.content).hexdigest(),
            "etag": resp.headers.get("etag"),
            "last_modified": resp.headers.get("last-modified"),
            "downloaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        write_atomic(manifest_path(cfg), json.dumps(manifest, indent=2).encode())
        log.info("%s: downloaded %d bytes", table, len(resp.content))
    return manifest

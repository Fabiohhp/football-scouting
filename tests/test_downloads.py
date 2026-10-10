import json

import httpx

from football_scouting.ingest.statsbomb import FileTask, download_tasks
from football_scouting.ingest.transfermarkt import download_tables, load_manifest


def _client(routes: dict[str, bytes], calls: list[str]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        body = routes.get(str(request.url))
        return httpx.Response(404) if body is None else httpx.Response(200, content=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_download_tasks_skips_cached_downloads_missing_and_rejects_wrong_size(tmp_config):
    raw = tmp_config.paths.raw
    cached = FileTask("https://x/cached.json", raw / "cached.json", 2)
    missing = FileTask("https://x/missing.json", raw / "missing.json", 2)
    truncated = FileTask("https://x/truncated.json", raw / "truncated.json", 10)
    cached.dest.parent.mkdir(parents=True)
    cached.dest.write_bytes(b"[]")
    calls: list[str] = []
    routes = {missing.url: b"[]", truncated.url: b"[]"}

    with _client(routes, calls) as client:
        summary = download_tasks(client, tmp_config, [cached, missing, truncated])

    assert (summary.downloaded, summary.skipped) == (1, 1)
    assert summary.failed == (truncated.url,)
    assert cached.url not in calls
    assert missing.dest.read_bytes() == b"[]"
    assert not truncated.dest.exists()
    assert not list(raw.glob("*.part"))


def test_transfermarkt_download_is_idempotent_and_records_manifest(tmp_config):
    base = tmp_config.transfermarkt.base_url
    routes = {f"{base}/{t}.csv.gz": f"{t}-bytes".encode() for t in tmp_config.transfermarkt.tables}
    calls: list[str] = []

    with _client(routes, calls) as client:
        first = download_tables(client, tmp_config)
        n_calls = len(calls)
        second = download_tables(client, tmp_config)

    assert n_calls == len(tmp_config.transfermarkt.tables)
    assert len(calls) == n_calls  # second run served entirely from disk
    assert first == second == load_manifest(tmp_config)
    entry = first["players"]
    assert entry["bytes"] == len(b"players-bytes")
    assert len(entry["sha256"]) == 64
    manifest_on_disk = json.loads(
        (tmp_config.paths.raw / "transfermarkt" / "manifest.json").read_text()
    )
    assert set(manifest_on_disk) == set(tmp_config.transfermarkt.tables)

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.models.url_rip import RipJob
from setvault_ingest_sources.base import Candidate


@pytest.fixture
async def seeded_youtube_ripjob():
    """Insert a non-failed youtube RipJob with external id `known1`, committed so
    the search endpoint's already-in-library query sees it. The autouse
    `_cleanup_rip_jobs` fixture wipes rip_jobs before/after each test."""
    init_engine(__import__("os").environ["TEST_DATABASE_URL"])
    async with session_factory()() as s:
        job = RipJob(
            source_url="https://youtu.be/known1",
            source_platform="youtube",
            source_external_id="known1",
            status="ready",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        s.add(job)
        await s.commit()
    yield


@pytest.fixture
async def seeded_soundcloud_ripjob():
    """Insert a non-failed soundcloud RipJob with no external id (matched by url),
    committed so the search endpoint's already-in-library query sees it."""
    init_engine(__import__("os").environ["TEST_DATABASE_URL"])
    async with session_factory()() as s:
        job = RipJob(
            source_url="https://soundcloud.com/dj-s/known-sc",
            source_platform="soundcloud",
            source_external_id=None,
            status="ready",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        s.add(job)
        await s.commit()
    yield


@pytest.mark.asyncio
async def test_search_requires_auth(client):
    r = await client.post("/api/ingest-sources/search", json={"q": "x"})
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_search_merges_and_flags_in_library(
    authed_admin_client, seeded_youtube_ripjob, seeded_soundcloud_ripjob
):
    cands = [
        Candidate("youtube", "known1", "YT known", "U", 60, None, "https://youtu.be/known1"),
        Candidate("youtube", "new2", "YT new", "U", 60, None, "https://youtu.be/new2"),
        Candidate("soundcloud", "dj-s/known-sc", "SC known", "U", 60, None,
                  "https://soundcloud.com/dj-s/known-sc"),
        Candidate("mixcloud", "dj-m/fresh", "MC fresh", "U", 60, None,
                  "https://www.mixcloud.com/dj-m/fresh/"),
    ]
    result = SimpleNamespace(candidates=cands, errored_kinds=["internet_archive"])
    with patch("setvault_web.api.ingest_sources.search_all_sources", return_value=result):
        r = await authed_admin_client.post("/api/ingest-sources/search", json={"q": "set"})
    assert r.status_code == 200
    body = r.json()
    items = {c["external_id"]: c for c in body["items"]}
    assert items["known1"]["already_in_library"] is True          # youtube id match
    assert items["new2"]["already_in_library"] is False
    assert items["dj-s/known-sc"]["already_in_library"] is True    # soundcloud url match
    assert items["dj-m/fresh"]["already_in_library"] is False
    assert body["errored_sources"] == ["internet_archive"]


@pytest.mark.asyncio
async def test_search_proxies_external_thumbnails(authed_admin_client):
    """Candidate thumbnails are rewritten to the same-origin signed proxy so the
    strict CSP can keep blocking third-party image hosts; a missing thumbnail
    passes through as null."""
    from urllib.parse import unquote

    cands = [
        Candidate("youtube", "thumbed", "YT", "U", 60,
                  "https://i.ytimg.com/vi/thumbed/hqdefault.jpg",
                  "https://youtu.be/thumbed"),
        Candidate("youtube", "nothumb", "YT2", "U", 60, None, "https://youtu.be/nothumb"),
    ]
    result = SimpleNamespace(candidates=cands, errored_kinds=[])
    with patch("setvault_web.api.ingest_sources.search_all_sources", return_value=result):
        r = await authed_admin_client.post("/api/ingest-sources/search", json={"q": "x"})
    assert r.status_code == 200
    items = {c["external_id"]: c for c in r.json()["items"]}
    proxied = items["thumbed"]["thumbnail_url"]
    assert proxied.startswith("/api/images/proxy")
    assert "i.ytimg.com/vi/thumbed/hqdefault.jpg" in unquote(proxied)
    assert items["nothumb"]["thumbnail_url"] is None


@pytest.mark.asyncio
async def test_admin_can_list_and_toggle_sources(authed_admin_client):
    r = await authed_admin_client.get("/api/admin/ingest-sources")
    assert r.status_code == 200
    kinds = {s["kind"] for s in r.json()["items"]}
    assert {"youtube", "soundcloud", "mixcloud", "internet_archive"} <= kinds
    r2 = await authed_admin_client.put(
        "/api/admin/ingest-sources/youtube", json={"enabled": False}
    )
    assert r2.status_code == 200 and r2.json()["enabled"] is False


@pytest.mark.asyncio
async def test_search_results_ranked_by_expected_quality(authed_admin_client):
    def mk(ext, tier):
        return Candidate("youtube", ext, ext, "U", 60, None, f"https://youtu.be/{ext}",
                         expected_tier=tier)

    cands = [mk("unk", None), mk("low", "low"), mk("ll", "lossless"),
             mk("hi", "high"), mk("unk2", None)]
    result = SimpleNamespace(candidates=cands, errored_kinds=[])
    with patch("setvault_web.api.ingest_sources.search_all_sources", return_value=result):
        r = await authed_admin_client.post("/api/ingest-sources/search", json={"q": "x"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert [i["external_id"] for i in items] == ["ll", "hi", "low", "unk", "unk2"]
    assert items[0]["expected_tier"] == "lossless" and items[3]["expected_tier"] is None

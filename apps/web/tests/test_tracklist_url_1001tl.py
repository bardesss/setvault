from pathlib import Path

import pytest
import respx
from httpx import Response

FIXTURE = Path(__file__).parent / "fixtures" / "tracklists" / "1001tracklists_sample.html"


@pytest.mark.asyncio
async def test_url_import_returns_403_when_flag_disabled(
    authed_admin_client, seeded_live_set, monkeypatch,
):
    monkeypatch.setenv("SETVAULT_ALLOW_1001TL_SCRAPE", "0")
    r = await authed_admin_client.post(
        f"/api/sets/{seeded_live_set['slug']}/tracklist/import",
        json={"kind": "url_1001tl", "payload": {"url": "https://www.1001tracklists.com/x/y"}},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_toggle_enables_url_import_without_env(
    authed_admin_client, seeded_live_set, monkeypatch,
):
    monkeypatch.setenv("SETVAULT_ALLOW_1001TL_SCRAPE", "0")
    r = await authed_admin_client.put("/api/admin/settings", json={"allow_1001tl_scrape": True})
    assert r.status_code == 200, r.text
    assert r.json()["allow_1001tl_scrape"] is True
    assert r.json()["allow_1001tl_scrape_env"] is False
    try:
        html = FIXTURE.read_text(encoding="utf-8")
        with respx.mock(assert_all_called=True) as mock:
            mock.get("https://www.1001tracklists.com/x/y").mock(
                return_value=Response(200, text=html)
            )
            r = await authed_admin_client.post(
                f"/api/sets/{seeded_live_set['slug']}/tracklist/import",
                json={"kind": "url_1001tl",
                      "payload": {"url": "https://www.1001tracklists.com/x/y"}},
            )
        assert r.status_code == 200, r.text
    finally:
        await authed_admin_client.put("/api/admin/settings", json={"allow_1001tl_scrape": False})


@pytest.mark.asyncio
async def test_url_import_parses_entries_when_flag_enabled(
    authed_admin_client, seeded_live_set, monkeypatch,
):
    monkeypatch.setenv("SETVAULT_ALLOW_1001TL_SCRAPE", "1")
    html = FIXTURE.read_text(encoding="utf-8")
    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://www.1001tracklists.com/x/y").mock(
            return_value=Response(200, text=html)
        )
        r = await authed_admin_client.post(
            f"/api/sets/{seeded_live_set['slug']}/tracklist/import",
            json={"kind": "url_1001tl", "payload": {"url": "https://www.1001tracklists.com/x/y"}},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "succeeded"
    assert len(body["parsed"]) >= 2
    assert body["parsed"][0]["start_seconds"] == 0


@pytest.mark.asyncio
async def test_url_import_rejects_non_1001tl_host(
    authed_admin_client, seeded_live_set, monkeypatch,
):
    monkeypatch.setenv("SETVAULT_ALLOW_1001TL_SCRAPE", "1")
    r = await authed_admin_client.post(
        f"/api/sets/{seeded_live_set['slug']}/tracklist/import",
        json={"kind": "url_1001tl", "payload": {"url": "https://evil.example.com/scrape"}},
    )
    assert r.status_code == 400

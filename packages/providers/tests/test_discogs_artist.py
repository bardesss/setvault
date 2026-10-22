import pytest
import respx
from httpx import Response
from setvault_providers.base import ArtistRef
from setvault_providers.discogs import DiscogsProvider


@pytest.mark.asyncio
async def test_discogs_enrich_needs_token():
    p = DiscogsProvider(token="t")
    p.token = ""
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(host="api.discogs.com")
        assert await p.enrich_artist(ArtistRef(name="X")) is None
    assert not route.called


@pytest.mark.asyncio
async def test_discogs_enrich_fields():
    detail = {
        "id": 45, "name": "Aphex Twin",
        "profile": "Born [a=Richard D. James]. See [url=http://x.com]site[/url] "
                   "and [b]bold[/b] [l=Warp].",
        "images": [{"uri": "https://img/a.jpg"}, {"uri": "https://img/b.jpg"}],
        "namevariations": ["AFX", "A.F.X."],
        "urls": ["https://aphextwin.warp.net", "https://soundcloud.com/aphex",
                 "https://aphex.bandcamp.com"],
    }
    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://api.discogs.com/database/search").mock(
            return_value=Response(200, json={"results": [
                {"id": 45, "title": "Aphex Twin"}]}))
        mock.get("https://api.discogs.com/artists/45").mock(
            return_value=Response(200, json=detail))
        r = await DiscogsProvider(token="t").enrich_artist(ArtistRef(name="Aphex Twin"))
    assert r is not None
    f = r.fields
    assert "[" not in f["bio"].value and "]" not in f["bio"].value
    assert "Richard D. James" in f["bio"].value and "bold" in f["bio"].value
    assert f["image_url"].value == "https://img/a.jpg"
    assert f["aliases"].value == ["AFX", "A.F.X."]
    assert f["external_ids"].value == {"discogs": "45"}
    s = f["socials"].value
    assert s["homepage"] == "https://aphextwin.warp.net"
    assert s["soundcloud"] == "https://soundcloud.com/aphex"
    assert s["bandcamp"] == "https://aphex.bandcamp.com"

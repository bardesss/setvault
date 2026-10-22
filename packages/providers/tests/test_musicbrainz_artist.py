import pytest
import respx
from httpx import Response
from setvault_providers.base import ArtistRef
from setvault_providers.musicbrainz import MusicBrainzProvider

MBID = "11111111-2222-3333-4444-555555555555"


def _p():
    return MusicBrainzProvider(user_agent="SetVault/test (test@example.com)")


def _rel(kind, url):
    return {"type": kind, "url": {"resource": url}}


@pytest.mark.asyncio
async def test_mb_enrich_by_stored_mbid():
    payload = {
        "id": MBID, "name": "Aphex Twin", "country": "GB",
        "aliases": [{"name": "AFX"}, {"name": "Polygon Window"}],
        "annotation": "British electronic musician.",
        "relations": [
            _rel("official homepage", "https://aphextwin.warp.net"),
            _rel("bandcamp", "https://aphex.bandcamp.com"),
            _rel("soundcloud", "https://soundcloud.com/aphex"),
            _rel("youtube", "https://youtube.com/aphex"),
            _rel("social network", "https://instagram.com/aphex"),
            _rel("discogs", "https://www.discogs.com/artist/45"),
        ],
    }
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"https://musicbrainz.org/ws/2/artist/{MBID}").mock(
            return_value=Response(200, json=payload))
        r = await _p().enrich_artist(
            ArtistRef(name="Aphex Twin", external_ids={"musicbrainz": MBID}))
    assert route.calls[0].request.url.params["inc"] == "aliases+url-rels+annotation"
    assert r is not None
    f = r.fields
    assert f["external_ids"].value == {"musicbrainz": MBID, "discogs": "45"}
    assert f["country"].value == "GB"
    assert f["aliases"].value == ["AFX", "Polygon Window"]
    assert f["bio"].value == "British electronic musician."
    s = f["socials"].value
    assert s["homepage"] == "https://aphextwin.warp.net"
    assert s["bandcamp"] == "https://aphex.bandcamp.com"
    assert s["soundcloud"] == "https://soundcloud.com/aphex"
    assert s["youtube"] == "https://youtube.com/aphex"
    assert s["instagram"] == "https://instagram.com/aphex"


def _search(name, score, aliases=()):
    return {"artists": [{"id": MBID, "name": name, "score": score,
                         "aliases": [{"name": a} for a in aliases]}]}


async def _run(search, ref_name):
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://musicbrainz.org/ws/2/artist").mock(
            return_value=Response(200, json=search))
        mock.get(f"https://musicbrainz.org/ws/2/artist/{MBID}").mock(
            return_value=Response(200, json={"id": MBID, "name": ref_name,
                                             "country": "NL"}))
        return await _p().enrich_artist(ArtistRef(name=ref_name))


@pytest.mark.asyncio
async def test_mb_search_requires_score_and_exact_name():
    assert await _run(_search("Âme ensemble", 95), "Ame") is None
    assert await _run(_search("Ame", 85), "Ame") is None
    r = await _run(_search("Different", 92, aliases=["AME"]), "Ame")
    assert r is not None
    assert r.fields["external_ids"].value["musicbrainz"] == MBID
    r = await _run(_search("ame", 99), "Ame")
    assert r is not None

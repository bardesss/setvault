import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from setvault_ingest_sources.bandcamp import BandcampSource
from setvault_ingest_sources.base import IngestSource, SourceError

_DATA = json.loads((Path(__file__).parent / "fixtures" / "bandcamp_search.json").read_text())


def _resp(body):
    r = MagicMock()
    r.json.return_value = body
    r.raise_for_status.return_value = None
    return r


def test_satisfies_protocol():
    src = BandcampSource()
    assert isinstance(src, IngestSource)
    assert (src.kind, src.name) == ("bandcamp", "Bandcamp")


def test_parses_album_and_track_results():
    with patch("setvault_ingest_sources.bandcamp.httpx.post", return_value=_resp(_DATA)) as p:
        out = BandcampSource().search("techno")
    # one request per filter (albums, tracks); duplicates collapse
    assert [c.kwargs["json"]["search_filter"] for c in p.call_args_list] == ["a", "t"]
    assert p.call_args_list[0].kwargs["json"]["search_text"] == "techno"
    urls = [c.webpage_url for c in out]
    assert urls[0] == "https://dlvmusic.bandcamp.com/album/rave-instructor-ep"
    assert "https://djfoo.bandcamp.com/track/some-track" in urls  # query dropped
    assert len(urls) == len(set(urls))
    first = out[0]
    assert (first.title, first.uploader) == ("Rave Instructor EP", "DLV")
    assert first.external_id == "a280824188"
    assert first.thumbnail_url == "https://f4.bcbits.com/img/3327689887_3.jpg"
    assert first.duration_seconds is None
    assert {c.expected_tier for c in out} == {"ok"}


def test_rejects_non_bandcamp_urls_and_other_types():
    with patch("setvault_ingest_sources.bandcamp.httpx.post", return_value=_resp(_DATA)):
        out = BandcampSource().search("techno")
    assert not any("evil.example.com" in c.webpage_url for c in out)
    assert not any(c.title == "A Band" for c in out)  # type "b" skipped


def test_respects_limit():
    with patch("setvault_ingest_sources.bandcamp.httpx.post", return_value=_resp(_DATA)):
        assert len(BandcampSource().search("techno", limit=2)) == 2


def test_http_error_raises_source_error():
    with patch("setvault_ingest_sources.bandcamp.httpx.post", side_effect=RuntimeError("boom")):
        with pytest.raises(SourceError):
            BandcampSource().search("foo")


def test_invalid_json_raises_source_error():
    r = _resp(None)
    r.json.side_effect = ValueError("not json")
    with patch("setvault_ingest_sources.bandcamp.httpx.post", return_value=r):
        with pytest.raises(SourceError):
            BandcampSource().search("foo")


def test_blank_query_returns_nothing():
    assert BandcampSource().search("  ") == []

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from setvault_ingest_sources.bandcamp import BandcampSource
from setvault_ingest_sources.base import IngestSource, SourceError

_HTML = (Path(__file__).parent / "fixtures" / "bandcamp_search.html").read_text()


def _resp(text):
    r = MagicMock()
    r.text = text
    r.raise_for_status.return_value = None
    return r


def test_satisfies_protocol():
    src = BandcampSource()
    assert isinstance(src, IngestSource)
    assert (src.kind, src.name) == ("bandcamp", "Bandcamp")


def test_parses_album_and_track_results():
    with patch("setvault_ingest_sources.bandcamp.httpx.get", return_value=_resp(_HTML)) as g:
        out = BandcampSource().search("foo")
    # one request per item type (album, track); duplicates collapse
    assert [c.kwargs["params"]["item_type"] for c in g.call_args_list] == ["a", "t"]
    assert [c.webpage_url for c in out] == [
        "https://djfoo.bandcamp.com/album/live-at-x",
        "https://bar.bandcamp.com/album/paid-one",
    ]
    first = out[0]
    assert first.title == "Live at X"
    assert first.uploader == "DJ Foo"
    assert first.duration_seconds == 74 * 60
    assert first.thumbnail_url == "https://f4.bcbits.com/img/a1_9.jpg"
    assert first.expected_tier == "lossless"  # marked free download
    assert out[1].expected_tier == "ok"


def test_rejects_non_bandcamp_urls():
    with patch("setvault_ingest_sources.bandcamp.httpx.get", return_value=_resp(_HTML)):
        out = BandcampSource().search("foo")
    assert not any("evil.example.com" in c.webpage_url for c in out)


def test_http_error_raises_source_error():
    with patch("setvault_ingest_sources.bandcamp.httpx.get", side_effect=RuntimeError("boom")):
        with pytest.raises(SourceError):
            BandcampSource().search("foo")


def test_blank_query_returns_nothing():
    assert BandcampSource().search("  ") == []

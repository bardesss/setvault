from unittest.mock import MagicMock, patch

import pytest
from setvault_ingest_sources.base import IngestSource, SourceError
from setvault_ingest_sources.internet_archive import InternetArchiveSource


def _resp(json_body):
    r = MagicMock()
    r.json.return_value = json_body
    r.raise_for_status.return_value = None
    return r


def test_ia_satisfies_protocol():
    src = InternetArchiveSource()
    assert isinstance(src, IngestSource)
    assert src.kind == "internet_archive"
    assert src.name == "Internet Archive"


def test_ia_maps_docs():
    body = {"response": {"docs": [
        {"identifier": "cool-set-1999", "title": "Cool Set", "creator": ["DJ A", "DJ B"]},
        {"title": "no identifier skipped"},  # skipped
    ]}}
    src = InternetArchiveSource()
    with patch("setvault_ingest_sources.internet_archive.httpx.get", return_value=_resp(body)) as g:
        out = src.search("cool set", limit=5)
    _, kwargs = g.call_args
    params = kwargs["params"]
    qval = params["q"] if isinstance(params, dict) else next(v for k, v in params if k == "q")
    assert "mediatype" in qval and "cool set" in qval
    assert len(out) == 1
    assert out[0].source_kind == "internet_archive"
    assert out[0].external_id == "cool-set-1999"
    assert out[0].title == "Cool Set"
    assert out[0].uploader == "DJ A"   # first of list
    assert out[0].duration_seconds is None
    assert out[0].thumbnail_url == "https://archive.org/services/img/cool-set-1999"
    assert out[0].webpage_url == "https://archive.org/details/cool-set-1999"


def test_ia_empty_query_returns_empty():
    assert InternetArchiveSource().search("") == []


def test_ia_raises_sourceerror():
    src = InternetArchiveSource()
    with patch(
        "setvault_ingest_sources.internet_archive.httpx.get",
        side_effect=RuntimeError("net"),
    ):
        with pytest.raises(SourceError):
            src.search("x")


@pytest.mark.parametrize(("fmt", "expected"), [
    (["VBR MP3", "24bit Flac"], True),
    (["FLAC"], True),
    ("Flac", True),  # a single format comes back as a plain string
    ("VBR MP3", False),
    (["VBR MP3", "Ogg Vorbis"], False),
    ([], False),
    (None, False),
    (7, False),  # unexpected shapes must not raise
    ({"name": "FLAC"}, False),
    ([None, 3, "flac"], True),
])
def test_has_flac_tolerates_any_shape(fmt, expected):
    from setvault_ingest_sources.internet_archive import _has_flac

    assert _has_flac({"format": fmt}) is expected

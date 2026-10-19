from unittest.mock import MagicMock, patch

from setvault_ingest_sources.base import Candidate
from setvault_ingest_sources.internet_archive import InternetArchiveSource
from setvault_ingest_sources.mixcloud import MixcloudSource
from setvault_ingest_sources.soundcloud import SoundCloudSource
from setvault_ingest_sources.youtube import YouTubeSource


class _FakeYDL:
    def __init__(self, info): self._info = info
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def extract_info(self, target, download=False): return self._info

_YDL = "setvault_ingest_sources.ytdlp_source.yt_dlp.YoutubeDL"


def _resp(body):
    r = MagicMock()
    r.json.return_value = body
    r.raise_for_status.return_value = None
    return r


def test_candidate_default_tier_is_none():
    c = Candidate("x", "1", "t", None, None, None, "https://x")
    assert c.expected_tier is None


def test_youtube_candidates_expect_ok():
    info = {"entries": [{"id": "v1", "title": "T", "url": "https://y/v1"}]}
    with patch(_YDL, return_value=_FakeYDL(info)):
        out = YouTubeSource().search("q")
    assert out[0].expected_tier == "ok"


def test_soundcloud_candidates_expect_ok():
    info = {"entries": [{"id": "s1", "title": "T", "url": "https://sc/s1"}]}
    with patch(_YDL, return_value=_FakeYDL(info)):
        out = SoundCloudSource().search("q")
    assert out[0].expected_tier == "ok"


def test_mixcloud_candidates_expect_ok():
    body = {"data": [{"key": "/u/set/", "url": "https://www.mixcloud.com/u/set/", "name": "S"}]}
    with patch("setvault_ingest_sources.mixcloud.httpx.get", return_value=_resp(body)):
        out = MixcloudSource().search("q")
    assert out[0].expected_tier == "ok"


def test_archive_flac_item_expects_lossless():
    body = {"response": {"docs": [
        {"identifier": "a", "title": "A", "format": ["Item Tile", "Flac", "VBR MP3"]},
        {"identifier": "b", "title": "B", "format": ["VBR MP3"]},
        {"identifier": "c", "title": "C"},
    ]}}
    with patch("setvault_ingest_sources.internet_archive.httpx.get", return_value=_resp(body)):
        out = InternetArchiveSource().search("q")
    assert [c.expected_tier for c in out] == ["lossless", None, None]

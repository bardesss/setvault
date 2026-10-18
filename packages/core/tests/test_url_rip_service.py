from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from setvault_core.services.url_rip import (
    UnsupportedUrlError,
    extract_platform_and_id,
    is_supported_url,
    probe_url,
    require_supported_url,
)


@pytest.mark.parametrize(("url", "expected_platform", "expected_id"), [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ", "youtube", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ?t=42", "youtube", "dQw4w9WgXcQ"),
    ("https://soundcloud.com/foo/bar", "soundcloud", None),
    ("https://www.mixcloud.com/foo/bar/", "mixcloud", None),
    ("https://archive.org/details/foo-bar", "internet_archive", "foo-bar"),
    ("https://random.example.com/x", "other", None),
])
def test_extract_platform_and_id(url: str, expected_platform: str, expected_id: str | None):
    platform, ext_id = extract_platform_and_id(url)
    assert platform == expected_platform
    assert ext_id == expected_id


@pytest.mark.parametrize("url", [
    # Allowed platforms
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ",
    "https://soundcloud.com/foo/bar",
    "https://www.mixcloud.com/foo/bar/",
    "https://archive.org/details/foo",
    "https://artist.bandcamp.com/track/x",
])
def test_is_supported_url_allows_platforms(url: str):
    assert is_supported_url(url) is True


@pytest.mark.parametrize("url", [
    # SSRF probes — must be rejected
    "http://169.254.169.254/latest/meta-data/",
    "http://localhost:6379/",
    "http://127.0.0.1:5432/",
    "http://10.0.0.5/",
    "file:///etc/passwd",
    "ftp://example.com/",
    "https://evil.example.com/x",
    "https://example.com.fake-bandcamp.com/",
])
def test_is_supported_url_rejects_non_allowlisted(url: str):
    assert is_supported_url(url) is False


def test_require_supported_url_raises_on_blocked():
    with pytest.raises(UnsupportedUrlError):
        require_supported_url("http://169.254.169.254/")


def test_probe_url_rejects_blocked_before_calling_ytdlp():
    """probe_url must enforce the allowlist before yt-dlp ever sees the URL."""
    with patch("setvault_core.services.url_rip.yt_dlp.YoutubeDL") as ydl:
        with pytest.raises(UnsupportedUrlError):
            probe_url("http://169.254.169.254/latest/meta-data/")
        ydl.assert_not_called()


def test_probe_url_returns_metadata():
    """probe_url() calls yt_dlp.YoutubeDL.extract_info(download=False) and
    normalises the result into a ProbeResult dataclass."""
    fake_info = {
        "id": "dQw4w9WgXcQ",
        "title": "Rick Astley - Never Gonna Give You Up",
        "uploader": "Rick Astley",
        "duration": 213,
        "thumbnail": "https://example.com/thumb.jpg",
        "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "extractor_key": "Youtube",
    }
    mock_ydl_ctx = MagicMock()
    mock_ydl_ctx.__enter__.return_value.extract_info.return_value = fake_info
    with patch("setvault_core.services.url_rip.yt_dlp.YoutubeDL", return_value=mock_ydl_ctx):
        result = probe_url("https://youtu.be/dQw4w9WgXcQ")
    assert result.platform == "youtube"
    assert result.external_id == "dQw4w9WgXcQ"
    assert result.title == "Rick Astley - Never Gonna Give You Up"
    assert result.duration_seconds == 213
    assert result.uploader == "Rick Astley"


def _probe_with(info: dict):
    ctx = MagicMock()
    ctx.__enter__.return_value.extract_info.return_value = info
    with patch("setvault_core.services.url_rip.yt_dlp.YoutubeDL", return_value=ctx) as ydl:
        try:
            return probe_url("https://www.youtube.com/watch?v=abc&list=PL123"), ydl
        except ValueError as exc:
            return exc, ydl


def test_probe_url_asks_for_the_single_video_not_the_playlist():
    """A watch?v=X&list=Y link must resolve to the video, not the playlist."""
    _, ydl = _probe_with({"id": "abc", "title": "t", "extractor_key": "Youtube"})
    opts = ydl.call_args.args[0]
    assert opts["noplaylist"] is True


@pytest.mark.parametrize(("info", "message"), [
    ({"_type": "playlist", "id": "PL123", "title": "p"}, "playlists"),
    ({"id": "abc", "title": "t", "is_live": True}, "live"),
    ({"id": "abc", "title": "t", "live_status": "is_upcoming"}, "live"),
])
def test_probe_url_rejects_playlists_and_live_streams(info: dict, message: str):
    result, _ = _probe_with(info)
    assert isinstance(result, ValueError)
    assert message in str(result)


async def test_submit_rip_probes_off_the_event_loop(monkeypatch):
    """yt-dlp's probe blocks for seconds; it must not run on the loop thread."""
    import threading
    from unittest.mock import AsyncMock

    from setvault_core.services import url_rip

    loop_thread = threading.current_thread()
    seen: list[threading.Thread] = []

    def _fake_probe(url):
        seen.append(threading.current_thread())
        return url_rip.ProbeResult(
            platform="soundcloud", external_id=None, title="t", duration_seconds=None,
            uploader=None, thumbnail_url=None, webpage_url=url, raw={},
        )

    monkeypatch.setattr(url_rip, "probe_url", _fake_probe)
    session = MagicMock()
    session.flush = AsyncMock()

    await url_rip.submit_rip(session, user_id=None, url="https://soundcloud.com/a/b")

    assert seen and seen[0] is not loop_thread

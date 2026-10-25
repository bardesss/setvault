"""YouTube cookies for yt-dlp: validation, storage and the per-call option."""
from __future__ import annotations

import os
import stat
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from setvault_core.services import ytdlp_cookies
from setvault_core.services.ytdlp_cookies import (
    InvalidCookiesError,
    cookies_path,
    cookies_status,
    remove_cookies,
    save_cookies,
    validate_cookies,
    ytdlp_cookie_opts,
)

GOOD = (
    b"# Netscape HTTP Cookie File\n"
    b"# This is a generated file! Do not edit.\n"
    b"\n"
    b".youtube.com\tTRUE\t/\tTRUE\t1893456000\tSID\tabc\n"
    b"#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t1893456000\t__Secure-3PSID\tdef\n"
    b".google.com\tTRUE\t/\tTRUE\t1893456000\tNID\tghi\n"
)


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SETVAULT_CONFIG_PATH", str(tmp_path))
    return tmp_path


def test_path_lives_in_the_config_volume(config_dir):
    assert cookies_path() == config_dir / "youtube-cookies.txt"


def test_path_defaults_to_srv_config(monkeypatch):
    monkeypatch.delenv("SETVAULT_CONFIG_PATH", raising=False)
    assert cookies_path() == Path("/srv/config/youtube-cookies.txt")


def test_validate_counts_youtube_lines():
    assert validate_cookies(GOOD) == 2


def test_validate_accepts_headerless_tab_separated_lines():
    assert validate_cookies(b".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tabc\r\n") == 1


@pytest.mark.parametrize("data", [
    b"",
    b"# Netscape HTTP Cookie File\n",                      # header, no cookies
    b"not a cookies file\n",
    b'{"cookies": []}',
    b".youtube.com\tTRUE\t/\tTRUE\t0\tSID\n",               # 6 fields
    b".google.com\tTRUE\t/\tTRUE\t0\tNID\tx\n",             # no YouTube cookies
    b".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tabc\x00\n",      # binary
    b"\xff\xfe\x00\x00",
])
def test_validate_rejects_other_input(data):
    with pytest.raises(InvalidCookiesError):
        validate_cookies(data)


def test_validate_rejects_oversized_input():
    line = b".youtube.com\tTRUE\t/\tTRUE\t0\tSID\t" + b"a" * 100 + b"\n"
    with pytest.raises(InvalidCookiesError):
        validate_cookies(line * (ytdlp_cookies.MAX_COOKIES_BYTES // len(line) + 1))


def test_status_without_a_file(config_dir):
    assert cookies_status() == {"set": False, "uploaded_at": None, "youtube_cookies": 0}


def test_save_writes_atomically_and_reports_status(config_dir):
    status = save_cookies(GOOD)
    path = config_dir / "youtube-cookies.txt"
    assert path.read_bytes() == GOOD
    assert list(config_dir.iterdir()) == [path]          # no tmp file left over
    if sys.platform != "win32":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert status["set"] is True
    assert status["youtube_cookies"] == 2
    assert status["uploaded_at"]
    assert cookies_status() == status


def test_save_creates_the_config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SETVAULT_CONFIG_PATH", str(tmp_path / "missing"))
    save_cookies(GOOD)
    assert (tmp_path / "missing" / "youtube-cookies.txt").is_file()


def test_save_rejects_invalid_input_without_touching_the_file(config_dir):
    save_cookies(GOOD)
    with pytest.raises(InvalidCookiesError):
        save_cookies(b"junk")
    assert (config_dir / "youtube-cookies.txt").read_bytes() == GOOD


def test_remove(config_dir):
    assert remove_cookies() is False
    save_cookies(GOOD)
    assert remove_cookies() is True
    assert not (config_dir / "youtube-cookies.txt").exists()


def test_opts_empty_without_a_file(config_dir):
    with ytdlp_cookie_opts() as opts:
        assert opts == {}


def test_opts_point_at_a_throwaway_copy(config_dir):
    """yt-dlp saves its cookie jar back to ``cookiefile`` on exit; it gets a
    copy so the uploaded file is never rewritten, and the copy is removed."""
    save_cookies(GOOD)
    with ytdlp_cookie_opts() as opts:
        copy = Path(opts["cookiefile"])
        assert copy != cookies_path()
        assert copy.read_bytes() == GOOD
        copy.write_text("rewritten by yt-dlp")
    assert not copy.exists()
    assert cookies_path().read_bytes() == GOOD


# --- every yt-dlp call site passes the cookies ------------------------------

def _ctx(info):
    ctx = MagicMock()
    ctx.__enter__.return_value.extract_info.return_value = info
    return ctx


def _seen_cookiefile(ydl) -> str | None:
    return ydl.call_args.args[0].get("cookiefile")


def test_probe_passes_the_cookies(config_dir):
    from setvault_core.services.url_rip import probe_url

    save_cookies(GOOD)
    seen: list[bytes] = []

    def _ydl(opts):
        seen.append(Path(opts["cookiefile"]).read_bytes())
        return _ctx({"id": "abc", "title": "t", "extractor_key": "Youtube"})

    with patch("setvault_core.services.url_rip.yt_dlp.YoutubeDL", side_effect=_ydl):
        probe_url("https://www.youtube.com/watch?v=abc")
    assert seen == [GOOD]


def test_probe_without_cookies_passes_none(config_dir):
    from setvault_core.services.url_rip import probe_url

    ctx = _ctx({"id": "abc", "title": "t", "extractor_key": "Youtube"})
    with patch("setvault_core.services.url_rip.yt_dlp.YoutubeDL", return_value=ctx) as ydl:
        probe_url("https://www.youtube.com/watch?v=abc")
    assert _seen_cookiefile(ydl) is None


async def test_download_passes_the_cookies(config_dir, tmp_path):
    from setvault_core.jobs.url_rip_job import _download

    save_cookies(GOOD)
    out = tmp_path / "x.opus"
    out.write_bytes(b"x")
    seen: list[bytes] = []

    def _ydl(opts):
        seen.append(Path(opts["cookiefile"]).read_bytes())
        return _ctx({"filepath": str(out)})

    job = SimpleNamespace(id=uuid.uuid4(), source_url="https://www.youtube.com/watch?v=a")
    with patch("yt_dlp.YoutubeDL", side_effect=_ydl):
        assert await _download(job, tmp_path) == out
    assert seen == [GOOD]


def test_search_passes_the_cookies(config_dir):
    from setvault_ingest_sources.youtube import YouTubeSource

    save_cookies(GOOD)
    seen: list[bytes] = []

    def _ydl(opts):
        seen.append(Path(opts["cookiefile"]).read_bytes())
        return _ctx({"entries": []})

    with patch("setvault_ingest_sources.ytdlp_source.yt_dlp.YoutubeDL", side_effect=_ydl):
        assert YouTubeSource().search("dj set") == []
    assert seen == [GOOD]


# --- the bot-check hint -----------------------------------------------------

def _bot_check():
    from yt_dlp.utils import DownloadError

    ctx = MagicMock()
    ctx.__enter__.return_value.extract_info.side_effect = DownloadError(
        "ERROR: [youtube] abc: Sign in to confirm you're not a bot. "
        "Use --cookies-from-browser or --cookies for the authentication.",
    )
    return ctx


def test_bot_check_without_cookies_points_to_the_upload(config_dir):
    from setvault_core.services.url_rip import ProbeError, probe_url

    with patch("setvault_core.services.url_rip.yt_dlp.YoutubeDL", return_value=_bot_check()):
        with pytest.raises(ProbeError) as exc_info:
            probe_url("https://www.youtube.com/watch?v=abc")
    message = str(exc_info.value)
    assert message.startswith("[youtube] abc: Sign in to confirm")
    assert "Admin → Sources → YouTube cookies" in message


def test_bot_check_with_cookies_suggests_they_expired(config_dir):
    from setvault_core.services.url_rip import ProbeError, probe_url

    save_cookies(GOOD)
    with patch("setvault_core.services.url_rip.yt_dlp.YoutubeDL", return_value=_bot_check()):
        with pytest.raises(ProbeError) as exc_info:
            probe_url("https://www.youtube.com/watch?v=abc")
    assert "may have expired" in str(exc_info.value)


def test_save_is_owner_only_even_with_a_loose_umask(config_dir):
    if sys.platform == "win32":
        pytest.skip("POSIX modes")
    old = os.umask(0)
    try:
        save_cookies(GOOD)
    finally:
        os.umask(old)
    assert stat.S_IMODE(cookies_path().stat().st_mode) == 0o600

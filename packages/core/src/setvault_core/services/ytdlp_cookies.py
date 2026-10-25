"""YouTube cookies for yt-dlp, uploaded in Admin -> Sources.

YouTube answers datacenter / homelab IPs with "Sign in to confirm you're not a
bot"; yt-dlp gets past it with the cookies of a logged-in browser. The admin
uploads a Netscape ``cookies.txt``, stored as ``youtube-cookies.txt`` in the
config volume (``SETVAULT_CONFIG_PATH``: ``/srv/config``, or ``/data/config``
in the bundled image), owner-only. The upload time is the file's mtime and the
cookie count is re-read from the file, so no other state is kept.

Every ``yt_dlp.YoutubeDL`` call merges ``ytdlp_cookie_opts()``. yt-dlp saves
its cookie jar back to ``cookiefile`` when it closes, so each call gets a
throwaway copy: the uploaded file is only ever written by an upload.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_CONFIG_DIR = "/srv/config"
COOKIES_FILENAME = "youtube-cookies.txt"
MAX_COOKIES_BYTES = 1024 * 1024
_HTTPONLY_PREFIX = "#HttpOnly_"


class InvalidCookiesError(ValueError):
    """The upload isn't a Netscape cookies.txt with YouTube cookies."""


def cookies_path() -> Path:
    config_dir = os.environ.get("SETVAULT_CONFIG_PATH") or DEFAULT_CONFIG_DIR
    return Path(config_dir) / COOKIES_FILENAME


def validate_cookies(data: bytes) -> int:
    """The number of YouTube cookie lines in a Netscape cookies file.

    Comment lines (``#``, but not ``#HttpOnly_`` cookie lines) and blank lines
    are skipped; every other line must have the format's 7 tab-separated
    fields. Raises InvalidCookiesError for anything else, or for a file
    without youtube.com cookies (it would never pass the bot check).
    """
    if len(data) > MAX_COOKIES_BYTES:
        raise InvalidCookiesError(
            f"cookies file is larger than {MAX_COOKIES_BYTES // 1024} KB",
        )
    if b"\x00" in data:
        raise InvalidCookiesError("not a cookies.txt file (binary data)")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidCookiesError("not a cookies.txt file (not UTF-8 text)") from exc
    youtube = 0
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or (line.startswith("#") and not line.startswith(_HTTPONLY_PREFIX)):
            continue
        fields = raw.rstrip("\r\n").split("\t")
        if len(fields) != 7:
            raise InvalidCookiesError(
                f"line {lineno} is not a Netscape cookie line (7 tab-separated fields); "
                "export the cookies in Netscape / cookies.txt format",
            )
        domain = fields[0].removeprefix(_HTTPONLY_PREFIX).lstrip(".").lower()
        if domain == "youtube.com" or domain.endswith(".youtube.com"):
            youtube += 1
    if youtube == 0:
        raise InvalidCookiesError(
            "no youtube.com cookies found; export them from a browser that is "
            "logged in to YouTube",
        )
    return youtube


def cookies_status() -> dict:
    """Whether cookies are set, when they were uploaded and how many YouTube
    cookies they hold. Never the contents."""
    path = cookies_path()
    try:
        data = path.read_bytes()
        mtime = path.stat().st_mtime
    except OSError:
        return {"set": False, "uploaded_at": None, "youtube_cookies": 0}
    try:
        count = validate_cookies(data)
    except InvalidCookiesError:
        count = 0
    return {
        "set": True,
        "uploaded_at": datetime.fromtimestamp(mtime, UTC).isoformat(),
        "youtube_cookies": count,
    }


def has_cookies() -> bool:
    return cookies_path().is_file()


def save_cookies(data: bytes) -> dict:
    """Validate and store the upload (tmp file + rename, mode 0600)."""
    validate_cookies(data)
    path = cookies_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # mkstemp creates the file 0600 whatever the umask.
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{COOKIES_FILENAME}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with suppress(OSError):
            os.unlink(tmp)
        raise
    return cookies_status()


def remove_cookies() -> bool:
    """Delete the stored cookies; False when there were none."""
    try:
        cookies_path().unlink()
    except FileNotFoundError:
        return False
    return True


@contextmanager
def ytdlp_cookie_opts() -> Iterator[dict]:
    """``{"cookiefile": <copy>}`` for a ``YoutubeDL`` options dict while
    cookies are set, else ``{}``. The copy is deleted on exit."""
    path = cookies_path()
    if not path.is_file():
        yield {}
        return
    fd, tmp = tempfile.mkstemp(prefix="setvault-ytdlp-cookies-", suffix=".txt")
    try:
        with os.fdopen(fd, "wb") as dst, path.open("rb") as src:
            shutil.copyfileobj(src, dst)
    except FileNotFoundError:  # removed meanwhile
        os.unlink(tmp)
        yield {}
        return
    try:
        yield {"cookiefile": tmp}
    finally:
        with suppress(OSError):
            os.unlink(tmp)

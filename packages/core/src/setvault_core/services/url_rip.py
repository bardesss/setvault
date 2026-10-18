from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import yt_dlp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.models.url_rip import RipJob


class DuplicateRipError(Exception):
    """Raised when a RipJob already exists for the same (platform, external_id)."""

    def __init__(self, existing: RipJob):
        self.existing = existing
        super().__init__(f"rip already in progress: {existing.id}")


class UnsupportedUrlError(ValueError):
    """Raised when the URL's host isn't on the platform allowlist.

    Acts as an SSRF gate: yt-dlp's extract_info() will fetch arbitrary hosts,
    including internal services and cloud metadata endpoints, unless callers
    constrain the input to known platforms first.
    """


@dataclass
class ProbeResult:
    platform: str
    external_id: str | None
    title: str
    duration_seconds: int | None
    uploader: str | None
    thumbnail_url: str | None
    webpage_url: str
    raw: dict


_YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "music.youtube.com", "youtu.be",
}
_SOUNDCLOUD_HOSTS = {"soundcloud.com", "www.soundcloud.com", "m.soundcloud.com"}
_MIXCLOUD_HOSTS = {"mixcloud.com", "www.mixcloud.com"}
_INTERNET_ARCHIVE_HOSTS = {"archive.org", "www.archive.org"}
_BANDCAMP_RE = re.compile(r"\.bandcamp\.com$")


def _host(url: str) -> str:
    """Lowercased hostname with a trailing dot stripped, for allowlist checks."""
    return urlparse(url).hostname.rstrip(".").lower() if urlparse(url).hostname else ""


def is_supported_url(url: str) -> bool:
    """True iff the URL's scheme + host is on the platform allowlist.

    Used as an SSRF gate before any yt-dlp / network call. The allowlist matches
    the platforms whose IDs we know how to parse in extract_platform_and_id().
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = _host(url)
    if not host:
        return False
    if host in _YOUTUBE_HOSTS:
        return True
    if host in _SOUNDCLOUD_HOSTS:
        return True
    if host in _MIXCLOUD_HOSTS:
        return True
    if host in _INTERNET_ARCHIVE_HOSTS:
        return True
    if _BANDCAMP_RE.search(host):
        return True
    return False


def require_supported_url(url: str) -> None:
    """Raise UnsupportedUrlError if the URL fails the allowlist."""
    if not is_supported_url(url):
        raise UnsupportedUrlError("URL must point to a supported platform")


def extract_platform_and_id(url: str) -> tuple[str, str | None]:
    """Best-effort platform detection from URL alone. Returns (platform, external_id-or-None).

    For platforms without a stable URL-embedded ID (SoundCloud, Mixcloud, Bandcamp),
    returns None and the caller falls back to probe-time idempotency.
    """
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host in _YOUTUBE_HOSTS:
        if host == "youtu.be":
            ext_id = parsed.path.lstrip("/").split("/")[0] or None
        else:
            qs = parse_qs(parsed.query)
            ext_id = qs.get("v", [None])[0]
        return "youtube", ext_id
    if host in _SOUNDCLOUD_HOSTS:
        return "soundcloud", None
    if host in _MIXCLOUD_HOSTS:
        return "mixcloud", None
    if host in _INTERNET_ARCHIVE_HOSTS:
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "details":
            return "internet_archive", parts[1]
        return "internet_archive", None
    if _BANDCAMP_RE.search(host):
        return "bandcamp", None
    return "other", None


def probe_url(url: str) -> ProbeResult:
    """Run yt-dlp probe (no download) and normalise the result.

    SSRF gate: the URL must pass require_supported_url() first. yt-dlp will
    happily fetch arbitrary hosts (including internal services and cloud
    metadata endpoints) otherwise.
    """
    require_supported_url(url)
    # noplaylist: a watch?v=X&list=Y link (the norm when copying from a
    # playlist) would otherwise resolve to the whole playlist.
    ydl_opts = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "extract_flat": "in_playlist", "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if info is None:
        raise ValueError("yt-dlp returned no info")
    if info.get("_type") in {"playlist", "multi_video"}:
        raise ValueError("playlists aren't supported; submit the URL of a single set")
    if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming"}:
        # A live download only ends when the stream does.
        raise ValueError("live streams can't be ripped; submit the recording once it has ended")
    extractor = (info.get("extractor_key") or "").lower()
    platform_from_extractor = {
        "youtube": "youtube", "youtubetab": "youtube",
        "soundcloud": "soundcloud",
        "mixcloud": "mixcloud",
        "internetarchive": "internet_archive", "archiveorg": "internet_archive",
        "bandcamp": "bandcamp",
    }.get(extractor)
    if platform_from_extractor is None:
        platform_from_extractor, _ = extract_platform_and_id(info.get("webpage_url", url))
    return ProbeResult(
        platform=platform_from_extractor or "other",
        external_id=info.get("id"),
        title=info.get("title") or "(untitled)",
        duration_seconds=int(info["duration"]) if info.get("duration") else None,
        uploader=info.get("uploader"),
        thumbnail_url=info.get("thumbnail"),
        webpage_url=info.get("webpage_url", url),
        raw=info,
    )


async def find_existing_rip(
    session: AsyncSession, *, platform: str, external_id: str | None,
) -> RipJob | None:
    """Idempotency check: return an in-flight or recently-completed RipJob for the
    same (platform, external_id) if one exists."""
    if external_id is None:
        return None
    return (await session.execute(
        select(RipJob).where(
            RipJob.source_platform == platform,
            RipJob.source_external_id == external_id,
        ).order_by(RipJob.created_at.desc()).limit(1)
    )).scalar_one_or_none()


async def submit_rip(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    url: str,
) -> RipJob:
    """Create a RipJob row and return it. Raise DuplicateRipError if an active
    or recently-completed rip exists for the same (platform, external_id).

    The probe runs inline so the returned row carries metadata for the Jobs
    drawer. The actual download/transcode is enqueued separately by the caller
    (see jobs/url_rip_job.py).
    """
    url = url.strip()
    if not url:
        raise ValueError("url is empty")

    # SSRF gate before any network call (idempotency probe + yt-dlp probe).
    require_supported_url(url)

    pre_platform, pre_ext_id = extract_platform_and_id(url)
    if pre_ext_id:
        existing = await find_existing_rip(session, platform=pre_platform, external_id=pre_ext_id)
        if existing and existing.status != "failed":
            raise DuplicateRipError(existing)

    # yt-dlp's probe is blocking network I/O (seconds); keep it off the
    # event loop so one submit doesn't stall every other request.
    probed = await asyncio.to_thread(probe_url, url)

    if probed.external_id:
        existing = await find_existing_rip(
            session, platform=probed.platform, external_id=probed.external_id,
        )
        if existing and existing.status != "failed":
            raise DuplicateRipError(existing)

    job = RipJob(
        live_set_id=None,
        submitted_by=user_id,
        source_url=url,
        source_external_id=probed.external_id,
        source_platform=probed.platform,
        status="queued",
        progress_pct=0,
        probed_metadata={
            "title": probed.title,
            "uploader": probed.uploader,
            "duration": probed.duration_seconds,
            "thumbnail": probed.thumbnail_url,
            "webpage_url": probed.webpage_url,
        },
        ytdlp_version=yt_dlp.version.__version__,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(job)
    await session.flush()
    return job

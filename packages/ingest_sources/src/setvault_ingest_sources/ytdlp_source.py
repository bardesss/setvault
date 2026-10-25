from __future__ import annotations

from contextlib import nullcontext

import yt_dlp

from setvault_ingest_sources.base import Candidate, SourceError

try:
    # The YouTube cookies uploaded in Admin -> Sources. setvault-core is always
    # installed next to this package in SetVault, but isn't a dependency of it.
    from setvault_core.services.ytdlp_cookies import ytdlp_cookie_opts
except ImportError:  # pragma: no cover - standalone use
    def ytdlp_cookie_opts():
        return nullcontext({})


def _thumb(entry: dict) -> str | None:
    if entry.get("thumbnail"):
        return entry["thumbnail"]
    thumbs = entry.get("thumbnails") or []
    return thumbs[-1]["url"] if thumbs else None


class _YtDlpSearchSource:
    """Shared yt-dlp `<prefix>search{N}:` source. Subclasses set kind/name/search_prefix."""

    kind: str
    name: str
    search_prefix: str  # e.g. "ytsearch", "scsearch"

    def _fallback_url(self, ext_id: str) -> str | None:
        """URL to use when yt-dlp gives neither webpage_url nor url. Default: skip."""
        return None

    def search(self, query: str, *, limit: int = 20) -> list[Candidate]:
        query = query.strip()
        if not query:
            return []
        limit = max(1, min(limit, 50))
        opts = {"quiet": True, "no_warnings": True, "skip_download": True,
                "extract_flat": True, "default_search": self.search_prefix}
        try:
            with ytdlp_cookie_opts() as cookie_opts, \
                    yt_dlp.YoutubeDL({**opts, **cookie_opts}) as ydl:
                info = ydl.extract_info(f"{self.search_prefix}{limit}:{query}", download=False)
        except Exception as e:
            raise SourceError(f"{self.kind} search failed: {e}") from e
        out: list[Candidate] = []
        for e in (info or {}).get("entries", []) or []:
            ext_id = e.get("id")
            if not ext_id:
                continue
            url = e.get("webpage_url") or e.get("url") or self._fallback_url(ext_id)
            if not url:
                continue
            dur = e.get("duration")
            out.append(Candidate(
                source_kind=self.kind,
                external_id=ext_id,
                title=e.get("title") or "(untitled)",
                uploader=e.get("uploader") or e.get("channel"),
                duration_seconds=int(dur) if dur else None,
                thumbnail_url=_thumb(e),
                webpage_url=url,
                expected_tier="ok",  # best audio is ~130 kbps Opus/AAC
            ))
        return out

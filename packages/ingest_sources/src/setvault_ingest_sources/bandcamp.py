from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx

from setvault_ingest_sources.base import Candidate, SourceError

# The public JSON endpoint Bandcamp's own search box uses. The HTML search
# page answers HTTP clients with a bot challenge, so it isn't scraped.
_URL = "https://bandcamp.com/api/bcsearch_public_api/1/autocomplete_elastic"
_TIMEOUT = 15.0
_UA = "SetVault/1.0 (+https://github.com/Bardesss/setvault)"
_HOST_RE = re.compile(r"(^|\.)bandcamp\.com$")


def _parse(data: dict, limit: int) -> list[Candidate]:
    out: list[Candidate] = []
    for item in ((data.get("auto") or {}).get("results") or []):
        if item.get("type") not in ("a", "t"):
            continue
        raw = item.get("item_url_path")
        if not raw or item.get("id") is None:
            continue
        parsed = urlparse(str(raw))
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not _HOST_RE.search(host):
            continue
        img = item.get("img")
        out.append(Candidate(
            source_kind="bandcamp",
            external_id=f"{item['type']}{item['id']}",
            title=item.get("name") or "(untitled)",
            uploader=item.get("band_name"),
            duration_seconds=None,
            thumbnail_url=str(img) if img else None,
            webpage_url=f"https://{host}{parsed.path}",  # drop query/fragment
            # No free-download marker in this data, so never claim lossless.
            expected_tier="ok",
        ))
        if len(out) >= limit:
            break
    return out


class BandcampSource:
    kind = "bandcamp"
    name = "Bandcamp"

    def search(self, query: str, *, limit: int = 20) -> list[Candidate]:
        query = query.strip()
        if not query:
            return []
        limit = max(1, min(limit, 50))
        out: list[Candidate] = []
        seen: set[str] = set()
        try:
            for search_filter in ("a", "t"):
                r = httpx.post(
                    _URL,
                    json={
                        "search_text": query, "search_filter": search_filter,
                        "full_page": False, "fan_id": None,
                    },
                    headers={"User-Agent": _UA},
                    timeout=_TIMEOUT,
                )
                r.raise_for_status()
                for c in _parse(r.json(), limit):
                    if c.webpage_url not in seen:
                        seen.add(c.webpage_url)
                        out.append(c)
        except Exception as e:  # network / HTTP / parse -> domain error
            raise SourceError(f"bandcamp search failed: {e}") from e
        return out[:limit]

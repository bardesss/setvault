from __future__ import annotations

import httpx

from setvault_ingest_sources.base import Candidate, SourceError

_API = "https://api.mixcloud.com/search/"
_TIMEOUT = 10.0


class MixcloudSource:
    kind = "mixcloud"
    name = "Mixcloud"

    def search(self, query: str, *, limit: int = 20) -> list[Candidate]:
        query = query.strip()
        if not query:
            return []
        limit = max(1, min(limit, 50))
        try:
            r = httpx.get(
                _API,
                params={"q": query, "type": "cloudcast", "limit": limit},
                timeout=_TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:  # network / HTTP / parse -> domain error
            raise SourceError(f"mixcloud search failed: {e}") from e
        out: list[Candidate] = []
        for item in data.get("data", []) or []:
            key = item.get("key")
            url = item.get("url")
            if not key or not url:
                continue
            pics = item.get("pictures") or {}
            out.append(Candidate(
                source_kind="mixcloud",
                external_id=key.strip("/"),
                title=item.get("name") or "(untitled)",
                uploader=(item.get("user") or {}).get("name"),
                duration_seconds=item.get("audio_length"),
                thumbnail_url=pics.get("large") or pics.get("medium") or pics.get("thumbnail"),
                webpage_url=url,
                expected_tier="ok",
            ))
        return out

from __future__ import annotations

import httpx

from setvault_ingest_sources.base import Candidate, SourceError

_API = "https://archive.org/advancedsearch.php"
_TIMEOUT = 10.0


def _first(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _has_flac(doc: dict) -> bool:
    fmts = doc.get("format") or []
    if isinstance(fmts, str):
        fmts = [fmts]
    return any("flac" in str(f).lower() for f in fmts)


class InternetArchiveSource:
    kind = "internet_archive"
    name = "Internet Archive"

    def search(self, query: str, *, limit: int = 20) -> list[Candidate]:
        query = query.strip()
        if not query:
            return []
        limit = max(1, min(limit, 50))
        params = [
            ("q", f"({query}) AND mediatype:(audio)"),
            ("fl[]", "identifier"), ("fl[]", "title"), ("fl[]", "creator"), ("fl[]", "format"),
            ("rows", str(limit)), ("page", "1"), ("output", "json"),
        ]
        try:
            r = httpx.get(_API, params=params, timeout=_TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            raise SourceError(f"internet_archive search failed: {e}") from e
        out: list[Candidate] = []
        for doc in (data.get("response") or {}).get("docs", []) or []:
            ident = doc.get("identifier")
            if not ident:
                continue
            out.append(Candidate(
                source_kind="internet_archive",
                external_id=ident,
                title=_first(doc.get("title")) or ident,
                uploader=_first(doc.get("creator")),
                duration_seconds=None,
                thumbnail_url=f"https://archive.org/services/img/{ident}",
                webpage_url=f"https://archive.org/details/{ident}",
                expected_tier="lossless" if _has_flac(doc) else None,
            ))
        return out

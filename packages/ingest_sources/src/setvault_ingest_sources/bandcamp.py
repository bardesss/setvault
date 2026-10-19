from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from setvault_ingest_sources.base import Candidate, SourceError

_URL = "https://bandcamp.com/search"
_TIMEOUT = 15.0
_UA = "SetVault/1.0 (+https://github.com/Bardesss/setvault)"
_HOST_RE = re.compile(r"(^|\.)bandcamp\.com$")
# Result data that marks a free / name-your-price download. Search pages
# don't always carry one; absent a marker the candidate is just "ok".
_FREE_RE = re.compile(r"free download|name your price|name-your-price", re.I)


def _duration(text: str) -> int | None:
    m = re.search(r"(\d+):(\d{2})(?::(\d{2}))?", text)
    if m:
        a, b, c = int(m[1]), int(m[2]), m[3]
        return a * 3600 + b * 60 + int(c) if c is not None else a * 60 + b
    m = re.search(r"(\d+)\s*minute", text)
    return int(m[1]) * 60 if m else None


def _parse(html: str, limit: int) -> list[Candidate]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[Candidate] = []
    for li in soup.select("li.searchresult"):
        link = li.select_one(".heading a")
        if link is None or not link.get("href"):
            continue
        parsed = urlparse(str(link["href"]))
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not _HOST_RE.search(host):
            continue
        url = f"https://{host}{parsed.path}"  # drop tracking query/fragment
        sub = li.select_one(".subhead")
        sub_text = sub.get_text(" ", strip=True) if sub else ""
        m = re.search(r"\bby\s+(.+)$", sub_text)
        length = li.select_one(".length")
        img = li.select_one(".art img")
        out.append(Candidate(
            source_kind="bandcamp",
            external_id=f"{host}{parsed.path}",
            title=link.get_text(" ", strip=True) or "(untitled)",
            uploader=m[1].strip() if m else None,
            duration_seconds=_duration(length.get_text(" ", strip=True)) if length else None,
            thumbnail_url=str(img["src"]) if img is not None and img.get("src") else None,
            webpage_url=url,
            expected_tier="lossless" if _FREE_RE.search(li.get_text(" ", strip=True)) else "ok",
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
            for item_type in ("a", "t"):
                r = httpx.get(
                    _URL,
                    params={"q": query, "item_type": item_type},
                    headers={"User-Agent": _UA},
                    timeout=_TIMEOUT,
                    follow_redirects=True,
                )
                r.raise_for_status()
                for c in _parse(r.text, limit):
                    if c.webpage_url not in seen:
                        seen.add(c.webpage_url)
                        out.append(c)
        except Exception as e:  # network / HTTP / parse -> domain error
            raise SourceError(f"bandcamp search failed: {e}") from e
        return out[:limit]

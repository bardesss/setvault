from __future__ import annotations

import asyncio
import time
from typing import ClassVar
from urllib.parse import quote_plus, urlparse

import httpx

from setvault_providers.base import (
    ArtistRef,
    Capability,
    FieldValue,
    ProviderError,
    ProviderRateLimited,
    ProviderResult,
    TrackRef,
)

_SOCIAL_HOSTS = {
    "bandcamp.com": "bandcamp", "soundcloud.com": "soundcloud",
    "youtube.com": "youtube", "youtu.be": "youtube", "instagram.com": "instagram",
}
_MIN_SEARCH_SCORE = 90
_MIN_INTERVAL = 1.1  # MusicBrainz allows 1 request/second
_rate_lock = asyncio.Lock()
_last_request = 0.0
_sleep = asyncio.sleep
_clock = time.monotonic


async def _throttle() -> None:
    """Hold the lock until >= _MIN_INTERVAL has passed since the last request."""
    global _last_request
    async with _rate_lock:
        wait = _MIN_INTERVAL - (_clock() - _last_request)
        if wait > 0:
            await _sleep(wait)
        _last_request = _clock()


def _social_key(rel_type: str, url: str) -> str | None:
    if rel_type == "official homepage":
        return "homepage"
    host = (urlparse(url).hostname or "").lower()
    for dom, key in _SOCIAL_HOSTS.items():
        if host == dom or host.endswith("." + dom):
            return key
    return None


def _names(entry: dict) -> set[str]:
    out = {(entry.get("name") or "").casefold()}
    out.update((a.get("name") or "").casefold() for a in entry.get("aliases") or [])
    out.discard("")
    return out


class MusicBrainzProvider:
    kind = "musicbrainz"
    capabilities: ClassVar[set[Capability]] = {
        Capability.ENRICH_TRACK, Capability.ENRICH_RELEASE,
        Capability.ENRICH_ARTIST, Capability.LOOKUP_BY_ISRC,
    }

    def __init__(self, user_agent: str, base_url: str = "https://musicbrainz.org/ws/2"):
        if not user_agent:
            raise ValueError("MusicBrainz requires a user_agent per their ToS")
        self.user_agent = user_agent
        self.base_url = base_url

    async def _get(self, path: str, params: dict) -> dict:
        await _throttle()
        async with httpx.AsyncClient(
            timeout=15.0, headers={"User-Agent": self.user_agent}
        ) as c:
            r = await c.get(f"{self.base_url}/{path}", params={**params, "fmt": "json"})
        if r.status_code == 429:
            raise ProviderRateLimited("musicbrainz 429")
        if r.status_code != 200:
            raise ProviderError(f"musicbrainz {r.status_code}")
        return r.json()

    async def enrich_track(self, track: TrackRef) -> ProviderResult | None:
        if not track.title:
            return None
        q = f'recording:"{track.title}"'
        if track.primary_artist_name:
            q += f' AND artist:"{track.primary_artist_name}"'
        data = await self._get("recording", {"query": q, "limit": "1"})
        recs = data.get("recordings") or []
        if not recs:
            return None
        rec = recs[0]
        fields: dict[str, FieldValue] = {}
        if rec.get("isrcs"):
            fields["isrc"] = FieldValue(value=rec["isrcs"][0], confidence=0.9)
        rel = (rec.get("releases") or [{}])[0]
        if rel.get("date"):
            try:
                fields["year"] = FieldValue(value=int(rel["date"][:4]), confidence=0.85)
            except ValueError:
                pass
        if rec.get("title"):
            fields["title"] = FieldValue(value=rec["title"], confidence=0.95)
        if rec.get("artist-credit"):
            ac = rec["artist-credit"][0].get("artist", {})
            if ac.get("name"):
                fields["primary_artist"] = FieldValue(value=ac["name"], confidence=0.95)
        return ProviderResult(kind=self.kind, fields=fields, raw_response=data)

    async def enrich_artist(self, artist: ArtistRef) -> ProviderResult | None:
        mbid = (artist.external_ids or {}).get("musicbrainz")
        if not mbid:
            name = (artist.name or "").strip()
            if not name:
                return None
            escaped = name.replace("\\", "\\\\").replace('"', '\\"')
            found = await self._get("artist", {"query": f'artist:"{escaped}"', "limit": "3"})
            want = name.casefold()
            for cand in found.get("artists") or []:
                try:
                    score = int(cand.get("score") or 0)
                except (TypeError, ValueError):
                    continue
                if score >= _MIN_SEARCH_SCORE and want in _names(cand) and cand.get("id"):
                    mbid = cand["id"]
                    break
            if not mbid:
                return None
        data = await self._get(f"artist/{mbid}", {"inc": "aliases+url-rels+annotation"})
        ids = {"musicbrainz": data.get("id") or mbid}
        socials: dict[str, str] = {}
        for rel in data.get("relations") or []:
            url = (rel.get("url") or {}).get("resource")
            if not url:
                continue
            if rel.get("type") == "discogs":
                tail = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
                if tail.isdigit():
                    ids["discogs"] = tail
                continue
            key = _social_key(rel.get("type") or "", url)
            if key and key not in socials:
                socials[key] = url
        fields: dict[str, FieldValue] = {
            "external_ids": FieldValue(value=ids, confidence=0.95)}
        if data.get("country"):
            fields["country"] = FieldValue(value=data["country"], confidence=0.9)
        aliases = [a["name"] for a in data.get("aliases") or [] if a.get("name")]
        if aliases:
            fields["aliases"] = FieldValue(value=aliases, confidence=0.85)
        if socials:
            fields["socials"] = FieldValue(value=socials, confidence=0.85)
        if data.get("annotation"):
            fields["bio"] = FieldValue(value=data["annotation"], confidence=0.7)
        return ProviderResult(kind=self.kind, fields=fields, raw_response=data)

    async def enrich_release(self, release):
        return None

    async def lookup_by_isrc(self, isrc: str) -> TrackRef | None:
        data = await self._get(f"isrc/{quote_plus(isrc)}", {"inc": "artist-credits"})
        recs = data.get("recordings") or []
        if not recs:
            return None
        rec = recs[0]
        artist = (rec.get("artist-credit") or [{}])[0].get("artist", {}).get("name")
        return TrackRef(title=rec.get("title"), primary_artist_name=artist,
                        external_ids={"musicbrainz": rec.get("id", "")})

    async def fingerprint(self, *_args, **_kwargs):
        return []

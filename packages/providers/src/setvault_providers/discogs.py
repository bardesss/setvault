from __future__ import annotations

import re
from typing import ClassVar
from urllib.parse import urlparse

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
# Discogs markup: [a=Name] [l=Label] [m=123] [r=123] keep the text, [url=..]/[b]/[/b] drop tags.
_MARKUP_REF = re.compile(r"\[[almr]=([^\]]*)\]")
_MARKUP_TAG = re.compile(r"\[/?[a-z]+\d*(?:=[^\]]*)?\]", re.IGNORECASE)


def _strip_markup(text: str) -> str:
    out = _MARKUP_REF.sub(r"\1", text)
    out = _MARKUP_TAG.sub("", out)
    return re.sub(r"[ \t]+", " ", out).strip()


class DiscogsProvider:
    kind = "discogs"
    capabilities: ClassVar[set[Capability]] = {
        Capability.ENRICH_TRACK, Capability.ENRICH_ARTIST,
    }

    def __init__(self, token: str, base_url: str = "https://api.discogs.com"):
        if not token:
            raise ValueError("Discogs requires a personal access token")
        self.token = token
        self.base_url = base_url

    async def _get(self, path: str, params: dict) -> dict:
        headers = {"Authorization": f"Discogs token={self.token}",
                   "User-Agent": "SetVault/0.1"}
        async with httpx.AsyncClient(timeout=15.0, headers=headers) as c:
            r = await c.get(f"{self.base_url}/{path}", params=params)
        if r.status_code == 429:
            raise ProviderRateLimited("discogs 429")
        if r.status_code != 200:
            raise ProviderError(f"discogs {r.status_code}")
        return r.json()

    async def enrich_track(self, track: TrackRef) -> ProviderResult | None:
        if not track.title:
            return None
        q = f"{track.primary_artist_name or ''} {track.title}".strip()
        data = await self._get("database/search", {"q": q, "type": "release", "per_page": 1})
        rs = data.get("results") or []
        if not rs:
            return None
        r = rs[0]
        fields: dict[str, FieldValue] = {}
        if r.get("year"):
            try:
                fields["year"] = FieldValue(value=int(r["year"]), confidence=0.8)
            except (TypeError, ValueError):
                pass
        if r.get("label"):
            label = r["label"][0] if isinstance(r["label"], list) else r["label"]
            fields["label"] = FieldValue(value=label, confidence=0.75)
        if r.get("catno"):
            fields["catalog_number"] = FieldValue(value=r["catno"], confidence=0.8)
        return ProviderResult(kind=self.kind, fields=fields, raw_response=data)

    async def enrich_artist(self, artist: ArtistRef) -> ProviderResult | None:
        if not self.token:
            return None
        did = (artist.external_ids or {}).get("discogs")
        if not did:
            name = (artist.name or "").strip()
            if not name:
                return None
            found = await self._get(
                "database/search", {"q": name, "type": "artist", "per_page": 5})
            want = name.casefold()
            for cand in found.get("results") or []:
                if (cand.get("title") or "").casefold() == want and cand.get("id"):
                    did = str(cand["id"])
                    break
            if not did:
                return None
        data = await self._get(f"artists/{did}", {})
        fields: dict[str, FieldValue] = {
            "external_ids": FieldValue(value={"discogs": str(did)}, confidence=0.85)}
        if data.get("profile"):
            bio = _strip_markup(data["profile"])
            if bio:
                fields["bio"] = FieldValue(value=bio, confidence=0.7)
        images = data.get("images") or []
        if images and images[0].get("uri"):
            fields["image_url"] = FieldValue(value=images[0]["uri"], confidence=0.7)
        variations = [v for v in data.get("namevariations") or [] if v]
        if variations:
            fields["aliases"] = FieldValue(value=variations, confidence=0.7)
        socials: dict[str, str] = {}
        for url in data.get("urls") or []:
            host = (urlparse(url).hostname or "").lower()
            key = next((k for dom, k in _SOCIAL_HOSTS.items()
                        if host == dom or host.endswith("." + dom)), "homepage")
            socials.setdefault(key, url)
        if socials:
            fields["socials"] = FieldValue(value=socials, confidence=0.7)
        return ProviderResult(kind=self.kind, fields=fields, raw_response=data)

    async def fingerprint(self, *_args, **_kwargs):
        return []

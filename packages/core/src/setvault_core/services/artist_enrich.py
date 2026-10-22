from __future__ import annotations

import logging
from datetime import UTC, datetime

from setvault_providers.base import ArtistRef, Capability, Provider
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.models.catalog import Artist

_log = logging.getLogger(__name__)

# Provider field names we apply directly to Artist scalar columns.
_SCALAR_FIELDS = {"bio", "image_url", "country"}


async def enrich_artist_entity(
    session: AsyncSession, *, artist: Artist, providers: list[Provider],
) -> list[str]:
    ref = ArtistRef(name=artist.name, external_ids=dict(artist.external_ids or {}))
    status = dict(artist.enrichment_status or {})
    written: list[str] = []

    for p in providers:
        if Capability.ENRICH_ARTIST not in p.capabilities:
            continue
        try:
            result = await p.enrich_artist(ref)
        except Exception:
            _log.warning("artist_enrich_failed provider=%s", p.kind, exc_info=True)
            continue
        if result is None:
            continue
        for name, fv in result.fields.items():
            if status.get(name, {}).get("locked"):
                continue
            if name in _SCALAR_FIELDS:
                setattr(artist, name, fv.value)
            elif name == "external_ids" and isinstance(fv.value, dict):
                artist.external_ids = {**(artist.external_ids or {}), **fv.value}
            elif name == "aliases" and isinstance(fv.value, list):
                merged = list(artist.aliases or [])
                seen = {a.casefold() for a in merged}
                for a in fv.value:
                    if isinstance(a, str) and a.strip() and a.casefold() not in seen:
                        seen.add(a.casefold())
                        merged.append(a)
                artist.aliases = merged
            elif name == "socials" and isinstance(fv.value, dict):
                artist.socials = {**(artist.socials or {}), **fv.value}
            else:
                continue
            status[name] = {"value": fv.value, "confidence": fv.confidence,
                            "set_by": f"provider:{p.kind}", "locked": False,
                            "set_at": datetime.now(UTC).isoformat()}
            if name not in written:
                written.append(name)

    artist.enrichment_status = status
    return written

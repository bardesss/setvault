from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from setvault_providers.base import Capability, Provider, ProviderResult, TrackRef
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.models.enrichment import ProviderResponse
from setvault_core.models.tracklist import Track, TracklistEntry
from setvault_core.services.crypto import Crypter

_log = structlog.get_logger(__name__)

# How long a provider *error* is cached (a genuine "not found" keeps 24 h).
_ERROR_CACHE_TTL_SECONDS = 3600

# ── config encryption ───────────────────────────────────────────────────────
# ProviderConfig.encrypted_config is JSONB; we store a single Fernet token
# string under "ciphertext". Crypter (services/crypto.py) is bytes-in/bytes-out
# and takes the app SECRET_KEY — the web layer passes it down.


def encrypt_config(config: dict, secret_key: str) -> dict:
    token = Crypter(secret_key).encrypt(json.dumps(config).encode("utf-8"))
    return {"ciphertext": token.decode("ascii")}


def decrypt_config(encrypted: dict | None, secret_key: str) -> dict:
    ciphertext = (encrypted or {}).get("ciphertext")
    if not ciphertext:
        return {}
    return json.loads(Crypter(secret_key).decrypt(ciphertext.encode("ascii")))


async def enrich_fields_in_memory(
    *,
    providers: list[Provider],
    track_ref_kwargs: dict[str, Any],
    field_priority: dict[str, list[str]],
    locked_fields: set[str],
) -> dict[str, dict]:
    ref = TrackRef(**track_ref_kwargs)
    raw_results: dict[str, ProviderResult] = {}
    for p in providers:
        if Capability.ENRICH_TRACK not in p.capabilities:
            continue
        try:
            res = await p.enrich_track(ref)
        except Exception:
            # A provider failure must not abort enrichment of the others.
            _log.warning("provider_enrich_failed", provider=p.kind, exc_info=True)
            continue
        if res is None:
            continue
        raw_results[p.kind] = res

    fields: dict[str, dict] = {}
    all_field_names = {f for r in raw_results.values() for f in r.fields}
    provider_order = [p.kind for p in providers]
    for name in all_field_names:
        if name in locked_fields:
            continue
        order = field_priority.get(name, provider_order)
        for kind in order:
            res = raw_results.get(kind)
            if res and name in res.fields:
                fv = res.fields[name]
                fields[name] = {"value": fv.value, "confidence": fv.confidence,
                                "set_by": f"provider:{kind}"}
                break
    return fields


def _cache_key_for_track(track_ref_kwargs: dict[str, Any]) -> str:
    title = (track_ref_kwargs.get("title") or "").strip().lower()
    artist = (track_ref_kwargs.get("primary_artist_name") or "").strip().lower()
    return f"track:title_artist:{artist}::{title}"


async def cached_call_provider(
    session: AsyncSession,
    provider: Provider,
    track_ref_kwargs: dict[str, Any],
) -> ProviderResult | None:
    key = _cache_key_for_track(track_ref_kwargs)
    now = datetime.now(UTC)
    cached = (await session.execute(
        select(ProviderResponse).where(
            ProviderResponse.provider_kind == provider.kind,
            ProviderResponse.query_key == key,
            ProviderResponse.expires_at > now,
        )
    )).scalar_one_or_none()
    if cached:
        data = cached.response
        if not data:
            return None
        from setvault_providers.base import FieldValue
        return ProviderResult(
            kind=provider.kind,
            fields={k: FieldValue(value=v["value"], confidence=v["confidence"])
                    for k, v in (data.get("fields") or {}).items()},
            raw_response=data.get("raw_response", {}),
        )
    failed = False
    try:
        result = await provider.enrich_track(TrackRef(**track_ref_kwargs))
    except Exception:
        # Cache the miss so a flaky provider is not retried hot, but only
        # briefly: a transient outage must not hide a track for a whole day.
        _log.warning("provider_enrich_failed", provider=provider.kind, exc_info=True)
        result = None
        failed = True
    if result:
        ttl = result.cache_ttl_seconds
    else:
        ttl = _ERROR_CACHE_TTL_SECONDS if failed else 24 * 3600
    expires = now + timedelta(seconds=ttl)
    serialized = (
        {"fields": {k: {"value": v.value, "confidence": v.confidence}
                    for k, v in result.fields.items()},
         "raw_response": result.raw_response}
        if result else {}
    )
    session.add(ProviderResponse(
        provider_kind=provider.kind, query_key=key,
        response=serialized, fetched_at=now, expires_at=expires,
    ))
    await session.flush()
    return result


async def resolve_entry(
    session: AsyncSession,
    entry: TracklistEntry,
    providers: list[Provider],
    field_priority: dict[str, list[str]],
) -> list[dict]:
    raw = entry.raw_label
    if " - " in raw:
        artist, _, title = raw.partition(" - ")
    else:
        artist, title = "", raw
    candidates: list[dict] = []
    for p in providers:
        result = await cached_call_provider(
            session, p, {"title": title.strip(), "primary_artist_name": artist.strip()},
        )
        if not result:
            continue
        cand_title = result.fields.get("title", None)
        cand_artist = result.fields.get("primary_artist", None)
        candidates.append({
            "title": (cand_title.value if cand_title else title.strip()),
            "artist_name": (cand_artist.value if cand_artist else artist.strip()),
            "confidence": max([fv.confidence for fv in result.fields.values()], default=0.0),
            "source_kind": p.kind,
            "external_ids": {},
            "_fields": {k: {"value": v.value, "confidence": v.confidence}
                        for k, v in result.fields.items()},
        })
    candidates.sort(key=lambda c: c["confidence"], reverse=True)
    return candidates


async def accept_candidate(
    session: AsyncSession,
    entry: TracklistEntry,
    *,
    title: str,
    artist_name: str,
    external_ids: dict,
    confirmed_via_acoustid: bool,
    field_priority: dict[str, list[str]],
    providers: list[Provider],
) -> Track:
    from setvault_core.models.catalog import Artist
    from setvault_core.services.catalog import slugify, unique_slug
    artist = None
    if artist_name:
        # Live artists only (never attach to a merged-away tombstone); several
        # same-name rows are exactly what dedup finds, so take the oldest.
        artist = (await session.execute(
            select(Artist)
            .where(Artist.name == artist_name, Artist.merged_into_id.is_(None))
            .order_by(Artist.created_at, Artist.id)
            .limit(1)
        )).scalars().first()
        if artist is None:
            artist = Artist(
                name=artist_name,
                slug=await unique_slug(session, Artist, slugify(artist_name), name=artist_name),
            )
            session.add(artist)
            await session.flush()
    # Duplicate (title, artist) tracks can exist; reuse the oldest.
    track = (await session.execute(
        select(Track).where(
            Track.title == title,
            Track.primary_artist_id == (artist.id if artist else None),
        )
        .order_by(Track.created_at, Track.id)
        .limit(1)
    )).scalars().first()
    if track is None:
        track = Track(
            title=title,
            primary_artist_id=(artist.id if artist else None),
            external_ids=external_ids,
        )
        session.add(track)
        await session.flush()

    enriched_fields = await enrich_fields_in_memory(
        providers=providers,
        track_ref_kwargs={"title": title, "primary_artist_name": artist_name},
        field_priority=field_priority,
        locked_fields=set(),
    )
    new_status = dict(track.enrichment_status or {})
    for fname, fdata in enriched_fields.items():
        now_iso = datetime.now(UTC).isoformat()
        new_status[fname] = {**fdata, "locked": False, "set_at": now_iso}
        if fname in {"year", "bpm", "key", "isrc", "mix_name"}:
            setattr(track, fname, fdata["value"])
    track.enrichment_status = new_status

    entry.track_id = track.id
    entry.status = "acoustid_confirmed" if confirmed_via_acoustid else "resolved"
    entry.confidence = enriched_fields.get("title", {}).get("confidence")
    await session.flush()
    return track


def select_providers_for_capability(
    configs: Iterable,
    cap: Capability,
    *,
    secret_key: str,
) -> list[Provider]:
    """Build provider instances from enabled ProviderConfig rows, sorted by priority."""
    from setvault_providers.acoustid import AcoustIdProvider
    from setvault_providers.discogs import DiscogsProvider
    from setvault_providers.musicbrainz import MusicBrainzProvider
    out: list[tuple[int, Provider]] = []
    for cfg in configs:
        if not cfg.enabled:
            continue
        plaintext = decrypt_config(cfg.encrypted_config, secret_key)
        if cfg.provider_kind == "musicbrainz":
            inst: Provider = MusicBrainzProvider(
                user_agent=plaintext.get("user_agent", "SetVault/0.1")
            )
        elif cfg.provider_kind == "discogs":
            inst = DiscogsProvider(token=plaintext.get("token", ""))
        elif cfg.provider_kind == "acoustid":
            inst = AcoustIdProvider(api_key=plaintext.get("api_key", ""))
        else:
            continue
        if cap not in inst.capabilities:
            continue
        out.append((cfg.priority, inst))
    out.sort(key=lambda x: x[0])
    return [p for _, p in out]

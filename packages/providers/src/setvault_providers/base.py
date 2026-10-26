"""Provider plugin contract — see spec §5.2.1."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable


class Capability(StrEnum):
    ENRICH_ARTIST = "enrich_artist"
    ENRICH_TRACK = "enrich_track"
    FINGERPRINT = "fingerprint"
    PARSE_TEXT = "parse_text"   # reserved for future LLM provider


@dataclass
class FieldValue:
    value: object
    confidence: float


@dataclass
class ProviderResult:
    kind: str
    fields: dict[str, FieldValue]
    raw_response: dict
    cache_ttl_seconds: int = 86_400 * 90


@dataclass
class ArtistRef:
    name: str | None = None
    external_ids: dict[str, str] = field(default_factory=dict)


@dataclass
class TrackRef:
    title: str | None = None
    primary_artist_name: str | None = None
    isrc: str | None = None
    external_ids: dict[str, str] = field(default_factory=dict)


@dataclass
class TrackCandidate:
    title: str
    artist_name: str
    confidence: float
    external_ids: dict[str, str]
    extra: dict[str, object] = field(default_factory=dict)


class ProviderError(RuntimeError):
    pass


class ProviderRateLimited(ProviderError):
    pass


@runtime_checkable
class Provider(Protocol):
    kind: str
    capabilities: set[Capability]

    async def enrich_artist(self, artist: ArtistRef) -> ProviderResult | None: ...
    async def enrich_track(self, track: TrackRef) -> ProviderResult | None: ...
    async def fingerprint(
        self, audio_path: str, start_seconds: int, window_seconds: int
    ) -> list[TrackCandidate]: ...

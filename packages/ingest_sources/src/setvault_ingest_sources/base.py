"""Ingest-source plugin contract — search across external audio platforms."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class SourceError(Exception):
    """A source failed to perform a search (network/parse/rate-limit)."""


@dataclass
class Candidate:
    """A single search hit from an ingest source. `webpage_url` is a real,
    ingestable URL handed to the existing url-rip pipeline."""
    source_kind: str
    external_id: str
    title: str
    uploader: str | None
    duration_seconds: int | None
    thumbnail_url: str | None
    webpage_url: str
    # Estimated quality tier (setvault_core TIERS name) or None when unknown.
    expected_tier: str | None = None


@runtime_checkable
class IngestSource(Protocol):
    kind: str   # stable id, e.g. "youtube"
    name: str   # admin display name

    def search(self, query: str, *, limit: int = 20) -> list[Candidate]:
        """Return up to `limit` candidates for the query. Raise SourceError on failure."""
        ...

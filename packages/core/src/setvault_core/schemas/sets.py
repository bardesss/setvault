from __future__ import annotations

from datetime import date as _date
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

from setvault_core.schemas.catalog import PartyOut, VenueOut

SetType = Literal["opener", "closer", "b2b", "headline", "warmup", "unknown"]


class SetArtistOut(BaseModel):
    id: str
    name: str
    slug: str
    role: str


class VenueRefOut(BaseModel):
    name: str
    slug: str
    kind: str | None = None


class SetFacetTagOut(BaseModel):
    slug: str
    name: str
    count: int


class SetFacetsOut(BaseModel):
    tags: list[SetFacetTagOut]
    years: list[int]
    venue_kinds: list[str]


class SetSummaryOut(BaseModel):
    id: str
    slug: str
    title: str
    date: _date | None
    duration_seconds: int | None
    set_type: SetType
    status: str
    artists: list[SetArtistOut]
    tags: list[str]
    created_at: datetime
    venue: VenueRefOut | None = None


class SetQualityOut(BaseModel):
    tier: str
    label: str


class SetUpgradeHistoryOut(BaseModel):
    id: str
    created_at: datetime
    from_label: str
    to_label: str
    outcome: str = "upgraded"  # upgraded | merged
    # A merge left the merged copy's tracklist with the recycled copy (the
    # set already had one).
    tracklist_kept: bool = False


class SetDetailOut(SetSummaryOut):
    party: PartyOut | None
    venue: VenueOut | None
    description: str | None
    audio_stream_url: str
    waveform_url: str | None
    normalized_lufs: float | None
    embed_allowed: bool
    quality: SetQualityOut | None = None
    upgrades_enabled: bool = True
    # The library-wide switch; while off, the set's own switch does nothing
    # (the page says so).
    auto_upgrades_enabled: bool = True
    upgrade_history: list[SetUpgradeHistoryOut] = []
    is_favorite: bool = False


class SetListOut(BaseModel):
    items: list[SetSummaryOut]
    total: int


class SetPatchIn(BaseModel):
    title: str | None = None
    date: _date | None = None
    set_type: SetType | None = None
    party_id: str | None = None
    venue_id: str | None = None
    description: str | None = None
    artist_ids: list[str] | None = None
    tag_names: list[Annotated[str, StringConstraints(max_length=80)]] | None = None
    upgrades_enabled: bool | None = None

from __future__ import annotations

from datetime import date as _date
from typing import Literal

from pydantic import BaseModel, Field

VenueKind = Literal["club", "concert_hall", "arena", "outdoor", "warehouse", "boat",
                    "studio", "online", "other"]


class ArtistIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    country: str | None = Field(default=None, max_length=8)
    bio: str | None = None
    aliases: list[str] = Field(default_factory=list)
    image_url: str | None = None


class EntityMonitorOut(BaseModel):
    """The current user's monitor linked to an entity (detail responses only)."""

    id: str
    enabled: bool


class ArtistOut(BaseModel):
    id: str
    name: str
    slug: str
    country: str | None
    bio: str | None
    aliases: list[str]
    image_url: str | None
    monitor: EntityMonitorOut | None = None


class VenueIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind: VenueKind
    city_or_area: str | None = None
    country: str | None = None
    capacity: int | None = None
    website: str | None = None


class VenueOut(VenueIn):
    id: str
    slug: str
    monitor: EntityMonitorOut | None = None


class SeriesIn(BaseModel):
    name: str
    description: str | None = None
    image_url: str | None = None


class SeriesOut(SeriesIn):
    id: str
    slug: str


class PartyIn(BaseModel):
    name: str
    venue_id: str | None = None
    series_id: str | None = None
    date: _date | None = None
    description: str | None = None


class PartyOut(BaseModel):
    id: str
    name: str
    slug: str
    venue: VenueOut | None
    series: SeriesOut | None
    date: _date | None
    description: str | None
    monitor: EntityMonitorOut | None = None


class ArtistPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    country: str | None = Field(default=None, max_length=8)
    bio: str | None = None
    aliases: list[str] | None = None
    image_url: str | None = None


class VenuePatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    kind: VenueKind | None = None
    city_or_area: str | None = None
    country: str | None = None
    capacity: int | None = None
    website: str | None = None


class SeriesPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    image_url: str | None = None


class PartyPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    venue_id: str | None = None
    series_id: str | None = None
    date: _date | None = None
    description: str | None = None

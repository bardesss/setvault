from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from setvault_core.schemas.sets import SetSummaryOut

PlaylistName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
PlaylistDescription = Annotated[str, StringConstraints(max_length=2000)]


class PlaylistIn(BaseModel):
    name: PlaylistName
    description: PlaylistDescription | None = None


class PlaylistPatch(BaseModel):
    # An explicit null name is refused by the route (400); an omitted one keeps
    # the name, so the route tells them apart through model_fields_set.
    name: str | None = None
    description: PlaylistDescription | None = None


class PlaylistOut(BaseModel):
    id: str
    name: str
    description: str | None
    item_count: int
    total_duration_seconds: int
    created_at: datetime
    updated_at: datetime


class PlaylistItemOut(SetSummaryOut):
    position: int
    added_at: datetime


class PlaylistDetailOut(PlaylistOut):
    items: list[PlaylistItemOut]


class PlaylistsListOut(BaseModel):
    items: list[PlaylistOut]


class ReorderIn(BaseModel):
    slugs: list[str]


class AddItemIn(BaseModel):
    slug: str


class SetPlaylistOut(BaseModel):
    id: str
    name: str
    contains: bool


class SetPlaylistsOut(BaseModel):
    items: list[SetPlaylistOut]


class QueueOut(BaseModel):
    slugs: list[str]
    index: int
    updated_at: datetime | None


class QueueIn(BaseModel):
    slugs: list[str]
    index: Annotated[int, Field(ge=0)] = 0
    base_updated_at: datetime | None = None


class QueueWriteOut(BaseModel):
    updated_at: datetime
    overwrote_newer: bool

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CatalogKind = Literal["artist", "party", "venue"]
PerPollCap = Annotated[int, Field(ge=1, le=50)]
QueryText = Annotated[str, Field(max_length=255)]


class MonitorCreate(BaseModel):
    kind: str  # query | entity
    query_text: QueryText | None = None
    source_kind: str | None = Field(default=None, max_length=32)
    external_id: str | None = Field(default=None, max_length=255)
    per_poll_cap: PerPollCap = 5
    # Optional link to the catalog entity this (query) monitor watches.
    catalog_kind: CatalogKind | None = None
    catalog_id: str | None = None

    @model_validator(mode="after")
    def _check(self) -> MonitorCreate:
        if self.kind == "query":
            if not (self.query_text and self.query_text.strip()):
                raise ValueError("query monitor requires query_text")
        elif self.kind == "entity":
            if not self.source_kind or not self.external_id:
                raise ValueError("entity monitor requires source_kind and external_id")
        else:
            raise ValueError("kind must be 'query' or 'entity'")
        if (self.catalog_kind is None) != (self.catalog_id is None):
            raise ValueError("catalog_kind and catalog_id go together")
        if self.catalog_kind is not None and self.kind != "query":
            raise ValueError("only query monitors can link to a catalog entity")
        return self


class MonitorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    kind: str
    query_text: str | None
    source_kind: str | None
    external_id: str | None
    enabled: bool
    per_poll_cap: int
    last_checked_at: datetime | None
    created_at: datetime
    catalog_kind: str | None = None
    catalog_id: str | None = None
    # Resolved from the linked entity; null when unlinked or the entity is gone.
    catalog_name: str | None = None
    catalog_slug: str | None = None


class MonitorsListOut(BaseModel):
    items: list[MonitorOut]


class MonitorUpdate(BaseModel):
    """Edit in place. Every field is optional; ``kind`` can't change. Send
    ``source_kind: null`` for all sources."""

    enabled: bool | None = None
    query_text: QueryText | None = None
    source_kind: str | None = Field(default=None, max_length=32)
    per_poll_cap: PerPollCap | None = None

    @model_validator(mode="after")
    def _check(self) -> MonitorUpdate:
        for name in ("enabled", "per_poll_cap"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} can't be null")
        return self


class DiscoveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    monitor_id: str
    source_kind: str
    external_id: str
    title: str
    uploader: str | None
    webpage_url: str
    duration_seconds: int | None
    thumbnail_url: str | None
    confidence: str
    status: str
    created_at: datetime


class DiscoveriesListOut(BaseModel):
    items: list[DiscoveryOut]
    # The caller's pending_review count, whatever the status filter.
    pending_count: int = 0

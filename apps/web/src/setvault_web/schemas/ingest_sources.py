from __future__ import annotations

from pydantic import BaseModel, Field


class SourceSearchIn(BaseModel):
    q: str
    limit_per_source: int = Field(10, ge=1, le=50)


class CandidateOut(BaseModel):
    source_kind: str
    external_id: str
    title: str
    uploader: str | None
    duration_seconds: int | None
    thumbnail_url: str | None
    webpage_url: str
    already_in_library: bool
    expected_tier: str | None = None


class SourceSearchOut(BaseModel):
    items: list[CandidateOut]
    errored_sources: list[str]


class SourceStateOut(BaseModel):
    kind: str
    name: str
    enabled: bool
    state: str
    consecutive_failures: int
    last_error: str | None
    rate_limit_max: int
    rate_limit_window_seconds: int


class SourceStatesOut(BaseModel):
    items: list[SourceStateOut]


class SetEnabledIn(BaseModel):
    # Optional so a rate-limit-only save leaves enabled/health untouched.
    enabled: bool | None = None
    rate_limit_max: int | None = None
    rate_limit_window_seconds: int | None = Field(None, ge=1)

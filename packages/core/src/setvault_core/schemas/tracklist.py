from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

TracklistEntryStatus = Literal["raw", "resolved", "acoustid_confirmed"]


class TracklistEntryOut(BaseModel):
    id: str
    position: int
    start_seconds: int
    end_seconds: int | None = None
    raw_label: str
    edit_notes: str | None = None
    status: TracklistEntryStatus
    confidence: float | None = None
    track_id: str | None = None
    mashup_with: list[str] = Field(default_factory=list)


class TracklistEntryCreateIn(BaseModel):
    start_seconds: int = Field(ge=0)
    raw_label: str = Field(min_length=1, max_length=1024)
    position: int | None = None
    end_seconds: int | None = None
    edit_notes: str | None = None


class TracklistEntryPatchIn(BaseModel):
    start_seconds: int | None = Field(default=None, ge=0)
    end_seconds: int | None = None
    raw_label: str | None = Field(default=None, min_length=1, max_length=1024)
    edit_notes: str | None = None
    mashup_with: list[str] | None = None


class TracklistEntryMoveIn(BaseModel):
    after_position: int = Field(ge=-1)


class TimeShiftIn(BaseModel):
    after_seconds: int = Field(ge=0)
    delta_seconds: int  # may be negative


class ParsedEntry(BaseModel):
    start_seconds: int | None = None
    raw_label: str


class TracklistImportIn(BaseModel):
    kind: Literal["paste", "url_1001tl", "ocr"]
    payload: dict


class TracklistImportOut(BaseModel):
    id: str
    kind: Literal["paste", "url_1001tl", "ocr"]
    status: Literal["queued", "running", "succeeded", "failed", "accepted"]
    parsed: list[ParsedEntry] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime


class TracklistImportAcceptIn(BaseModel):
    accepted_indexes: list[int]

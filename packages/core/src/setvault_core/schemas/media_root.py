from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from setvault_core.services.storage import HealthStatus  # re-exported for schema consumers

__all__ = [
    "HealthStatus",
    "MediaRootCreateIn",
    "MediaRootListOut",
    "MediaRootOut",
    "MediaRootPatchIn",
    "NamingPreviewIn",
    "NamingPreviewOut",
]


class MediaRootCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    host_path: str = Field(min_length=1, max_length=2048)
    default_for_ingest: bool = False
    max_bytes: int | None = None
    naming_template: str | None = Field(default=None, max_length=255)


class MediaRootPatchIn(BaseModel):
    """Partial edit. An explicit null clears ``max_bytes`` / ``naming_template``;
    the other fields cannot be null."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    enabled: bool | None = None
    default_for_ingest: bool | None = None
    max_bytes: int | None = Field(default=None, ge=0)
    naming_template: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _non_nullable_fields(self) -> MediaRootPatchIn:
        for name in ("name", "enabled", "default_for_ingest"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class MediaRootOut(BaseModel):
    id: str
    name: str
    host_path: str
    enabled: bool
    default_for_ingest: bool
    max_bytes: int | None
    naming_template: str | None
    last_health_status: HealthStatus
    set_count: int = 0


class MediaRootListOut(BaseModel):
    items: list[MediaRootOut]


class NamingPreviewIn(BaseModel):
    template: str = Field(max_length=255)


class NamingPreviewOut(BaseModel):
    errors: list[str]
    warn_no_unique_token: bool
    samples: list[str]

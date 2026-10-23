from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator
from setvault_core.services.audio_quality import TIERS


class SettingsOut(BaseModel):
    """Editable app-wide settings backed by the ``SystemConfig`` singleton."""

    audit_retention_days: int
    monitors_allow_all_users: bool
    monitor_interval_seconds: int
    single_user_auto_login: bool
    quality_tiers_order: list[str]
    quality_cutoff: str
    auto_upgrades_enabled: bool
    upgrade_search_schedule: Literal["daily", "weekly", "off"]
    # None = loudness matching off.
    loudness_target_lufs: float | None


class SettingsIn(BaseModel):
    """Partial update — only the supplied fields are written.

    All fields optional so callers can patch a single toggle without echoing
    the rest of the config back.
    """

    audit_retention_days: int | None = Field(default=None, ge=0)
    monitors_allow_all_users: bool | None = None
    monitor_interval_seconds: int | None = Field(default=None, ge=60)
    single_user_auto_login: bool | None = None
    quality_tiers_order: list[str] | None = None
    quality_cutoff: str | None = None
    auto_upgrades_enabled: bool | None = None
    upgrade_search_schedule: Literal["daily", "weekly", "off"] | None = None
    # An explicit null turns loudness matching off; leaving the field out
    # keeps the stored target (the PUT checks ``model_fields_set``).
    loudness_target_lufs: float | None = Field(default=None, ge=-30.0, le=-5.0)

    @field_validator("quality_tiers_order")
    @classmethod
    def _order_is_permutation(cls, v: list[str] | None) -> list[str] | None:
        if v is not None and sorted(v) != sorted(TIERS):
            raise ValueError(f"must be an ordering of {list(TIERS)}")
        return v

    @field_validator("quality_cutoff")
    @classmethod
    def _cutoff_is_tier(cls, v: str | None) -> str | None:
        if v is not None and v not in TIERS:
            raise ValueError(f"must be one of {list(TIERS)}")
        return v

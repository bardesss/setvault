"""The upgrade search schedule values, shared by the scheduler and the
settings API."""
from __future__ import annotations

from typing import Literal, get_args

Schedule = Literal["daily", "weekly", "off"]
SCHEDULES: tuple[Schedule, ...] = get_args(Schedule)

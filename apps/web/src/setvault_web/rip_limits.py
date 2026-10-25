"""Per-user limit on rip submissions, shared by the URL-rip and discovery-rip
endpoints. Module constants so tests can patch them."""
from __future__ import annotations

import uuid

from fastapi import HTTPException

from setvault_web.rate_limit import hit

RIP_HOURLY_LIMIT = 5
RIP_DAILY_LIMIT = 50


async def enforce_rip_rate_limit(user_id: uuid.UUID) -> None:
    """Raise 429 when ``user_id`` is over the hourly or daily rip limit."""
    hourly = await hit(f"rip_hour:{user_id}", limit=RIP_HOURLY_LIMIT, window_seconds=3600)
    if hourly > RIP_HOURLY_LIMIT:
        raise HTTPException(
            status_code=429, detail="too many URL rips this hour",
            headers={"Retry-After": "3600"},
        )
    daily = await hit(f"rip_day:{user_id}", limit=RIP_DAILY_LIMIT, window_seconds=86400)
    if daily > RIP_DAILY_LIMIT:
        raise HTTPException(
            status_code=429, detail="too many URL rips today",
            headers={"Retry-After": "86400"},
        )

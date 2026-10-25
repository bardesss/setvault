from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from redis import Redis

from setvault_core.config import redis_url


def channel_for_set(live_set_id: str) -> str:
    return f"sv:progress:set:{live_set_id}"


class ProgressEvent(BaseModel):
    kind: Literal[
        "probe", "fingerprint", "transcode", "normalize", "waveform", "ready", "failed",
        "bulk_resolve",
    ]
    live_set_id: str
    job_id: str
    progress_pct: int = 0
    message: str | None = None


_publisher: Redis | None = None


def publisher() -> Redis:
    global _publisher
    if _publisher is None:
        _publisher = Redis.from_url(redis_url())
    return _publisher


def publish(event: ProgressEvent) -> None:
    publisher().publish(channel_for_set(event.live_set_id), event.model_dump_json())

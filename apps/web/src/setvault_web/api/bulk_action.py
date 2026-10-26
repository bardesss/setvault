"""Bulk-action API endpoint (§G7).

POST /api/sets/bulk-action with body:
  {
    "action": "soft_delete" | "retag" | "move_root",
    "set_ids": ["<uuid>", ...],
    "params": { ... }  # action-specific
  }

Returns 202 with a job id; the worker reports per-set audit events and a
summary on completion. Synchronous-only for now — small libraries can wait
on the round-trip; a fully async polling UX is deferred to v0.1.1.
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from redis import Redis
from rq import Queue
from setvault_core.config import redis_url
from setvault_core.models.identity import User

from setvault_web.deps import current_user, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sets/bulk-action", tags=["sets"])

ALLOWED_ACTIONS = {"soft_delete", "retag", "move_root"}


class BulkActionIn(BaseModel):
    action: str = Field(min_length=1)
    set_ids: list[str]
    params: dict = Field(default_factory=dict)


@router.post("", status_code=202)
async def submit_bulk_action(
    body: BulkActionIn,
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
):
    if body.action not in ALLOWED_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown action {body.action!r}; allowed: {sorted(ALLOWED_ACTIONS)}",
        )
    if not body.set_ids:
        raise HTTPException(status_code=400, detail="set_ids must be non-empty")

    queue = Queue("default", connection=Redis.from_url(redis_url()))
    job = queue.enqueue(
        "setvault_core.jobs.bulk_action.run_bulk_action",
        action=body.action,
        set_ids=body.set_ids,
        params=body.params,
        actor_user_id=str(admin.id),
    )
    logger.info(
        "admin %s queued bulk_action %s on %d sets -> %s",
        admin.id, body.action, len(body.set_ids), job.id,
    )
    return {
        "status": "queued",
        "job_id": job.id,
        "action": body.action,
        "count": len(body.set_ids),
    }

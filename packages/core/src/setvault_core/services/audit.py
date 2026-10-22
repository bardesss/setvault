from __future__ import annotations

import uuid
from typing import Any

from pydantic_core import to_jsonable_python
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.models.system import AuditEvent


async def log(
    session: AsyncSession,
    *,
    actor_user_id: uuid.UUID | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    actor_kind: str = "user",
) -> AuditEvent:
    # before/after land in JSONB: encode dates, UUIDs, Decimals, etc. so no
    # caller can turn an audit write into a serialisation error at flush.
    event = AuditEvent(
        actor_user_id=actor_user_id,
        actor_kind=actor_kind,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before=to_jsonable_python(before) if before is not None else None,
        after=to_jsonable_python(after) if after is not None else None,
        ip=ip,
        user_agent=user_agent,
    )
    session.add(event)
    return event

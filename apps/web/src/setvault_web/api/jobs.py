from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from setvault_core.models.system import Job
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.deps import db_session, require_admin

router = APIRouter(prefix="/api/admin/jobs", tags=["admin"])


@router.get("")
async def list_jobs(
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(require_admin)],
):
    rows = (
        await session.execute(
            select(Job).order_by(Job.created_at.desc()).limit(500)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": j.id,
                "rq_id": j.rq_id,
                "kind": j.kind,
                "status": j.status,
                "progress_pct": j.progress_pct,
                "message": j.message,
                "result": j.result,
                "created_at": j.created_at.isoformat(),
                "started_at": j.started_at.isoformat() if j.started_at else None,
                "finished_at": j.finished_at.isoformat() if j.finished_at else None,
            }
            for j in rows
        ]
    }

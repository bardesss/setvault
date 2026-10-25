from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime
from pathlib import PurePosixPath
from types import SimpleNamespace
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from setvault_core.config import redis_url
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User
from setvault_core.schemas.media_root import (
    MediaRootCreateIn,
    MediaRootListOut,
    MediaRootOut,
    MediaRootPatchIn,
    NamingPreviewIn,
    NamingPreviewOut,
)
from setvault_core.services.audit import log as audit_log
from setvault_core.services.naming import (
    render_filename,
    template_has_unique_token,
    validate_template,
)
from setvault_core.services.storage import probe
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from setvault_web.deps import current_user, db_session, parse_uuid, require_admin

router = APIRouter(prefix="/api/media-roots", tags=["admin"])

# Stand-in for the naming preview when the library has no sets yet. A plain
# namespace (not a LiveSet) so it can never be added to a session; it carries
# every attribute ``render_filename`` reads.
_SAMPLE_SET = SimpleNamespace(
    id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
    slug="example-set",
    date=date(2026, 1, 1),
    set_type="headline",
    artists=[SimpleNamespace(artist=SimpleNamespace(name="Example Artist"))],
    party=SimpleNamespace(
        name="Example Party", series=SimpleNamespace(name="Example Series"),
    ),
    venue=SimpleNamespace(name="Example Venue"),
)


def _to_out(r: MediaRoot, set_count: int = 0) -> MediaRootOut:
    return MediaRootOut(
        id=str(r.id), name=r.name, host_path=r.host_path, enabled=r.enabled,
        default_for_ingest=r.default_for_ingest, max_bytes=r.max_bytes,
        naming_template=r.naming_template, last_health_status=r.last_health_status,
        set_count=set_count,
    )


async def _set_counts(session: AsyncSession) -> dict[uuid.UUID, int]:
    """Non-deleted sets per root, in one grouped query."""
    rows = (await session.execute(
        select(LiveSet.media_root_id, func.count())
        .where(LiveSet.deleted_at.is_(None))
        .group_by(LiveSet.media_root_id)
    )).all()
    return {root_id: n for root_id, n in rows}


async def _set_count(session: AsyncSession, root_id: uuid.UUID) -> int:
    return (await session.execute(
        select(func.count()).select_from(LiveSet)
        .where(LiveSet.media_root_id == root_id, LiveSet.deleted_at.is_(None))
    )).scalar_one()


def _check_template(template: str | None) -> None:
    if template is None:
        return
    errors = validate_template(template)
    if errors:
        raise HTTPException(status_code=422, detail=errors)


async def _check_name_free(
    session: AsyncSession, name: str, *, except_id: uuid.UUID | None = None,
) -> None:
    stmt = select(MediaRoot.id).where(MediaRoot.name == name)
    if except_id is not None:
        stmt = stmt.where(MediaRoot.id != except_id)
    if (await session.execute(stmt)).first() is not None:
        raise HTTPException(status_code=409, detail="a media root with that name exists")


@router.get("", response_model=MediaRootListOut)
async def list_roots(
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(require_admin)],
):
    rows = (
        await session.execute(select(MediaRoot).order_by(MediaRoot.created_at))
    ).scalars().all()
    counts = await _set_counts(session)
    return MediaRootListOut(items=[_to_out(r, counts.get(r.id, 0)) for r in rows])


# Registered before the /{root_id} routes.
@router.post("/naming-preview", response_model=NamingPreviewOut)
async def naming_preview(
    body: NamingPreviewIn,
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(require_admin)],
):
    """Render ``body.template`` against up to 3 recent sets (or a built-in
    sample when there are none). Nothing is written."""
    errors = validate_template(body.template)
    warn = not template_has_unique_token(body.template)
    if errors:
        return NamingPreviewOut(errors=errors, warn_no_unique_token=warn, samples=[])
    # Artists (and their Artist rows) are loaded in the same query; party,
    # series and venue are joined-eager on the model already.
    sets = (await session.execute(
        select(LiveSet)
        .options(joinedload(LiveSet.artists))
        .where(LiveSet.deleted_at.is_(None))
        .order_by(LiveSet.created_at.desc())
        .limit(3)
    )).unique().scalars().all()
    if sets:
        samples = [
            render_filename(body.template, s, ext=PurePosixPath(s.audio_path).suffix or ".flac")
            for s in sets
        ]
    else:
        samples = [render_filename(body.template, _SAMPLE_SET, ext=".flac")]
    return NamingPreviewOut(errors=[], warn_no_unique_token=warn, samples=samples)


@router.post("", response_model=MediaRootOut, status_code=201)
async def create_root(
    body: MediaRootCreateIn,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
):
    _check_template(body.naming_template)
    await _check_name_free(session, body.name)
    health = probe(body.host_path)
    # Best-effort mutex: race is acceptable for admin-only Phase 2. A partial-unique
    # index `WHERE default_for_ingest` would enforce strictly; deferred to follow-up.
    if body.default_for_ingest:
        for existing in (await session.execute(
            select(MediaRoot).where(MediaRoot.default_for_ingest.is_(True))
        )).scalars():
            existing.default_for_ingest = False
    row = MediaRoot(
        name=body.name, host_path=body.host_path, enabled=True,
        default_for_ingest=body.default_for_ingest, max_bytes=body.max_bytes,
        naming_template=body.naming_template, last_health_status=health,
        last_health_check_at=datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    await audit_log(
        session,
        actor_user_id=admin.id,
        action="media_root.added",
        target_type="MediaRoot",
        target_id=str(row.id),
        after={"name": body.name, "host_path": body.host_path},
    )
    await session.commit()
    return _to_out(row, 0)


@router.patch("/{root_id}", response_model=MediaRootOut)
async def patch_root(
    root_id: str,
    body: MediaRootPatchIn,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
):
    rid = parse_uuid(root_id)
    row = await session.get(MediaRoot, rid)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    changes = {f: getattr(body, f) for f in body.model_fields_set}
    if "naming_template" in changes:
        _check_template(changes["naming_template"])
    if "name" in changes and changes["name"] != row.name:
        await _check_name_free(session, changes["name"], except_id=row.id)

    final_enabled = changes.get("enabled", row.enabled)
    final_default = changes.get("default_for_ingest", row.default_for_ingest)
    if final_default and not final_enabled:
        raise HTTPException(
            status_code=422,
            detail="the default ingest root cannot be disabled — pick another default first",
        )

    before = {f: getattr(row, f) for f in changes}
    if changes.get("default_for_ingest"):
        # Same transaction as the edit: at most one default at any commit.
        await session.execute(
            update(MediaRoot)
            .where(MediaRoot.id != row.id, MediaRoot.default_for_ingest.is_(True))
            .values(default_for_ingest=False)
        )
    for field, value in changes.items():
        setattr(row, field, value)
    after = {f: getattr(row, f) for f in changes}
    await audit_log(
        session,
        actor_user_id=admin.id,
        action="media_root.edited",
        target_type="MediaRoot",
        target_id=str(row.id),
        before=before,
        after=after,
    )
    await session.commit()
    return _to_out(row, await _set_count(session, row.id))


@router.post("/{root_id}/probe", response_model=MediaRootOut)
async def probe_root(
    root_id: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(require_admin)],
):
    row = await session.get(MediaRoot, parse_uuid(root_id))
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    row.last_health_status = await asyncio.to_thread(probe, row.host_path)
    row.last_health_check_at = datetime.now(UTC)
    await session.commit()
    return _to_out(row, await _set_count(session, row.id))


@router.post("/{root_id}/reapply-template", status_code=202)
async def reapply_naming(
    root_id: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
):
    """Enqueue a worker job that walks every LiveSet on this root and renames
    it under the root's current ``naming_template``.

    Returns 202 immediately; the actual work + per-set audit happens in the
    worker. Admin can watch progress on the scheduled-tasks tab (5C)."""

    from redis import Redis
    from rq import Queue

    row = await session.get(MediaRoot, parse_uuid(root_id))
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    if not row.naming_template:
        raise HTTPException(
            status_code=400, detail="root has no naming_template configured",
        )

    redis = Redis.from_url(redis_url())
    Queue("default", connection=redis).enqueue(
        "setvault_core.jobs.reapply_naming.run_reapply_naming_template",
        str(row.id),
    )
    await audit_log(
        session,
        actor_user_id=admin.id,
        action="media_root.naming_reapply_requested",
        target_type="MediaRoot",
        target_id=str(row.id),
    )
    await session.commit()
    return {"status": "enqueued", "root_id": str(row.id)}


@router.delete("/{root_id}", status_code=204)
async def delete_root(
    root_id: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
):
    row = await session.get(MediaRoot, parse_uuid(root_id))
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    # Refuse delete if any LiveSet still references the root.
    in_use = (await session.execute(
        select(LiveSet.id).where(LiveSet.media_root_id == row.id).limit(1)
    )).first()
    if in_use is not None:
        raise HTTPException(
            status_code=409,
            detail="root has sets — move or delete them first",
        )
    await audit_log(
        session,
        actor_user_id=admin.id,
        action="media_root.removed",
        target_type="MediaRoot",
        target_id=str(row.id),
        before={"name": row.name},
    )
    await session.delete(row)
    await session.commit()

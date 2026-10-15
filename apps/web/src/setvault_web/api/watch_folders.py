"""Admin REST endpoints for watch folders + unmatched-file inbox (5A surface).

All endpoints under `/api/admin/...` and require admin. Watch-folder CRUD is
straightforward; the unmatched-file resolve endpoint is the interesting one —
it covers three branches (link to existing set, create draft, discard).
"""
from __future__ import annotations

import logging
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User
from setvault_core.models.watch_folder import UnmatchedFile, WatchFolder
from setvault_core.schemas.watch_folder import (
    UnmatchedFileListOut,
    UnmatchedFileOut,
    UnmatchedResolveIn,
    WatchFolderCreateIn,
    WatchFolderListOut,
    WatchFolderOut,
    WatchFolderPatchIn,
)
from setvault_core.services.audit import log as audit_log
from setvault_core.services.storage import place_audio_file, probe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.deps import current_user, db_session, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _wf_out(r: WatchFolder) -> WatchFolderOut:
    return WatchFolderOut(
        id=str(r.id),
        name=r.name,
        host_path=r.host_path,
        target_media_root_id=str(r.target_media_root_id),
        enabled=r.enabled,
        last_event_at=r.last_event_at,
        last_health_check_at=r.last_health_check_at,
        last_health_status=r.last_health_status,
        created_at=r.created_at,
    )


def _uf_out(r: UnmatchedFile) -> UnmatchedFileOut:
    return UnmatchedFileOut(
        id=str(r.id),
        watch_folder_id=str(r.watch_folder_id),
        file_path=r.file_path,
        detected_at=r.detected_at,
        audio_info=r.audio_info or {},
        resolution=r.resolution,
        resolved_to_set_id=str(r.resolved_to_set_id) if r.resolved_to_set_id else None,
        error_text=r.error_text,
    )


# --- watch_folders CRUD ------------------------------------------------------

@router.get("/watch-folders", response_model=WatchFolderListOut)
async def list_watch_folders(
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[User, Depends(require_admin)],
):
    rows = (await session.execute(
        select(WatchFolder).order_by(WatchFolder.created_at)
    )).scalars().all()
    return WatchFolderListOut(items=[_wf_out(r) for r in rows])


@router.post("/watch-folders", response_model=WatchFolderOut, status_code=201)
async def create_watch_folder(
    body: WatchFolderCreateIn,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[User, Depends(require_admin)],
):
    try:
        target_id = uuid.UUID(body.target_media_root_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid target_media_root_id") from exc
    target = await session.get(MediaRoot, target_id)
    if target is None:
        raise HTTPException(status_code=400, detail="target MediaRoot not found")

    health = probe(body.host_path)
    row = WatchFolder(
        name=body.name,
        host_path=body.host_path,
        target_media_root_id=target_id,
        enabled=body.enabled,
        created_by=admin.id,
        last_health_status=health,
        last_health_check_at=datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    await audit_log(
        session,
        actor_user_id=admin.id,
        action="watch_folder.added",
        target_type="WatchFolder",
        target_id=str(row.id),
        after={"name": body.name, "host_path": body.host_path,
               "target_media_root_id": body.target_media_root_id},
    )
    await session.commit()
    return _wf_out(row)


@router.patch("/watch-folders/{wf_id}", response_model=WatchFolderOut)
async def update_watch_folder(
    wf_id: str,
    body: WatchFolderPatchIn,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[User, Depends(require_admin)],
):
    try:
        row = await session.get(WatchFolder, uuid.UUID(wf_id))
    except ValueError as exc:
        raise HTTPException(status_code=404) from exc
    if row is None:
        raise HTTPException(status_code=404)
    before = {"name": row.name, "enabled": row.enabled}
    if body.name is not None:
        row.name = body.name
    if body.enabled is not None:
        row.enabled = body.enabled
    await audit_log(
        session,
        actor_user_id=admin.id,
        action="watch_folder.updated",
        target_type="WatchFolder",
        target_id=str(row.id),
        before=before,
        after={"name": row.name, "enabled": row.enabled},
    )
    await session.commit()
    return _wf_out(row)


@router.delete("/watch-folders/{wf_id}", status_code=204)
async def delete_watch_folder(
    wf_id: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[User, Depends(require_admin)],
):
    try:
        row = await session.get(WatchFolder, uuid.UUID(wf_id))
    except ValueError as exc:
        raise HTTPException(status_code=404) from exc
    if row is None:
        raise HTTPException(status_code=404)
    await audit_log(
        session,
        actor_user_id=admin.id,
        action="watch_folder.deleted",
        target_type="WatchFolder",
        target_id=str(row.id),
    )
    await session.delete(row)
    await session.commit()


@router.post("/watch-folders/{wf_id}/health-check", response_model=WatchFolderOut)
async def watch_folder_health_check(
    wf_id: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[User, Depends(require_admin)],
):
    try:
        row = await session.get(WatchFolder, uuid.UUID(wf_id))
    except ValueError as exc:
        raise HTTPException(status_code=404) from exc
    if row is None:
        raise HTTPException(status_code=404)
    row.last_health_status = probe(row.host_path)
    row.last_health_check_at = datetime.now(UTC)
    await session.commit()
    return _wf_out(row)


# --- unmatched-file inbox ----------------------------------------------------

@router.get("/unmatched", response_model=UnmatchedFileListOut)
async def list_unmatched(
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[User, Depends(require_admin)],
    resolution: str | None = None,
    limit: int = 100,
):
    q = select(UnmatchedFile)
    if resolution:
        q = q.where(UnmatchedFile.resolution == resolution)
    else:
        # Default to pending only — the inbox semantics
        q = q.where(UnmatchedFile.resolution == "pending")
    q = q.order_by(UnmatchedFile.detected_at.desc()).limit(limit)
    rows = (await session.execute(q)).scalars().all()
    return UnmatchedFileListOut(items=[_uf_out(r) for r in rows])


@router.post("/unmatched/{uf_id}/resolve", response_model=UnmatchedFileOut)
async def resolve_unmatched(
    uf_id: str,
    body: UnmatchedResolveIn,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[User, Depends(require_admin)],
):
    try:
        row = await session.get(UnmatchedFile, uuid.UUID(uf_id))
    except ValueError as exc:
        raise HTTPException(status_code=404) from exc
    if row is None:
        raise HTTPException(status_code=404)
    if row.resolution != "pending":
        raise HTTPException(status_code=409, detail="already resolved")

    action = body.action
    if action not in {"link_to_set", "create_draft", "discard"}:
        raise HTTPException(status_code=400, detail="unknown action")

    if action == "link_to_set":
        if not body.live_set_id:
            raise HTTPException(status_code=400, detail="live_set_id required")
        try:
            target_set_id = uuid.UUID(body.live_set_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid live_set_id") from exc
        target_set = await session.get(LiveSet, target_set_id)
        if target_set is None:
            raise HTTPException(status_code=400, detail="LiveSet not found")
        # Place the file under the target set's originals/ subtree
        root = await session.get(MediaRoot, target_set.media_root_id)
        if root is None:
            raise HTTPException(status_code=500, detail="MediaRoot vanished")
        src = Path(row.file_path)
        # ASYNC240: a single stat() on an admin-supplied path is bounded;
        # same noqa rationale as uploads.py.
        if not src.exists():  # noqa: ASYNC240
            raise HTTPException(status_code=410, detail="source file no longer exists")
        rel = f"originals/{target_set.id}/{src.name}"
        dst = Path(root.host_path) / rel
        try:
            place_audio_file(src, dst)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"place failed: {exc}") from exc
        row.resolution = "linked_to_set"
        row.resolved_to_set_id = target_set_id

    elif action == "discard":
        # Move source into <watch_folder>/.discarded/. The watch_folder relation
        # gives us the host_path.
        wf = await session.get(WatchFolder, row.watch_folder_id)
        if wf is not None:
            try:
                src = Path(row.file_path)
                if src.exists():
                    discarded_dir = Path(wf.host_path) / ".discarded"
                    discarded_dir.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(discarded_dir / src.name))
            except OSError as exc:
                logger.warning("discard move failed for %s: %s", row.id, exc)
        row.resolution = "discarded"

    else:  # create_draft — defer the actual draft work to a follow-up endpoint.
        # The watcher's job already does the draft-creation work; resolving an
        # unmatched as create_draft is rare (admin saw it, edited the
        # filename, re-dropped it). Mark it resolved + leave the file in place
        # so the watcher catches the rename next.
        row.resolution = "created_as_draft"

    row.resolved_by = admin.id
    row.resolved_at = datetime.now(UTC)
    await audit_log(
        session,
        actor_user_id=admin.id,
        action=f"unmatched_file.{action}",
        target_type="UnmatchedFile",
        target_id=str(row.id),
        after={
            "resolution": row.resolution,
            "resolved_to_set_id": (
                str(row.resolved_to_set_id) if row.resolved_to_set_id else None
            ),
        },
    )
    await session.commit()
    return _uf_out(row)

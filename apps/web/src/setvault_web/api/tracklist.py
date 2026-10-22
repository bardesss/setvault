from __future__ import annotations

import base64
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from setvault_core.jobs.tracklist_ocr import OcrFailed, ocr_to_entries
from setvault_core.jobs.tracklist_url_1001tl import HostRejected, scrape_1001tracklists
from setvault_core.models.catalog import LiveSet
from setvault_core.models.identity import User
from setvault_core.models.tracklist import TracklistEntry, TracklistImportJob
from setvault_core.schemas.tracklist import (
    ParsedEntry,
    TimeShiftIn,
    TracklistEntryCreateIn,
    TracklistEntryMoveIn,
    TracklistEntryOut,
    TracklistEntryPatchIn,
    TracklistImportAcceptIn,
    TracklistImportIn,
    TracklistImportOut,
)
from setvault_core.services.audit import log as audit_log
from setvault_core.services.tracklist import (
    InvalidPosition,
    create_entry,
    delete_entry,
    list_entries,
    reorder_entries,
    time_shift_entries,
    update_entry,
)
from setvault_core.services.tracklist_parse import parse_tracklist_text
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.config import Settings
from setvault_web.deps import current_user, db_session, parse_uuid
from setvault_web.rate_limit import hit

router = APIRouter(prefix="/api/sets", tags=["tracklist"])


class TracklistOut(BaseModel):
    entries: list[TracklistEntryOut]


def _to_out(e: TracklistEntry) -> TracklistEntryOut:
    return TracklistEntryOut(
        id=str(e.id),
        position=e.position,
        start_seconds=e.start_seconds,
        end_seconds=e.end_seconds,
        raw_label=e.raw_label,
        edit_notes=e.edit_notes,
        status=e.status,
        confidence=e.confidence,
        track_id=str(e.track_id) if e.track_id else None,
        mashup_with=[str(x) for x in (e.mashup_with or [])],
    )


async def _load_set(session: AsyncSession, slug: str) -> LiveSet:
    live = (await session.execute(
        select(LiveSet).where(LiveSet.slug == slug, LiveSet.deleted_at.is_(None))
    )).scalar_one_or_none()
    if live is None:
        raise HTTPException(status_code=404, detail="not found")
    return live


@router.get("/{slug}/tracklist", response_model=TracklistOut)
async def get_tracklist(
    slug: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[User, Depends(current_user)],
):
    live = await _load_set(session, slug)
    entries = await list_entries(session, live.id)
    return TracklistOut(entries=[_to_out(e) for e in entries])


@router.post("/{slug}/tracklist/entries", response_model=TracklistEntryOut, status_code=201)
async def create_tracklist_entry(
    slug: str,
    body: TracklistEntryCreateIn,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    live = await _load_set(session, slug)
    try:
        entry = await create_entry(
            session, live.id,
            user_id=user.id,
            start_seconds=body.start_seconds,
            raw_label=body.raw_label,
            position=body.position,
            end_seconds=body.end_seconds,
            edit_notes=body.edit_notes,
        )
    except InvalidPosition as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await audit_log(
        session, actor_user_id=user.id, actor_kind="user",
        action="tracklist.entry.created",
        target_type="tracklist_entry", target_id=str(entry.id),
        after={"live_set_id": str(live.id), "position": entry.position,
               "raw_label": entry.raw_label},
    )
    await session.commit()
    return _to_out(entry)


@router.patch("/{slug}/tracklist/entries/{entry_id}", response_model=TracklistEntryOut)
async def patch_tracklist_entry(
    slug: str,
    entry_id: str,
    body: TracklistEntryPatchIn,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    live = await _load_set(session, slug)
    entry = (await session.execute(
        select(TracklistEntry).where(
            TracklistEntry.id == parse_uuid(entry_id),
            TracklistEntry.live_set_id == live.id,
        )
    )).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="entry not found")
    before = {"raw_label": entry.raw_label, "start_seconds": entry.start_seconds}
    await update_entry(
        session, entry,
        start_seconds=body.start_seconds,
        end_seconds=body.end_seconds,
        raw_label=body.raw_label,
        edit_notes=body.edit_notes,
        mashup_with=(
            [parse_uuid(x, status_code=422, detail="invalid id") for x in body.mashup_with]
            if body.mashup_with else None
        ),
    )
    after = {"raw_label": entry.raw_label, "start_seconds": entry.start_seconds}
    await audit_log(
        session, actor_user_id=user.id, actor_kind="user",
        action="tracklist.entry.updated",
        target_type="tracklist_entry", target_id=str(entry.id),
        before=before, after=after,
    )
    await session.commit()
    return _to_out(entry)


@router.patch("/{slug}/tracklist/entries/{entry_id}/move", status_code=204)
async def move_tracklist_entry(
    slug: str,
    entry_id: str,
    body: TracklistEntryMoveIn,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    live = await _load_set(session, slug)
    try:
        await reorder_entries(session, live.id, entry_id=entry_id,
                              after_position=body.after_position)
    except InvalidPosition as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()


@router.delete("/{slug}/tracklist/entries/{entry_id}", status_code=204)
async def delete_tracklist_entry(
    slug: str,
    entry_id: str,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    live = await _load_set(session, slug)
    entry = (await session.execute(
        select(TracklistEntry).where(
            TracklistEntry.id == parse_uuid(entry_id),
            TracklistEntry.live_set_id == live.id,
        )
    )).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="entry not found")
    entry_id_str = str(entry.id)
    raw_label = entry.raw_label
    await delete_entry(session, entry)
    await audit_log(
        session, actor_user_id=user.id, actor_kind="user",
        action="tracklist.entry.deleted",
        target_type="tracklist_entry", target_id=entry_id_str,
        before={"raw_label": raw_label},
    )
    await session.commit()


class TimeShiftOut(BaseModel):
    affected_count: int


@router.post("/{slug}/tracklist/time-shift", response_model=TimeShiftOut)
async def time_shift_tracklist(
    slug: str,
    body: TimeShiftIn,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    live = await _load_set(session, slug)
    count = await time_shift_entries(
        session, live.id,
        after_seconds=body.after_seconds, delta_seconds=body.delta_seconds,
    )
    await audit_log(
        session, actor_user_id=user.id, actor_kind="user",
        action="tracklist.time_shift",
        target_type="live_set", target_id=str(live.id),
        after={"after_seconds": body.after_seconds,
               "delta_seconds": body.delta_seconds, "affected": count},
    )
    await session.commit()
    return TimeShiftOut(affected_count=count)


def _import_to_out(job: TracklistImportJob) -> TracklistImportOut:
    result = job.result or {}
    return TracklistImportOut(
        id=str(job.id),
        kind=job.kind,
        status=job.status,
        parsed=[ParsedEntry(**p) for p in result.get("parsed", [])],
        error=result.get("error"),
        created_at=job.created_at,
    )


@router.post("/{slug}/tracklist/import", response_model=TracklistImportOut)
async def import_tracklist(
    slug: str,
    body: TracklistImportIn,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    live = await _load_set(session, slug)
    job = TracklistImportJob(
        live_set_id=live.id, kind=body.kind, payload=body.payload,
        created_by=user.id, created_at=datetime.now(UTC),
    )
    session.add(job)
    await session.flush()

    if body.kind == "paste":
        text = body.payload.get("text", "")
        parsed = parse_tracklist_text(text)
        # Assign sequential start_seconds for entries with None — keep ordering
        next_t = 0
        normalized = []
        for p in parsed:
            t = p.start_seconds if p.start_seconds is not None else next_t
            next_t = t
            normalized.append({"start_seconds": t, "raw_label": p.raw_label})
        job.status = "succeeded"
        job.result = {"parsed": normalized}
        job.finished_at = datetime.now(UTC)
    elif body.kind == "url_1001tl":
        # ToS-grey source: gated behind an admin opt-in flag, then rate limited.
        if not Settings().allow_1001tl_scrape:
            raise HTTPException(
                status_code=403, detail="1001tracklists scraping disabled by admin"
            )
        count = await hit(f"tl_scrape:{user.id}", limit=1, window_seconds=60)
        if count > 1:
            raise HTTPException(
                status_code=429,
                detail="1001tracklists scrape rate limit (1/min)",
                headers={"Retry-After": "60"},
            )
        url = body.payload.get("url", "")
        try:
            scraped = await scrape_1001tracklists(url)
        except HostRejected as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # any fetch/parse failure marks the job failed
            job.status = "failed"
            job.result = {"error": str(exc)}
            job.finished_at = datetime.now(UTC)
            await session.commit()
            return _import_to_out(job)
        # Normalize None start_seconds the same way paste does
        next_t = 0
        normalized = []
        for s in scraped:
            t = s.start_seconds if s.start_seconds is not None else next_t
            next_t = t
            normalized.append({"start_seconds": t, "raw_label": s.raw_label})
        job.status = "succeeded"
        job.result = {"parsed": normalized}
        job.finished_at = datetime.now(UTC)
    elif body.kind == "ocr":
        b64 = body.payload.get("image_b64", "")
        try:
            data = base64.b64decode(b64, validate=True)
        except (ValueError, TypeError) as exc:  # binascii.Error is a ValueError
            raise HTTPException(status_code=400, detail="invalid image_b64") from exc
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        try:
            parsed = ocr_to_entries(tmp_path)
        except OcrFailed as exc:
            job.status = "failed"
            job.result = {"error": str(exc)}
            job.finished_at = datetime.now(UTC)
            await session.commit()
            return _import_to_out(job)
        finally:
            tmp_path.unlink(missing_ok=True)  # noqa: ASYNC240 — trivial cleanup of our own temp file
        next_t = 0
        normalized = []
        for p in parsed:
            t = p.start_seconds if p.start_seconds is not None else next_t
            next_t = t
            normalized.append({"start_seconds": t, "raw_label": p.raw_label})
        job.status = "succeeded"
        job.result = {"parsed": normalized}
        job.finished_at = datetime.now(UTC)
    else:
        raise HTTPException(status_code=400, detail=f"unknown kind: {body.kind}")

    await session.commit()
    return _import_to_out(job)


@router.post("/{slug}/tracklist/import/{job_id}/accept", response_model=TracklistOut)
async def accept_import(
    slug: str,
    job_id: str,
    body: TracklistImportAcceptIn,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    live = await _load_set(session, slug)
    job = (await session.execute(
        select(TracklistImportJob).where(
            TracklistImportJob.id == parse_uuid(job_id),
            TracklistImportJob.live_set_id == live.id,
        ).with_for_update()
    )).scalar_one_or_none()
    if job is None or job.status not in ("succeeded", "accepted"):
        raise HTTPException(status_code=404, detail="import not ready")
    if job.status == "accepted":
        raise HTTPException(status_code=409, detail="import already accepted")
    parsed = (job.result or {}).get("parsed", [])
    # Materialize accepted entries appended after the current last position
    max_pos = (await session.execute(
        select(func.max(TracklistEntry.position)).where(
            TracklistEntry.live_set_id == live.id
        )
    )).scalar()
    next_pos = 0 if max_pos is None else max_pos + 1
    indexes = [
        i for i in dict.fromkeys(body.accepted_indexes) if 0 <= i < len(parsed)
    ]
    job.status = "accepted"
    for idx in indexes:
        p = parsed[idx]
        e = TracklistEntry(
            live_set_id=live.id,
            position=next_pos,
            start_seconds=int(p["start_seconds"]),
            raw_label=p["raw_label"],
            created_by=user.id,
        )
        session.add(e)
        next_pos += 1
    await audit_log(
        session, actor_user_id=user.id, actor_kind="user",
        action="tracklist.import.accepted",
        target_type="tracklist_import_job", target_id=str(job.id),
        after={"accepted": indexes},
    )
    await session.commit()
    refreshed = await list_entries(session, live.id)
    return TracklistOut(entries=[_to_out(e) for e in refreshed])

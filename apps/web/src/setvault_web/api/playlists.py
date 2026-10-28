from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from setvault_core.models.catalog import LiveSet
from setvault_core.models.identity import User
from setvault_core.models.playlists import Playlist
from setvault_core.schemas.playlists import (
    AddItemIn,
    PlaylistDetailOut,
    PlaylistIn,
    PlaylistItemOut,
    PlaylistOut,
    PlaylistPatch,
    PlaylistsListOut,
    ReorderIn,
    SetPlaylistOut,
    SetPlaylistsOut,
)
from setvault_core.services import playlists as svc
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.api.sets import summary_out, tags_by_set
from setvault_web.deps import current_user, db_session, parse_uuid

router = APIRouter(tags=["playlists"])

_MISMATCH = "The list doesn't match the sets in this playlist"


def _out(pl: Playlist, count: int, total: int) -> PlaylistOut:
    return PlaylistOut(
        id=str(pl.id), name=pl.name, description=pl.description,
        item_count=count, total_duration_seconds=total,
        created_at=pl.created_at, updated_at=pl.updated_at,
    )


async def _owned_or_404(session: AsyncSession, user: User, playlist_id: str) -> Playlist:
    pl = await svc.get_owned(session, user.id, parse_uuid(playlist_id))
    if pl is None:
        raise HTTPException(status_code=404)
    return pl


async def _visible_set(session: AsyncSession, slug: str) -> LiveSet:
    live = (await session.execute(
        select(LiveSet).where(LiveSet.slug == slug, *svc.visible_clause())
    )).scalar_one_or_none()
    if live is None:
        raise HTTPException(status_code=404)
    return live


async def _detail(session: AsyncSession, pl: Playlist) -> PlaylistDetailOut:
    rows = await svc.visible_items(session, pl.id)
    tags = await tags_by_set(session, [ls.id for ls, _ in rows])
    items = [
        PlaylistItemOut(
            **summary_out(ls, tags.get(ls.id, [])).model_dump(),
            position=item.position, added_at=item.added_at,
        )
        for ls, item in rows
    ]
    base = _out(pl, len(rows), sum(ls.duration_seconds or 0 for ls, _ in rows))
    return PlaylistDetailOut(**base.model_dump(), items=items)


async def _commit_and_detail(session: AsyncSession, pl: Playlist) -> PlaylistDetailOut:
    await session.commit()
    await session.refresh(pl)
    return await _detail(session, pl)


@router.get("/api/me/playlists", response_model=PlaylistsListOut)
async def list_playlists(
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    rows = await svc.list_owned(session, user.id)
    return PlaylistsListOut(items=[_out(pl, n, total) for pl, n, total in rows])


@router.post("/api/me/playlists", response_model=PlaylistDetailOut, status_code=201)
async def create_playlist(
    body: PlaylistIn,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    pl = Playlist(
        owner_user_id=user.id, name=body.name,
        description=(body.description or "").strip() or None,
    )
    session.add(pl)
    await session.flush()
    return await _commit_and_detail(session, pl)


@router.get("/api/me/playlists/{playlist_id}", response_model=PlaylistDetailOut)
async def get_playlist(
    playlist_id: str,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    return await _detail(session, await _owned_or_404(session, user, playlist_id))


@router.patch("/api/me/playlists/{playlist_id}", response_model=PlaylistOut)
async def patch_playlist(
    playlist_id: str,
    body: PlaylistPatch,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    pl = await _owned_or_404(session, user, playlist_id)
    if "name" in body.model_fields_set:
        name = (body.name or "").strip()
        if not name or len(name) > 200:
            raise HTTPException(
                status_code=400, detail="A playlist needs a name of 1-200 characters")
        pl.name = name
    if "description" in body.model_fields_set:
        pl.description = (body.description or "").strip() or None
    pl.updated_at = datetime.now(UTC)
    detail = await _commit_and_detail(session, pl)
    return PlaylistOut(**detail.model_dump(exclude={"items"}))


@router.delete("/api/me/playlists/{playlist_id}", status_code=204)
async def delete_playlist(
    playlist_id: str,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    pl = await _owned_or_404(session, user, playlist_id)
    await session.delete(pl)
    await session.commit()
    return Response(status_code=204)


@router.put("/api/me/playlists/{playlist_id}/items", response_model=PlaylistDetailOut)
async def reorder_playlist(
    playlist_id: str,
    body: ReorderIn,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    pl = await _owned_or_404(session, user, playlist_id)
    if len(body.slugs) > svc.MAX_ITEMS:
        raise HTTPException(status_code=400, detail=_MISMATCH)
    found = dict((await session.execute(
        select(LiveSet.slug, LiveSet.id).where(
            LiveSet.slug.in_(body.slugs), *svc.visible_clause())
    )).all())
    if any(s not in found for s in body.slugs):
        raise HTTPException(status_code=400, detail=_MISMATCH)
    try:
        await svc.reorder(session, pl, [found[s] for s in body.slugs])
    except svc.PlaylistError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _commit_and_detail(session, pl)


@router.post("/api/me/playlists/{playlist_id}/items", status_code=204)
async def add_playlist_item(
    playlist_id: str,
    body: AddItemIn,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    pl = await _owned_or_404(session, user, playlist_id)
    live = await _visible_set(session, body.slug)
    try:
        await svc.add_item(session, pl, live.id)
    except svc.PlaylistError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return Response(status_code=204)


@router.delete("/api/me/playlists/{playlist_id}/items/{slug}", status_code=204)
async def remove_playlist_item(
    playlist_id: str,
    slug: str,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    pl = await _owned_or_404(session, user, playlist_id)
    # No visibility check: recycled or unpublished sets must stay removable.
    live_id = (await session.execute(
        select(LiveSet.id).where(LiveSet.slug == slug)
    )).scalar_one_or_none()
    if live_id is None:
        raise HTTPException(status_code=404)
    await svc.remove_item(session, pl, live_id)
    await session.commit()
    return Response(status_code=204)


@router.get("/api/sets/{slug}/playlists", response_model=SetPlaylistsOut)
async def set_playlists(
    slug: str,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    live = await _visible_set(session, slug)
    rows = await svc.playlists_containing(session, user.id, live.id)
    return SetPlaylistsOut(items=[
        SetPlaylistOut(id=str(pl.id), name=pl.name, contains=has) for pl, has in rows
    ])

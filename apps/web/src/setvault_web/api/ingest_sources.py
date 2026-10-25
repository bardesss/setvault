from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from setvault_core.models.identity import User
from setvault_core.models.url_rip import RipJob
from setvault_core.services.ingest_sources import (
    get_state,
    list_states,
    search_all_sources,
    set_enabled,
)
from setvault_core.services.quality_profile import get_profile, rank
from setvault_ingest_sources.base import Candidate
from setvault_ingest_sources.registry import get_source
from sqlalchemy import and_, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.api.images import build_proxied_image_url
from setvault_web.deps import current_user, db_session, require_admin
from setvault_web.rate_limit import hit as _ratelimit_hit
from setvault_web.schemas.ingest_sources import (
    CandidateOut,
    SetEnabledIn,
    SourceSearchIn,
    SourceSearchOut,
    SourceStateOut,
    SourceStatesOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ingest-sources"])

# Per-user searches per minute; every search fans out to all enabled sources.
SEARCH_LIMIT = 30


def _state_out(st, source) -> SourceStateOut:
    return SourceStateOut(
        kind=st.kind,
        name=(source.name if source else st.kind),
        enabled=st.enabled,
        state=st.state,
        consecutive_failures=st.consecutive_failures,
        last_error=st.last_error,
        rate_limit_max=st.rate_limit_max,
        rate_limit_window_seconds=st.rate_limit_window_seconds,
    )


@router.post("/api/ingest-sources/search", response_model=SourceSearchOut)
async def search(
    body: SourceSearchIn,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
) -> SourceSearchOut:
    searches = await _ratelimit_hit(f"search:{user.id}", limit=SEARCH_LIMIT, window_seconds=60)
    if searches > SEARCH_LIMIT:
        raise HTTPException(
            status_code=429, detail="too many searches", headers={"Retry-After": "60"},
        )
    result = await search_all_sources(
        session, query=body.q, limit_per_source=body.limit_per_source
    )
    profile = await get_profile(session)
    # Stable sort: best expected quality first, unknown last.
    cands = sorted(result.candidates, key=lambda c: rank(profile, c.expected_tier))

    id_keys: set[tuple[str, str]] = set()
    urls: set[str] = set()
    if cands:
        platforms = {c.source_kind for c in cands}
        ext_ids = [c.external_id for c in cands if c.external_id]
        webpage_urls = [c.webpage_url for c in cands if c.webpage_url]
        # Scope to the candidate keys so this stays cheap on a large library
        # rather than scanning every non-failed rip for the searched platforms.
        rows = (await session.execute(
            select(RipJob.source_platform, RipJob.source_external_id, RipJob.source_url).where(
                RipJob.source_platform.in_(platforms),
                RipJob.status != "failed",
                # A discarded/failed upgrade attempt left no set behind (an
                # applied one now points at the upgraded set).
                ~and_(RipJob.upgrade_target_set_id.is_not(None), RipJob.live_set_id.is_(None)),
                or_(
                    RipJob.source_external_id.in_(ext_ids) if ext_ids else false(),
                    RipJob.source_url.in_(webpage_urls) if webpage_urls else false(),
                ),
            )
        )).all()
        for platform, ext_id, src_url in rows:
            if ext_id:
                id_keys.add((platform, ext_id))
            if src_url:
                urls.add(src_url)

    def _in_lib(c: Candidate) -> bool:
        # URL fallback (for sources with no stable external_id) is an exact-string
        # match, so trailing-slash/query drift can miss — chromaprint is the real dedup.
        return (c.source_kind, c.external_id) in id_keys or c.webpage_url in urls

    return SourceSearchOut(
        items=[
            CandidateOut(
                source_kind=c.source_kind, external_id=c.external_id, title=c.title,
                uploader=c.uploader, duration_seconds=c.duration_seconds,
                thumbnail_url=build_proxied_image_url(c.thumbnail_url),
                webpage_url=c.webpage_url,
                already_in_library=_in_lib(c),
                expected_tier=c.expected_tier,
            )
            for c in cands
        ],
        errored_sources=result.errored_kinds,
        throttled_kinds=result.throttled_kinds,
    )


@router.get("/api/admin/ingest-sources", response_model=SourceStatesOut)
async def admin_list(
    _: Annotated[object, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(db_session)],
) -> SourceStatesOut:
    states = await list_states(session)
    return SourceStatesOut(items=[
        _state_out(s, get_source(s.kind)) for s in states
    ])


@router.put("/api/admin/ingest-sources/{kind}", response_model=SourceStateOut)
async def admin_set_enabled(
    kind: str,
    body: SetEnabledIn,
    _: Annotated[object, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(db_session)],
) -> SourceStateOut:
    source = get_source(kind)
    if source is None:
        raise HTTPException(status_code=404, detail="unknown source")
    st = await get_state(session, kind)
    # set_enabled resets health (failures, last_error, state), so only call it
    # when the enabled flag actually changes; a rate-limit save must not clear
    # a degraded source or relabel an auto-disabled one.
    if body.enabled is not None and (st is None or body.enabled != st.enabled):
        st = await set_enabled(session, kind, body.enabled)
    elif st is None:
        st = await set_enabled(session, kind, True)
    if body.rate_limit_max is not None:
        st.rate_limit_max = body.rate_limit_max
    if body.rate_limit_window_seconds is not None:
        st.rate_limit_window_seconds = body.rate_limit_window_seconds
    await session.flush()
    await session.commit()
    return _state_out(st, source)

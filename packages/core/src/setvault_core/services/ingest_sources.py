from __future__ import annotations

import asyncio
from dataclasses import dataclass

from setvault_ingest_sources.base import Candidate, IngestSource, SourceError
from setvault_ingest_sources.registry import all_source_kinds, get_source
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.models.ingest_sources import IngestSourceState
from setvault_core.services.source_rate_limit import allow as _source_allow

AUTO_DISABLE_AFTER = 5


class SourceDisabledError(Exception):
    """The requested source is disabled (manually or auto)."""


class SourceRateLimitedError(Exception):
    """The per-source rate limit budget for this kind is exhausted. NOT a
    health failure — retry next poll."""


@dataclass
class SearchAllResult:
    candidates: list[Candidate]
    errored_kinds: list[str]


def _record_success(st: IngestSourceState) -> None:
    st.consecutive_failures = 0
    st.state = "healthy"
    st.last_error = None


def _record_failure(st: IngestSourceState, err: Exception) -> None:
    st.consecutive_failures += 1
    st.last_error = str(err)[:500]
    if st.consecutive_failures >= AUTO_DISABLE_AFTER:
        st.enabled = False
        st.state = "auto_disabled"
    else:
        st.state = "degraded"


# Default rate limits where the model default (30 per 60 s) is too fast:
# Bandcamp is scraped HTML, so keep it to 30 requests an hour.
_SEED_RATE_LIMITS: dict[str, dict[str, int]] = {
    "bandcamp": {"rate_limit_max": 30, "rate_limit_window_seconds": 3600},
}


async def ensure_seed_states(session: AsyncSession) -> None:
    """Create an IngestSourceState row for every registered source kind that
    doesn't have one yet. Idempotent."""
    existing = {s.kind for s in (await session.execute(select(IngestSourceState))).scalars()}
    for kind in all_source_kinds():
        if kind not in existing:
            session.add(IngestSourceState(
                kind=kind, enabled=True, state="healthy",
                **_SEED_RATE_LIMITS.get(kind, {}),
            ))
    await session.flush()


async def list_states(session: AsyncSession) -> list[IngestSourceState]:
    await ensure_seed_states(session)
    return list((await session.execute(
        select(IngestSourceState).order_by(IngestSourceState.kind)
    )).scalars())


async def get_state(session: AsyncSession, kind: str) -> IngestSourceState | None:
    return (await session.execute(
        select(IngestSourceState).where(IngestSourceState.kind == kind)
    )).scalar_one_or_none()


async def set_enabled(session: AsyncSession, kind: str, enabled: bool) -> IngestSourceState:
    st = await get_state(session, kind)
    if st is None:
        st = IngestSourceState(kind=kind)
        session.add(st)
    st.enabled = enabled
    if enabled:
        st.state = "healthy"
        st.consecutive_failures = 0
        st.last_error = None
    else:
        st.state = "manually_disabled"
    await session.flush()
    return st


async def search_source(
    session: AsyncSession, *, kind: str, query: str, limit: int = 20,
) -> list[Candidate]:
    await ensure_seed_states(session)
    st = await get_state(session, kind)
    if st is None or not st.enabled:
        raise SourceDisabledError(kind)
    source = get_source(kind)
    if source is None:
        raise SourceDisabledError(kind)
    if not await _source_allow(
        kind, limit=st.rate_limit_max, window_seconds=st.rate_limit_window_seconds,
    ):
        raise SourceRateLimitedError(kind)
    try:
        results = source.search(query, limit=limit)
    except SourceError as e:
        _record_failure(st, e)
        await session.flush()
        raise
    _record_success(st)
    await session.flush()
    return results


async def search_all_sources(
    session: AsyncSession, *, query: str, limit_per_source: int = 10,
) -> SearchAllResult:
    states = await list_states(session)  # seeds + returns all, ordered by kind
    enabled = [
        (st, src)
        for st in states
        if st.enabled and (src := get_source(st.kind)) is not None
    ]

    async def _run(src: IngestSource, st: IngestSourceState) -> list[Candidate]:
        if not await _source_allow(
            st.kind, limit=st.rate_limit_max, window_seconds=st.rate_limit_window_seconds,
        ):
            return []  # budget exhausted this window; try next poll
        return await asyncio.to_thread(src.search, query, limit=limit_per_source)

    results = await asyncio.gather(
        *[_run(src, st) for st, src in enabled], return_exceptions=True
    )
    candidates: list[Candidate] = []
    errored: list[str] = []
    for (st, _src), res in zip(enabled, results, strict=True):
        if isinstance(res, SourceError):
            _record_failure(st, res)
            errored.append(st.kind)
        elif isinstance(res, BaseException):
            # A non-SourceError escaping search() is a bug (or cancellation),
            # not a flaky source — surface it rather than masking + auto-disabling.
            raise res
        else:
            _record_success(st)
            candidates.extend(res)
    await session.flush()
    return SearchAllResult(candidates=candidates, errored_kinds=errored)

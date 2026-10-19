import pytest
from setvault_core.services import ingest_sources as svc


@pytest.mark.asyncio
async def test_ensure_seed_states_creates_rows_for_known_kinds(session):
    await svc.ensure_seed_states(session)
    states = await svc.list_states(session)
    assert any(s.kind == "youtube" for s in states)


@pytest.mark.asyncio
async def test_search_success_resets_failures(session, monkeypatch):
    await svc.ensure_seed_states(session)
    from setvault_ingest_sources.base import Candidate

    class _Src:
        kind = "youtube"
        name = "YouTube"

        def search(self, q, *, limit=20):
            return [Candidate("youtube", "v1", "T", "U", 60, None, "https://youtu.be/v1")]

    monkeypatch.setattr(svc, "get_source", lambda kind: _Src())

    cands = await svc.search_source(session, kind="youtube", query="x", limit=5)
    assert cands[0].external_id == "v1"
    st = await svc.get_state(session, "youtube")
    assert st.consecutive_failures == 0 and st.state == "healthy"


@pytest.mark.asyncio
async def test_search_failures_auto_disable_after_threshold(session, monkeypatch):
    await svc.ensure_seed_states(session)
    from setvault_ingest_sources.base import SourceError

    class _BadSrc:
        kind = "youtube"
        name = "YouTube"

        def search(self, q, *, limit=20):
            raise SourceError("nope")

    monkeypatch.setattr(svc, "get_source", lambda kind: _BadSrc())

    for _ in range(svc.AUTO_DISABLE_AFTER):
        with pytest.raises(SourceError):
            await svc.search_source(session, kind="youtube", query="x")
    st = await svc.get_state(session, "youtube")
    assert st.enabled is False and st.state == "auto_disabled"


@pytest.mark.asyncio
async def test_search_disabled_source_raises(session, monkeypatch):
    await svc.ensure_seed_states(session)
    await svc.set_enabled(session, "youtube", False)
    with pytest.raises(svc.SourceDisabledError):
        await svc.search_source(session, kind="youtube", query="x")


@pytest.mark.asyncio
async def test_search_seeds_states_on_first_run(session, monkeypatch):
    # No ensure_seed_states() call — simulate a fresh DB where search is hit first.
    from setvault_ingest_sources.base import Candidate

    class _Src:
        kind = "youtube"
        name = "YouTube"

        def search(self, q, *, limit=20):
            return [Candidate("youtube", "v1", "T", "U", 60, None, "https://youtu.be/v1")]

    monkeypatch.setattr(svc, "get_source", lambda kind: _Src())

    cands = await svc.search_source(session, kind="youtube", query="x", limit=5)
    assert cands[0].external_id == "v1"
    st = await svc.get_state(session, "youtube")
    assert st is not None and st.enabled is True


@pytest.mark.asyncio
async def test_search_all_merges_enabled_sources(session, monkeypatch):
    await svc.ensure_seed_states(session)
    from setvault_ingest_sources.base import Candidate

    def fake_get_source(kind):
        class _S:
            def __init__(self, k):
                self.kind = k
                self.name = k

            def search(self, q, *, limit=20):
                return [Candidate(self.kind, f"{self.kind}1", "T", "U", 60, None, f"https://x/{self.kind}1")]
        return _S(kind)
    monkeypatch.setattr(svc, "get_source", fake_get_source)

    result = await svc.search_all_sources(session, query="x", limit_per_source=5)
    kinds = {c.source_kind for c in result.candidates}
    assert {"youtube", "soundcloud", "mixcloud", "internet_archive"} <= kinds
    assert result.errored_kinds == []


@pytest.mark.asyncio
async def test_search_all_isolates_a_failing_source(session, monkeypatch):
    await svc.ensure_seed_states(session)
    from setvault_ingest_sources.base import Candidate, SourceError

    def fake_get_source(kind):
        class _Bad:
            kind = "mixcloud"
            name = "Mixcloud"

            def search(self, q, *, limit=20):
                raise SourceError("down")
        class _Ok:
            def __init__(self, k):
                self.kind = k
                self.name = k

            def search(self, q, *, limit=20):
                return [Candidate(self.kind, f"{self.kind}1", "T", "U", 60, None, "https://x")]
        return _Bad() if kind == "mixcloud" else _Ok(kind)
    monkeypatch.setattr(svc, "get_source", fake_get_source)

    result = await svc.search_all_sources(session, query="x")
    assert "mixcloud" in result.errored_kinds
    assert all(c.source_kind != "mixcloud" for c in result.candidates)
    assert any(c.source_kind == "youtube" for c in result.candidates)
    mix = await svc.get_state(session, "mixcloud")
    assert mix.state == "degraded" and mix.consecutive_failures == 1
    yt = await svc.get_state(session, "youtube")
    assert yt.state == "healthy"


@pytest.mark.asyncio
async def test_search_all_skips_disabled_sources(session, monkeypatch):
    await svc.ensure_seed_states(session)
    await svc.set_enabled(session, "soundcloud", False)
    from setvault_ingest_sources.base import Candidate

    def fake_get_source(kind):
        class _S:
            def __init__(self, k):
                self.kind = k
                self.name = k

            def search(self, q, *, limit=20):
                return [Candidate(self.kind, f"{self.kind}1", "T", "U", 60, None, "https://x")]
        return _S(kind)
    monkeypatch.setattr(svc, "get_source", fake_get_source)

    result = await svc.search_all_sources(session, query="x")
    assert all(c.source_kind != "soundcloud" for c in result.candidates)


@pytest.mark.asyncio
async def test_search_all_propagates_non_sourceerror_bugs(session, monkeypatch):
    # A raw (non-SourceError) exception escaping a source's search() is a bug,
    # not a flaky source — it must surface, not be masked + auto-disabled.
    await svc.ensure_seed_states(session)

    def fake_get_source(kind):
        class _Buggy:
            def __init__(self, k):
                self.kind = k
                self.name = k

            def search(self, q, *, limit=20):
                raise ValueError("programming bug")
        return _Buggy(kind)
    monkeypatch.setattr(svc, "get_source", fake_get_source)

    with pytest.raises(ValueError):
        await svc.search_all_sources(session, query="x")


@pytest.mark.asyncio
async def test_bandcamp_seeded_with_hourly_rate_limit(session):
    await svc.ensure_seed_states(session)
    st = await svc.get_state(session, "bandcamp")
    assert (st.rate_limit_max, st.rate_limit_window_seconds) == (30, 3600)

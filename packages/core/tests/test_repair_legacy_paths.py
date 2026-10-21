import asyncio
import os
import uuid

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.jobs import repair_legacy_paths as mod
from setvault_core.jobs.repair_legacy_paths import damage_report, repair, rewrite_prefix
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User
from setvault_core.models.system import AuditEvent
from setvault_core.models.watch_folder import UnmatchedFile, WatchFolder
from setvault_core.services.passwords import hash_password
from sqlalchemy import delete, select

BUNDLED = {
    "SETVAULT_PG_EMBEDDED": "1",
    "SETVAULT_MEDIA_PATH": "/data/media",
    "SETVAULT_WATCH_FOLDERS_PATH": "/data/watch",
}


@pytest.fixture(autouse=True)
async def _engine_and_clean():
    init_engine(os.environ["TEST_DATABASE_URL"])
    async def _wipe():
        async with session_factory()() as s:
            await s.execute(delete(AuditEvent).where(AuditEvent.action == "system.paths_repaired"))
            await s.execute(delete(UnmatchedFile))
            await s.execute(delete(WatchFolder))
            await s.commit()
    await _wipe()
    yield
    await _wipe()


def test_rewrite_prefix_exact_and_under():
    assert rewrite_prefix("/srv/media", "/srv/media", "/data/media") == "/data/media"
    assert rewrite_prefix("/srv/media/a/b", "/srv/media", "/data/media") == "/data/media/a/b"
    assert rewrite_prefix("/srv/media/", "/srv/media", "/data/media") == "/data/media/"


@pytest.mark.parametrize(
    "value", ["/srv/media2", "/srv/mediabackup", "https://x/srv/media", None],
)
def test_rewrite_prefix_ignores_lookalikes(value):
    assert rewrite_prefix(value, "/srv/media", "/data/media") is None


async def _seed():
    async with session_factory()() as s:
        user = User(email=f"u-{uuid.uuid4().hex[:6]}@x.test",
                    username=f"u{uuid.uuid4().hex[:6]}", display_name="u",
                    password_hash=hash_password("aaaaaaaa"))
        root = MediaRoot(name=f"r-{uuid.uuid4().hex[:6]}", host_path="/srv/media")
        s.add_all([user, root])
        await s.flush()
        wf = WatchFolder(name="w", host_path="/srv/watch/in",
                         target_media_root_id=root.id)
        s.add(wf)
        await s.flush()
        s.add(UnmatchedFile(watch_folder_id=wf.id, file_path="/srv/watch/in/a.mp3"))
        for slug, url in (("b", "/srv/watch/in/b.mp3"), ("c", "https://soundcloud.com/x")):
            s.add(LiveSet(slug=f"{slug}-{uuid.uuid4().hex[:6]}", title="t",
                          media_root_id=root.id, audio_path="x.flac",
                          uploaded_by=user.id, source_url=url))
        await s.commit()


async def _values():
    async with session_factory()() as s:
        return (
            (await s.execute(select(MediaRoot.host_path))).scalars().all(),
            (await s.execute(select(WatchFolder.host_path))).scalars().all(),
            (await s.execute(select(UnmatchedFile.file_path))).scalars().all(),
            sorted((await s.execute(select(LiveSet.source_url))).scalars().all()),
        )


async def test_repair_rewrites_all_four_tables():
    await _seed()
    async with session_factory()() as s:
        counts = await repair(s, BUNDLED)
        await s.commit()
    assert counts == {"media_roots": 1, "watch_folders": 1,
                      "unmatched_files": 1, "live_sets": 1}
    roots, wfs, unm, urls = await _values()
    assert roots == ["/data/media"]
    assert wfs == ["/data/watch/in"]
    assert unm == ["/data/watch/in/a.mp3"]
    assert urls == ["/data/watch/in/b.mp3", "https://soundcloud.com/x"]


async def test_repair_is_idempotent():
    await _seed()
    async with session_factory()() as s:
        await repair(s, BUNDLED)
        await s.commit()
    async with session_factory()() as s:
        counts = await repair(s, BUNDLED)
        await s.commit()
    assert set(counts.values()) == {0}


async def test_repair_noop_when_not_bundled():
    await _seed()
    before = await _values()
    env = {k: v for k, v in BUNDLED.items() if k != "SETVAULT_PG_EMBEDDED"}
    async with session_factory()() as s:
        assert await repair(s, env) == {}
        await s.commit()
    assert await _values() == before


async def test_repair_noop_when_effective_is_legacy():
    await _seed()
    before = await _values()
    env = {**BUNDLED, "SETVAULT_MEDIA_PATH": "/srv/media",
           "SETVAULT_WATCH_FOLDERS_PATH": "/srv/watch"}
    async with session_factory()() as s:
        counts = await repair(s, env)
        await s.commit()
    assert set(counts.values()) <= {0}
    assert await _values() == before


async def test_damage_report_counts_missing_files(tmp_path):
    (tmp_path / "ok.flac").write_bytes(b"x")
    async with session_factory()() as s:
        user = User(email=f"u-{uuid.uuid4().hex[:6]}@x.test",
                    username=f"u{uuid.uuid4().hex[:6]}", display_name="u",
                    password_hash=hash_password("aaaaaaaa"))
        root = MediaRoot(name=f"r-{uuid.uuid4().hex[:6]}", host_path=str(tmp_path))
        s.add_all([user, root])
        await s.flush()
        missing = f"gone-{uuid.uuid4().hex[:6]}"
        for slug, path in ((f"ok-{uuid.uuid4().hex[:6]}", "ok.flac"), (missing, "nope.flac")):
            s.add(LiveSet(slug=slug, title="t", media_root_id=root.id,
                          audio_path=path, uploaded_by=user.id))
        await s.commit()
    env = {**BUNDLED, "SETVAULT_MEDIA_PATH": str(tmp_path)}
    async with session_factory()() as s:
        assert await damage_report(s, env) == (1, [missing])


async def test_main_is_nonfatal_on_error(monkeypatch):
    await _seed()
    before = await _values()

    async def boom(session, env):
        raise RuntimeError("boom")

    monkeypatch.setattr(mod, "repair", boom)
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    for k, v in BUNDLED.items():
        monkeypatch.setenv(k, v)
    await asyncio.to_thread(mod.main)
    init_engine(os.environ["TEST_DATABASE_URL"])
    assert await _values() == before


async def _audit_rows():
    async with session_factory()() as s:
        return (await s.execute(
            select(AuditEvent).where(AuditEvent.action == "system.paths_repaired")
        )).scalars().all()


async def test_run_writes_one_audit_row_then_none_when_idempotent():
    await _seed()
    await mod._run(BUNDLED)
    rows = await _audit_rows()
    assert len(rows) == 1
    assert rows[0].actor_user_id is None
    await mod._run(BUNDLED)
    assert len(await _audit_rows()) == 1


async def test_every_pair_applies_to_every_target():
    async with session_factory()() as s:
        m = MediaRoot(name=f"m-{uuid.uuid4().hex[:6]}", host_path="/srv/media/lib")
        w = MediaRoot(name=f"w-{uuid.uuid4().hex[:6]}", host_path="/srv/watch/lib")
        s.add_all([m, w])
        await s.flush()
        wf = WatchFolder(name="w", host_path="/srv/media/in", target_media_root_id=m.id)
        s.add(wf)
        await s.flush()
        s.add(UnmatchedFile(watch_folder_id=wf.id, file_path="/srv/media/in/a.mp3"))
        await s.commit()
    async with session_factory()() as s:
        await repair(s, BUNDLED)
        await s.commit()
    roots, wfs, unm, _ = await _values()
    assert sorted(roots) == ["/data/media/lib", "/data/watch/lib"]
    assert wfs == ["/data/media/in"]
    assert unm == ["/data/media/in/a.mp3"]


async def test_sql_prefix_rule_proves_lookalikes_and_trailing_slash():
    async with session_factory()() as s:
        for i, p in enumerate(["/srv/media2", "/srv/mediabackup", "/srv/media/"]):
            s.add(MediaRoot(name=f"r{i}-{uuid.uuid4().hex[:6]}", host_path=p))
        await s.commit()
    async with session_factory()() as s:
        await repair(s, BUNDLED)
        await s.commit()
    roots, *_ = await _values()
    assert sorted(roots) == ["/data/media/", "/srv/media2", "/srv/mediabackup"]


async def test_damage_report_covers_subpath_roots(tmp_path):
    sub = tmp_path / "x"
    sub.mkdir()
    async with session_factory()() as s:
        user = User(email=f"u-{uuid.uuid4().hex[:6]}@x.test",
                    username=f"u{uuid.uuid4().hex[:6]}", display_name="u",
                    password_hash=hash_password("aaaaaaaa"))
        root = MediaRoot(name=f"r-{uuid.uuid4().hex[:6]}", host_path=sub.as_posix())
        s.add_all([user, root])
        await s.flush()
        slug = f"gone-{uuid.uuid4().hex[:6]}"
        s.add(LiveSet(slug=slug, title="t", media_root_id=root.id,
                      audio_path="nope.flac", uploaded_by=user.id))
        await s.commit()
    env = {**BUNDLED, "SETVAULT_MEDIA_PATH": tmp_path.as_posix()}
    async with session_factory()() as s:
        assert await damage_report(s, env) == (1, [slug])


def test_read_mounts_decodes_octal_escapes(tmp_path):
    info = tmp_path / "mountinfo"
    info.write_text(
        "22 1 0:21 / / rw - overlay overlay rw\n"
        "30 22 8:1 /x /srv/watch/my\\040inbox rw,relatime - ext4 /dev/sda1 rw\n"
        "garbage\n",
        encoding="utf-8",
    )
    assert mod.read_mounts(str(info)) == ["/", "/srv/watch/my inbox"]


def test_read_mounts_missing_file_is_empty(tmp_path):
    assert mod.read_mounts(str(tmp_path / "nope")) == []


async def _seed_watch_mount_case():
    async with session_factory()() as s:
        root = MediaRoot(name=f"r-{uuid.uuid4().hex[:6]}", host_path="/data/media")
        s.add(root)
        await s.flush()
        live = WatchFolder(name="live", host_path="/srv/watch/incoming",
                           target_media_root_id=root.id)
        stale = WatchFolder(name="stale", host_path="/srv/watch/old",
                            target_media_root_id=root.id)
        s.add_all([live, stale])
        await s.flush()
        s.add_all([
            UnmatchedFile(watch_folder_id=live.id, file_path="/srv/watch/incoming/a.mp3"),
            UnmatchedFile(watch_folder_id=stale.id, file_path="/srv/watch/old/b.mp3"),
        ])
        user = User(email=f"u-{uuid.uuid4().hex[:6]}@x.test",
                    username=f"u{uuid.uuid4().hex[:6]}", display_name="u",
                    password_hash=hash_password("aaaaaaaa"))
        s.add(user)
        await s.flush()
        for url in ("/srv/watch/incoming/c.mp3", "/srv/watch/old/d.mp3"):
            s.add(LiveSet(slug=f"s-{uuid.uuid4().hex[:6]}", title="t",
                          media_root_id=root.id, audio_path="x.flac",
                          uploaded_by=user.id, source_url=url))
        await s.commit()


async def test_repair_skips_rows_under_a_mounted_watch_subfolder(capsys):
    await _seed_watch_mount_case()
    async with session_factory()() as s:
        counts = await repair(s, BUNDLED, mounts=["/", "/data", "/srv/watch/incoming"])
        await s.commit()
    assert counts["watch_folders"] == 1
    assert counts["unmatched_files"] == 1
    assert counts["live_sets"] == 1
    _, wfs, unm, urls = await _values()
    assert sorted(wfs) == ["/data/watch/old", "/srv/watch/incoming"]
    assert sorted(unm) == ["/data/watch/old/b.mp3", "/srv/watch/incoming/a.mp3"]
    assert urls == ["/data/watch/old/d.mp3", "/srv/watch/incoming/c.mp3"]
    out = capsys.readouterr().out
    assert out.count("[setvault]") == 1
    assert "/srv/watch/incoming" in out


async def test_repair_skips_a_mounted_media_root():
    async with session_factory()() as s:
        s.add_all([
            MediaRoot(name=f"nas-{uuid.uuid4().hex[:6]}", host_path="/srv/media/nas"),
            MediaRoot(name=f"main-{uuid.uuid4().hex[:6]}", host_path="/srv/media"),
        ])
        await s.commit()
    async with session_factory()() as s:
        counts = await repair(s, BUNDLED, mounts=["/srv/media/nas/"])
        await s.commit()
    assert counts["media_roots"] == 1
    roots, *_ = await _values()
    assert sorted(roots) == ["/data/media", "/srv/media/nas"]


async def test_repair_ignores_unrelated_mounts():
    await _seed()
    async with session_factory()() as s:
        plain = await repair(s, BUNDLED, mounts=[])
        await s.rollback()
    async with session_factory()() as s:
        counts = await repair(s, BUNDLED, mounts=["/nas", "/srv/media2", "/data/media"])
        await s.commit()
    assert counts == plain
    roots, wfs, *_ = await _values()
    assert roots == ["/data/media"]
    assert wfs == ["/data/watch/in"]


async def test_damage_report_ignores_sets_on_a_mounted_legacy_root():
    async with session_factory()() as s:
        user = User(email=f"u-{uuid.uuid4().hex[:6]}@x.test",
                    username=f"u{uuid.uuid4().hex[:6]}", display_name="u",
                    password_hash=hash_password("aaaaaaaa"))
        nas = MediaRoot(name=f"nas-{uuid.uuid4().hex[:6]}", host_path="/srv/media/nas")
        s.add_all([user, nas])
        await s.flush()
        s.add(LiveSet(slug=f"nas-{uuid.uuid4().hex[:6]}", title="t",
                      media_root_id=nas.id, audio_path="nope.flac", uploaded_by=user.id))
        await s.commit()
    mounts = ["/srv/media/nas"]
    async with session_factory()() as s:
        await repair(s, BUNDLED, mounts)
        await s.commit()
    async with session_factory()() as s:
        assert await damage_report(s, BUNDLED, mounts) == (0, [])

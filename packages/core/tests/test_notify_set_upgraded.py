"""set_upgraded notification (Phase 7D Task 12): payload labels, preference, email."""
from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.models.engagement_3c import InAppNotification
from setvault_core.models.identity import NotificationPreference, User
from setvault_core.services import notifications
from setvault_core.services.audio_quality import quality_label
from sqlalchemy import select


@pytest.fixture(autouse=True)
def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])


@pytest.fixture
def emails(monkeypatch):
    sent: list[dict] = []

    async def fake(session, *, redis_url, to, subject, text):
        sent.append({"to": to, "subject": subject, "text": text})
        return True

    monkeypatch.setattr(notifications, "enqueue_email", fake)
    return sent


def _event():
    return SimpleNamespace(
        id=uuid.uuid4(),
        from_tier="ok", from_codec="mp3", from_bitrate_kbps=128,
        from_source_type="url_rip", from_source_url="https://www.youtube.com/watch?v=abc",
        to_tier="lossless", to_codec="flac", to_bitrate_kbps=None,
        to_source_type="url_rip", to_source_url="https://artist.bandcamp.com/album/x",
    )


async def _owner(s) -> User:
    u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
             display_name="u", password_hash="x")
    s.add(u)
    await s.flush()
    return u


def _target(owner: User):
    return SimpleNamespace(id=uuid.uuid4(), slug="set-x", title="Set X", uploaded_by=owner.id)


async def _notes(s, uid):
    return (await s.execute(
        select(InAppNotification).where(InAppNotification.user_id == uid))).scalars().all()


async def test_notify_set_upgraded_in_app_payload(emails):
    async with session_factory()() as s:
        owner = await _owner(s)
        target = _target(owner)
        await notifications.notify_set_upgraded(s, target, _event())
        (n,) = await _notes(s, owner.id)
        assert n.kind == "set_upgraded" and n.subject_type == "set"
        assert n.subject_id == target.id
        assert n.payload == {
            "set_slug": "set-x", "set_title": "Set X",
            "from_label": "MP3 128 kbps (YouTube)", "to_label": "FLAC (Bandcamp)",
        }
        # No preference row: in-app only, email is opt-in.
        assert emails == []
        await s.rollback()


async def test_email_content(emails):
    async with session_factory()() as s:
        owner = await _owner(s)
        s.add(NotificationPreference(user_id=owner.id, kind="set_upgraded", channel="email"))
        await s.flush()
        await notifications.notify_set_upgraded(s, _target(owner), _event())
        assert [e["subject"] for e in emails] == ["A set in your SetVault library was upgraded"]
        assert emails[0]["to"] == owner.email
        assert "MP3 128 kbps (YouTube) -> FLAC (Bandcamp)" in emails[0]["text"]
        await s.rollback()


async def test_no_owner_notifies_nobody(emails):
    async with session_factory()() as s:
        target = SimpleNamespace(id=uuid.uuid4(), slug="s", title="S", uploaded_by=None)
        await notifications.notify_set_upgraded(s, target, _event())
        assert emails == []
        await s.rollback()


@pytest.mark.parametrize(
    ("channel", "in_app", "email"),
    [(None, 1, 0), ("off", 0, 0), ("in_app", 1, 0), ("email", 0, 1), ("both", 1, 1)],
)
async def test_notify_respects_preference(emails, channel, in_app, email):
    async with session_factory()() as s:
        owner = await _owner(s)
        if channel:
            s.add(NotificationPreference(user_id=owner.id, kind="set_upgraded", channel=channel))
            await s.flush()
        await notifications.notify_set_upgraded(s, _target(owner), _event())
        assert len(await _notes(s, owner.id)) == in_app
        assert len(emails) == email
        await s.rollback()


def test_quality_label_examples():
    assert quality_label("ok", "mp3", 128, "youtube") == "MP3 128 kbps (YouTube)"
    assert quality_label("lossless", "flac", None, "bandcamp") == "FLAC (Bandcamp)"
    # Lossless ignores a bitrate; lossy without one shows the codec alone.
    assert quality_label("lossless", "flac", 900, None) == "FLAC"
    assert quality_label("ok", "aac", None, "soundcloud") == "AAC (SoundCloud)"
    assert quality_label("lossless", "pcm_s16le", 1411, "upload") == "PCM (Upload)"
    assert quality_label("ok", "mp3", 128, "url_rip") == "MP3 128 kbps (Web link)"
    assert quality_label("good", None, None, "watch_folder") == "Good quality (Watch folder)"
    # One spelling for the ok tier everywhere (en.json: "OK quality").
    assert quality_label("ok", None, None, None) == "OK quality"
    assert quality_label(None, None, None, None) == "Unknown quality"
    assert quality_label("ok", "mp3", 128, "odd_thing") == "MP3 128 kbps (Odd thing)"

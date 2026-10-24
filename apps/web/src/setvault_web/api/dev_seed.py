"""Dev-only e2e seed endpoint.

This module exposes ``POST /api/dev/seed-e2e`` which idempotently provisions an
admin user, a MediaRoot at a stable temp path, and a published LiveSet with
slug ``seeded-set`` so Playwright tests can sign in and exercise the player
without uploading real audio. A 1-second silent WAV is written to disk to back
the stream endpoint.

It is **only** registered by ``setvault_web.main.create_app`` when the
environment variable ``SETVAULT_DEV_SEED`` is set to a truthy value. Do not
enable this in production: the response includes the seed admin's password.
"""

from __future__ import annotations

import json
import os
import struct
import tempfile
import uuid
import wave
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from setvault_core.models.catalog import (
    Artist,
    LiveSet,
    LiveSetArtist,
    LiveSetTag,
    MediaRoot,
    Tag,
    Venue,
)
from setvault_core.models.identity import User
from setvault_core.models.tracklist import Track, TracklistEntry
from setvault_core.services.passwords import hash_password
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.deps import db_session

router = APIRouter(prefix="/api/dev", tags=["dev"])

SEED_ADMIN_EMAIL = "admin@example.test"
SEED_ADMIN_PASSWORD = "hunter2hunter2"  # noqa: S105 — dev-only fixture
SEED_SLUG = "seeded-set"
SEED_MEDIA_ROOT_NAME = "e2e-seed"
SEED_STREAMING_REL = "test/silent.wav"
SEED_WAVEFORM_REL = "test/seed.waveform.json"


def _seed_root_path() -> Path:
    """Stable path under the OS temp dir so reruns reuse the same on-disk fixture."""
    root = Path(tempfile.gettempdir()) / "setvault-e2e-seed"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _ensure_silent_wav(root: Path) -> Path:
    """Write a tiny 1-second silent mono 8kHz 16-bit WAV if not already present."""
    target = root / SEED_STREAMING_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        with wave.open(str(target), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(struct.pack("<" + "h" * 8000, *([0] * 8000)))
    return target


def _ensure_waveform_json(root: Path) -> None:
    """Write a valid audiowaveform v2 file (~1s, matches the silent WAV).

    Only the main seeded set points at it; the extra sets have no
    ``waveform_path`` so the decode-from-stream fallback stays covered.
    """
    target = root / SEED_WAVEFORM_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    data = [v for i in range(100) for v in (-(20 + i % 50), 20 + i % 50)]
    target.write_text(
        json.dumps({
            "version": 2, "channels": 1, "sample_rate": 8000,
            "samples_per_pixel": 80, "bits": 8, "length": 100, "data": data,
        }),
        encoding="utf-8",
    )


SEED_TAG_SLUG = "e2e-house"
SEED_VENUE_SLUG = "e2e-club"
# (slug, title, set date, hours before first seeding, tagged, at venue).
# Set date order is the REVERSE of created_at order, so "recently added" and
# "by date" sorts give different results. Titles avoid "seeded set".
SEED_EXTRA_SETS = [
    ("e2e-alpha", "Alpha Night", date(2024, 6, 1), 3, True, True),
    ("e2e-bravo", "Bravo Session", date(2022, 6, 1), 2, True, False),
    ("e2e-charlie", "Charlie Closing", date(2020, 6, 1), 1, False, False),
]

# The set the metadata-editor e2e test (tests/set-edit.test.ts) mutates; no
# other test may use it. The slug avoids the "e2e-" prefix that the library
# tests count. The test puts it back to this state itself before each run, so
# the seed only creates it.
EDIT_SET_SLUG = "edit-target"
EDIT_SET_TITLE = "Edit Target"
EDIT_ARTIST_SLUG = "e2e-resident"
EDIT_ARTIST_NAME = "E2E Resident"

# Read-only set for tests/browse.test.ts: one resolved tracklist entry. No
# "e2e-" prefix (the library tests count those).
TRACK_SET_SLUG = "track-link"
TRACK_SET_TITLE = "Track Link Set"
TRACK_TITLE = "Browse Anthem"


class SeedAdminOut(BaseModel):
    email: str
    password: str


class SeedSetOut(BaseModel):
    slug: str


class SeedOut(BaseModel):
    admin: SeedAdminOut
    set: SeedSetOut


@router.post("/seed-e2e", response_model=SeedOut)
async def seed_e2e(session: Annotated[AsyncSession, Depends(db_session)]) -> SeedOut:
    # Playwright runs test files in parallel; each loginAs() races against
    # this endpoint on a fresh DB. Serialize concurrent seeders with a
    # transaction-scoped advisory lock (auto-released at commit). The
    # constant key is arbitrary — just a stable u32 unique to this seed.
    await session.execute(text("SELECT pg_advisory_xact_lock(0x5e7eedaa)"))

    # 1. Ensure admin
    admin = (
        await session.execute(select(User).where(User.email == SEED_ADMIN_EMAIL))
    ).scalar_one_or_none()
    if admin is None:
        admin = User(
            email=SEED_ADMIN_EMAIL,
            username="admin",
            display_name="Admin",
            password_hash=hash_password(SEED_ADMIN_PASSWORD),
            role="admin",
        )
        session.add(admin)
        await session.flush()
    else:
        # Always reset to the known seed password so tests that change it
        # (e.g. the settings change-password e2e) don't leak between runs.
        admin.password_hash = hash_password(SEED_ADMIN_PASSWORD)

    # 2. Ensure on-disk silent fixture + MediaRoot row
    root_path = _seed_root_path()
    _ensure_silent_wav(root_path)
    _ensure_waveform_json(root_path)
    media_root = (
        await session.execute(
            select(MediaRoot).where(MediaRoot.name == SEED_MEDIA_ROOT_NAME)
        )
    ).scalar_one_or_none()
    if media_root is None:
        media_root = MediaRoot(
            name=SEED_MEDIA_ROOT_NAME,
            host_path=str(root_path),
            enabled=True,
            default_for_ingest=False,
            last_health_status="ok",
        )
        session.add(media_root)
        await session.flush()
    else:
        # Keep host_path in sync (e.g. if tmp dir changes between runs)
        media_root.host_path = str(root_path)

    # 3. Ensure LiveSet
    live = (
        await session.execute(select(LiveSet).where(LiveSet.slug == SEED_SLUG))
    ).scalar_one_or_none()
    if live is None:
        live = LiveSet(
            id=uuid.uuid4(),
            slug=SEED_SLUG,
            title="seeded set",
            media_root_id=media_root.id,
            audio_path="originals/seed/audio.wav",
            streaming_path=SEED_STREAMING_REL,
            waveform_path=SEED_WAVEFORM_REL,
            duration_seconds=1,
            status="published",
            source_type="upload",
            uploaded_by=admin.id,
            deleted_at=None,
        )
        session.add(live)
    else:
        # Re-publish in case earlier runs soft-deleted it
        live.deleted_at = None
        live.purge_after_at = None
        live.status = "published"
        live.streaming_path = SEED_STREAMING_REL
        live.waveform_path = SEED_WAVEFORM_REL
        live.media_root_id = media_root.id

    # 4. Extra published sets (idempotent: created once, never rewritten)
    tag = (await session.execute(select(Tag).where(Tag.slug == SEED_TAG_SLUG))).scalar_one_or_none()
    if tag is None:
        tag = Tag(name="E2E House", slug=SEED_TAG_SLUG, kind="custom")
        session.add(tag)
    venue = (
        await session.execute(select(Venue).where(Venue.slug == SEED_VENUE_SLUG))
    ).scalar_one_or_none()
    if venue is None:
        venue = Venue(name="E2E Club", slug=SEED_VENUE_SLUG, kind="club")
        session.add(venue)
    await session.flush()
    now = datetime.now(UTC)
    for slug, title, set_date, hours, tagged, at_venue in SEED_EXTRA_SETS:
        exists = (
            await session.execute(select(LiveSet.id).where(LiveSet.slug == slug))
        ).scalar_one_or_none()
        if exists is not None:
            continue
        extra = LiveSet(
            id=uuid.uuid4(),
            slug=slug,
            title=title,
            date=set_date,
            media_root_id=media_root.id,
            audio_path=f"originals/seed/{slug}.wav",
            streaming_path=SEED_STREAMING_REL,
            duration_seconds=1,
            status="published",
            source_type="upload",
            uploaded_by=admin.id,
            venue_id=venue.id if at_venue else None,
            created_at=now - timedelta(hours=hours),
        )
        session.add(extra)
        await session.flush()
        if tagged:
            session.add(LiveSetTag(live_set_id=extra.id, tag_id=tag.id))

    # 5. The metadata editor's own set: one artist, at the seed venue.
    resident = (
        await session.execute(select(Artist).where(Artist.slug == EDIT_ARTIST_SLUG))
    ).scalar_one_or_none()
    if resident is None:
        resident = Artist(name=EDIT_ARTIST_NAME, slug=EDIT_ARTIST_SLUG)
        session.add(resident)
        await session.flush()
    edit_exists = (
        await session.execute(select(LiveSet.id).where(LiveSet.slug == EDIT_SET_SLUG))
    ).scalar_one_or_none()
    if edit_exists is None:
        edit_set = LiveSet(
            id=uuid.uuid4(),
            slug=EDIT_SET_SLUG,
            title=EDIT_SET_TITLE,
            media_root_id=media_root.id,
            audio_path=f"originals/seed/{EDIT_SET_SLUG}.wav",
            streaming_path=SEED_STREAMING_REL,
            duration_seconds=1,
            status="published",
            source_type="upload",
            uploaded_by=admin.id,
            venue_id=venue.id,
            created_at=now - timedelta(hours=4),
        )
        session.add(edit_set)
        await session.flush()
        session.add(LiveSetArtist(live_set_id=edit_set.id, artist_id=resident.id, position=0))

    # 6. A set with a resolved tracklist entry, for the browse e2e test
    # (tests/browse.test.ts): "Other sets with this track" needs a track_id.
    track_set_exists = (
        await session.execute(select(LiveSet.id).where(LiveSet.slug == TRACK_SET_SLUG))
    ).scalar_one_or_none()
    if track_set_exists is None:
        track = Track(title=TRACK_TITLE, primary_artist_id=resident.id)
        session.add(track)
        track_set = LiveSet(
            id=uuid.uuid4(),
            slug=TRACK_SET_SLUG,
            title=TRACK_SET_TITLE,
            media_root_id=media_root.id,
            audio_path=f"originals/seed/{TRACK_SET_SLUG}.wav",
            streaming_path=SEED_STREAMING_REL,
            duration_seconds=1,
            status="published",
            source_type="upload",
            uploaded_by=admin.id,
            created_at=now - timedelta(hours=5),
        )
        session.add(track_set)
        await session.flush()
        session.add(TracklistEntry(
            live_set_id=track_set.id,
            position=0,
            start_seconds=0,
            raw_label=f"{EDIT_ARTIST_NAME} - {TRACK_TITLE}",
            track_id=track.id,
            status="resolved",
            created_by=admin.id,
        ))

    await session.commit()
    return SeedOut(
        admin=SeedAdminOut(email=SEED_ADMIN_EMAIL, password=SEED_ADMIN_PASSWORD),
        set=SeedSetOut(slug=SEED_SLUG),
    )


def is_enabled() -> bool:
    return os.environ.get("SETVAULT_DEV_SEED", "").lower() in ("1", "true", "yes")

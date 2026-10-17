from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot, SetFingerprint
from setvault_core.progress import ProgressEvent, publish
from setvault_core.services.audit import log as audit_log

logger = logging.getLogger(__name__)


async def fingerprint_audio(live_set_id: str) -> None:
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    async with session_factory()() as s:
        live = await s.get(LiveSet, uuid.UUID(live_set_id))
        if live is None:
            raise RuntimeError(f"LiveSet {live_set_id} missing")
        root = await s.get(MediaRoot, live.media_root_id)
        if root is None:
            raise RuntimeError("MediaRoot vanished")
        path = Path(root.host_path) / live.audio_path

        publish(ProgressEvent(
            kind="fingerprint", live_set_id=live_set_id, job_id=live_set_id,
            progress_pct=20, message="fingerprinting",
        ))

        # No check=True: chromaprint 1.5.1 (Debian bookworm, Ubuntu noble)
        # exits 3 with "Error decoding audio frame (End of file)" after
        # printing a valid fingerprint. Trust the output, not the exit code.
        out = await asyncio.to_thread(
            subprocess.run, ["fpcalc", "-json", str(path)],
            capture_output=True, text=True,
        )
        try:
            data = json.loads(out.stdout)
            fp = data["fingerprint"]
        except (ValueError, KeyError) as exc:
            raise RuntimeError(
                f"fpcalc failed (exit {out.returncode}): {out.stderr.strip()[-500:]}",
            ) from exc
        if not fp:
            raise RuntimeError(f"fpcalc returned an empty fingerprint (exit {out.returncode})")
        duration = float(data.get("duration", live.duration_seconds or 0))
        digest = hashlib.sha256(fp.encode("ascii")).hexdigest()

        # Every arrival records its own fingerprint row (duplicates included),
        # so a hash can match many rows. The earliest other set is the original.
        matches = (await s.execute(
            select(SetFingerprint)
            .where(SetFingerprint.fingerprint_hash == digest)
            .order_by(SetFingerprint.created_at),
        )).scalars().all()
        own = [m for m in matches if m.live_set_id == live.id]
        existing = next(
            (m for m in matches
             if m.live_set_id != live.id and abs(m.duration_seconds - duration) < 2),
            None,
        )
        if existing is not None and live.duplicate_of is None:
            existing_live = await s.get(LiveSet, existing.live_set_id)
            if existing_live is not None:
                live.duplicate_of = existing_live.id
                live.status = "draft"
                if existing_live.deleted_at is not None:
                    # Spec §A6: "if the existing set is soft-deleted in the
                    # recycle bin, undelete the existing set and discard the
                    # new one." We undelete + soft-delete the new arrival with
                    # a 1-hour purge window so the recycle-bin purge job
                    # (5B.5) cleans it up without admin intervention.
                    existing_live.deleted_at = None
                    existing_live.purge_after_at = None
                    now = datetime.now(UTC)
                    live.deleted_at = now
                    live.purge_after_at = now + timedelta(hours=1)
                    audit_action = "ingest.duplicate_of_recycled"
                else:
                    audit_action = "ingest.duplicate_detected"
                await audit_log(
                    s,
                    actor_user_id=existing_live.uploaded_by,
                    actor_kind="system",
                    action=audit_action,
                    target_type="LiveSet",
                    target_id=str(live.id),
                    after={
                        "duplicate_of": str(existing_live.id),
                        "duration_seconds": duration,
                    },
                )

        # A re-run of the pipeline on the same set must not add a second row.
        if not own:
            s.add(SetFingerprint(
                live_set_id=live.id, fingerprint_hash=digest, duration_seconds=duration,
            ))
        await s.commit()

        publish(ProgressEvent(
            kind="fingerprint", live_set_id=live_set_id, job_id=live_set_id,
            progress_pct=30,
            message=(
                "duplicate of existing set" if live.duplicate_of
                else "unique fingerprint"
            ),
        ))


def fingerprint_audio_sync(live_set_id: str) -> None:
    run_job(fingerprint_audio(live_set_id))

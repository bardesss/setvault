from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from pathlib import Path

from setvault_core.db import init_engine, session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.progress import ProgressEvent, publish

_STDERR_TAIL = 400


def _render_peaks(src: Path, out_tmp: Path, pixels_per_second: int) -> None:
    """Decode ``src`` to WAV with ffmpeg and stream it into audiowaveform.

    audiowaveform (1.10.x) only decodes WAV/FLAC/MP3/Ogg/Opus — not AAC/m4a/mp4,
    which is what SoundCloud commonly hands back. ffmpeg decodes everything we
    ingest, so we transcode to WAV on the fly and pipe it in over stdin. This is
    audiowaveform's own documented workaround for unsupported inputs, and it
    avoids spilling a multi-GB intermediate WAV to disk.
    """
    decode = [
        "ffmpeg", "-hide_banner", "-nostdin", "-i", str(src),
        "-f", "wav", "pipe:1",
    ]
    peaks = [
        "audiowaveform", "--input-format", "wav", "-i", "-",
        "-o", str(out_tmp), "--output-format", "json",
        "--pixels-per-second", str(pixels_per_second), "--bits", "8",
    ]
    decoder = subprocess.Popen(  # noqa: S603
        decode, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        renderer = subprocess.Popen(  # noqa: S603
            peaks, stdin=decoder.stdout,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
    finally:
        # Hand the read end entirely to audiowaveform so ffmpeg gets EOF/SIGPIPE.
        if decoder.stdout is not None:
            decoder.stdout.close()

    _, peaks_err = renderer.communicate()
    decoder.wait()
    decode_err = decoder.stderr.read() if decoder.stderr else b""

    if renderer.returncode != 0:
        tail = peaks_err.decode("utf-8", "replace").strip()[-_STDERR_TAIL:]
        raise RuntimeError(f"audiowaveform failed: {tail or '(no stderr)'}")
    # ffmpeg can exit non-zero via SIGPIPE once audiowaveform has consumed enough;
    # only treat that as fatal when no peaks file was actually produced.
    if decoder.returncode not in (0, None) and not out_tmp.exists():
        tail = decode_err.decode("utf-8", "replace").strip()[-_STDERR_TAIL:]
        raise RuntimeError(f"ffmpeg decode failed: {tail or '(no stderr)'}")


async def generate_waveform(live_set_id: str) -> None:
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    async with session_factory()() as s:
        live = await s.get(LiveSet, uuid.UUID(live_set_id))
        if live is None:
            raise RuntimeError(f"LiveSet {live_set_id} missing")
        root = await s.get(MediaRoot, live.media_root_id)
        if root is None:
            raise RuntimeError("MediaRoot vanished")
        src = Path(root.host_path) / live.audio_path
        rel = f"waveform/{live.id}.json"
        dest = Path(root.host_path) / rel
        tmp = dest.with_suffix(".json.tmp")
        dest.parent.mkdir(parents=True, exist_ok=True)

        publish(ProgressEvent(
            kind="waveform", live_set_id=live_set_id, job_id=live_set_id,
            progress_pct=85, message="computing peaks",
        ))
        pixels_per_second = 20
        await asyncio.to_thread(_render_peaks, src, tmp, pixels_per_second)
        tmp.replace(dest)

        live.waveform_path = rel
        await s.commit()
        publish(ProgressEvent(
            kind="waveform", live_set_id=live_set_id, job_id=live_set_id,
            progress_pct=95, message="peaks written",
        ))

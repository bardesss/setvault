"""Tests for storage.place_audio_file — hardlink + atomic-move placement."""
from __future__ import annotations

from pathlib import Path

import pytest
from setvault_core.services.storage import place_audio_file


def _write(path: Path, content: bytes = b"hello") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_same_fs_uses_hardlink(tmp_path: Path):
    src = tmp_path / "src" / "audio.opus"
    dst = tmp_path / "dst" / "audio.opus"
    _write(src, b"x" * 64)

    mode = place_audio_file(src, dst)

    assert mode == "hardlinked"
    assert dst.exists()
    assert dst.read_bytes() == b"x" * 64
    # Hardlink semantics: both names refer to the same inode
    assert src.stat().st_ino == dst.stat().st_ino


def test_creates_destination_parent_dirs(tmp_path: Path):
    src = tmp_path / "audio.opus"
    dst = tmp_path / "a" / "b" / "c" / "audio.opus"
    _write(src)

    place_audio_file(src, dst)

    assert dst.exists()


def test_missing_source_raises(tmp_path: Path):
    src = tmp_path / "nope.opus"
    dst = tmp_path / "dst.opus"
    with pytest.raises(FileNotFoundError):
        place_audio_file(src, dst)


def test_overwrites_stale_dst_on_hardlink(tmp_path: Path):
    src = tmp_path / "audio.opus"
    dst = tmp_path / "dst.opus"
    _write(src, b"new")
    _write(dst, b"old")

    mode = place_audio_file(src, dst)

    assert mode == "hardlinked"
    assert dst.read_bytes() == b"new"


def test_cross_fs_falls_back_to_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """If hardlink-time stat reports different st_dev values, we copy + rename."""
    src = tmp_path / "audio.opus"
    dst = tmp_path / "dst" / "audio.opus"
    _write(src, b"y" * 32)

    # Force os.link to never be tried by making the device-IDs look different.
    real_stat = Path.stat

    def fake_stat(self, *args, **kw):
        st = real_stat(self, *args, **kw)
        if self == src:
            # Pretend src lives on device 999
            class _Stat:
                pass
            for attr in dir(st):
                if not attr.startswith("__"):
                    try:
                        setattr(_Stat, attr, getattr(st, attr))
                    except (AttributeError, TypeError):
                        pass
            _Stat.st_dev = 999
            _Stat.st_ino = st.st_ino
            _Stat.st_size = st.st_size
            return _Stat
        return st

    monkeypatch.setattr(Path, "stat", fake_stat)

    mode = place_audio_file(src, dst)

    assert mode == "copied"
    assert dst.exists()
    assert dst.read_bytes() == b"y" * 32
    # No leftover .tmp file
    assert not list(dst.parent.glob("*.tmp"))
    # Different inodes (copy, not hardlink)
    real_src_ino = real_stat(src).st_ino
    real_dst_ino = real_stat(dst).st_ino
    assert real_src_ino != real_dst_ino


# --- overwrite=False: exclusive create (P2a A4 renames) ----------------------


def _pretend_cross_fs(monkeypatch: pytest.MonkeyPatch, src: Path) -> None:
    """Make src report another device so placement takes the copy path."""
    import os as _os

    real_stat = Path.stat

    def fake_stat(self, *args, **kw):
        st = real_stat(self, *args, **kw)
        if self == src:
            fields = list(st)
            fields[2] = 999  # st_dev
            return _os.stat_result(fields)
        return st

    monkeypatch.setattr(Path, "stat", fake_stat)


def test_no_overwrite_hardlink_refuses_existing_dst(tmp_path: Path):
    src = tmp_path / "audio.opus"
    dst = tmp_path / "dst.opus"
    _write(src, b"new")
    _write(dst, b"old")

    with pytest.raises(FileExistsError):
        place_audio_file(src, dst, overwrite=False)

    assert dst.read_bytes() == b"old"
    assert src.read_bytes() == b"new"


def test_no_overwrite_copy_places_new_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    src = tmp_path / "audio.opus"
    dst = tmp_path / "dst" / "audio.opus"
    _write(src, b"y" * 32)
    _pretend_cross_fs(monkeypatch, src)

    assert place_audio_file(src, dst, overwrite=False) == "copied"

    assert dst.read_bytes() == b"y" * 32
    assert not list(dst.parent.glob("*.tmp"))


def test_no_overwrite_copy_refuses_existing_dst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    src = tmp_path / "audio.opus"
    dst = tmp_path / "dst" / "audio.opus"
    _write(src, b"new")
    _write(dst, b"old")
    _pretend_cross_fs(monkeypatch, src)

    with pytest.raises(FileExistsError):
        place_audio_file(src, dst, overwrite=False)

    assert dst.read_bytes() == b"old"
    assert not list(dst.parent.glob("*.tmp"))


@pytest.mark.parametrize("taken", [False, True])
def test_no_overwrite_copy_without_hardlink_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, taken: bool,
):
    """A filesystem without hardlinks: the name is reserved exclusively."""
    import os as _os

    src = tmp_path / "audio.opus"
    dst = tmp_path / "dst" / "audio.opus"
    _write(src, b"new")
    if taken:
        _write(dst, b"old")
    _pretend_cross_fs(monkeypatch, src)

    def no_link(*a, **kw):
        raise PermissionError("hardlinks not supported")

    monkeypatch.setattr(_os, "link", no_link)

    if taken:
        with pytest.raises(FileExistsError):
            place_audio_file(src, dst, overwrite=False)
        assert dst.read_bytes() == b"old"
    else:
        assert place_audio_file(src, dst, overwrite=False) == "copied"
        assert dst.read_bytes() == b"new"
    assert not list(dst.parent.glob("*.tmp"))

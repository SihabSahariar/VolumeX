"""VB-CABLE packaging and trust checks. Nothing here installs anything or shows a UAC prompt."""
from __future__ import annotations

import io
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

from volumex.platform import vbcable

OFFICIAL = Path(__file__).resolve().parents[2] / "third_party" / "vbcable" / vbcable.SETUP_EXE
needs_package = pytest.mark.skipif(not OFFICIAL.exists(), reason="run packaging/fetch_vbcable.py first")


@pytest.fixture
def no_elevation(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("must not start an elevated process in tests")

    monkeypatch.setattr(vbcable, "run_elevated", refuse)


@needs_package
def test_official_setup_is_signed_by_vb_audio():
    assert vbcable.verify_signature(OFFICIAL)


@needs_package
def test_bundled_package_is_found_from_source():
    assert vbcable.bundled_dir() == OFFICIAL.parent


def test_other_signed_programs_are_rejected():
    assert not vbcable.verify_signature(Path(sys.executable))  # signed by the PSF, not VB-Audio


def test_missing_file_is_rejected(tmp_path):
    assert not vbcable.verify_signature(tmp_path / vbcable.SETUP_EXE)


def test_install_refuses_an_unsigned_setup(tmp_path, no_elevation):
    shutil.copy(sys.executable, tmp_path / vbcable.SETUP_EXE)
    with pytest.raises(vbcable.VbCableError):
        vbcable.install(tmp_path)
    with pytest.raises(vbcable.VbCableError):
        vbcable.uninstall(tmp_path)


class _FakeResponse(io.BytesIO):
    headers = {"Content-Length": "0"}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _zip_with_fake_setup() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(vbcable.SETUP_EXE, b"MZ not really a program")
    return buf.getvalue()


def test_download_rejects_a_changed_package_when_strict(tmp_path, monkeypatch):
    monkeypatch.setattr(vbcable.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(_zip_with_fake_setup()))
    with pytest.raises(vbcable.VbCableError, match="changed"):
        vbcable.download_package(tmp_path / "out", strict_hash=True)
    assert not (tmp_path / "out").exists()


def test_download_rejects_an_unsigned_package(tmp_path, monkeypatch):
    monkeypatch.setattr(vbcable.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(_zip_with_fake_setup()))
    with pytest.raises(vbcable.VbCableError, match="signed"):
        vbcable.download_package(tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_download_failure_is_reported(tmp_path, monkeypatch):
    def offline(*_a, **_k):
        raise OSError("no network")

    monkeypatch.setattr(vbcable.urllib.request, "urlopen", offline)
    with pytest.raises(vbcable.VbCableError, match="download"):
        vbcable.download_package(tmp_path / "out")


def test_find_package_uses_the_cache_before_downloading(tmp_path, monkeypatch):
    monkeypatch.setattr(vbcable, "bundled_dir", lambda: None)
    monkeypatch.setattr(vbcable, "_cache_dir", lambda: tmp_path)
    (tmp_path / vbcable.SETUP_EXE).write_bytes(b"x")
    assert vbcable.find_package(download=False) == tmp_path


def test_find_package_without_download_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(vbcable, "bundled_dir", lambda: None)
    monkeypatch.setattr(vbcable, "_cache_dir", lambda: tmp_path)
    with pytest.raises(vbcable.VbCableError):
        vbcable.find_package(download=False)


def test_demo_mode_never_installs(qtbot, monkeypatch, no_elevation):
    from volumex.ui.vbcable_task import VbCableInstall

    monkeypatch.setenv("VOLUMEX_DEMO", "1")
    task = VbCableInstall()
    with qtbot.waitSignal(task.done, timeout=5000) as blocker:
        task.start()
    ok, cancelled, message = blocker.args
    assert not ok and not cancelled and "never install" in message
    task.wait()

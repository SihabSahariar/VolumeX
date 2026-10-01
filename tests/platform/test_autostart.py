"""default_command only: never touches the registry."""
from __future__ import annotations

import sys

from volumex.platform.autostart import default_command


def test_frozen(monkeypatch, tmp_path):
    exe = tmp_path / "VolumeX.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert default_command() == f'"{exe}" --minimized'
    assert default_command(minimized=False) == f'"{exe}"'


def test_source_uses_pythonw(monkeypatch, tmp_path):
    python = tmp_path / "python.exe"
    pythonw = tmp_path / "pythonw.exe"
    python.touch()
    pythonw.touch()
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "executable", str(python))
    assert default_command() == f'"{pythonw}" -m volumex --minimized'
    assert default_command(minimized=False) == f'"{pythonw}" -m volumex'


def test_source_without_pythonw_falls_back(monkeypatch, tmp_path):
    python = tmp_path / "python.exe"
    python.touch()
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "executable", str(python))
    assert default_command() == f'"{python}" -m volumex --minimized'

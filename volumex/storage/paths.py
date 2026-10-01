"""Where VolumeX keeps its files."""
from __future__ import annotations

import os
from pathlib import Path

from volumex import APP_NAME


def _base(env_var: str) -> Path:
    override = os.environ.get("VOLUMEX_DATA_DIR")  # demo mode and tests keep their files apart
    if override:
        path = Path(override)
        path.mkdir(parents=True, exist_ok=True)
        return path
    root = os.environ.get(env_var) or str(Path.home() / "AppData" / ("Roaming" if env_var == "APPDATA" else "Local"))
    path = Path(root) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_file() -> Path:
    return _base("APPDATA") / "settings.json"


def journal_file() -> Path:
    return _base("LOCALAPPDATA") / "journal.json"


def cache_dir(name: str) -> Path:
    path = _base("LOCALAPPDATA") / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    path = _base("LOCALAPPDATA") / "logs"
    path.mkdir(exist_ok=True)
    return path


def atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)

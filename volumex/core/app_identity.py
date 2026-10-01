"""Stable identity for an app across restarts and PID changes."""
from __future__ import annotations

import ntpath
import re

from .models import SYSTEM_SOUNDS_KEY


def app_key(exe_path: str, pid: int) -> str:
    """Key used to remember settings for an app.

    All processes of the same executable share one key, so a browser with many
    processes shows up as one app.
    """
    if pid == 0 or not exe_path:
        return SYSTEM_SOUNDS_KEY
    return ntpath.normcase(ntpath.normpath(exe_path))


_WORD_SPLIT = re.compile(r"[_\-.]+")


def pretty_exe_name(exe_path: str) -> str:
    """Fallback display name: 'C:/x/my_app.exe' -> 'My App'."""
    stem = ntpath.splitext(ntpath.basename(exe_path))[0]
    words = [w for w in _WORD_SPLIT.split(stem) if w]
    if not words:
        return stem or "Unknown app"
    return " ".join(w[:1].upper() + w[1:] for w in words)

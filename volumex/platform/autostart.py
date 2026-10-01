"""Start with Windows via HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run (no admin needed)."""
from __future__ import annotations

import sys
import winreg
from pathlib import Path

from volumex import APP_NAME

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = APP_NAME


def default_command(minimized: bool = True) -> str:
    """Command line that launches this install of VolumeX.

    Frozen build: '"<VolumeX.exe>" --minimized'. From source: pythonw.exe (no console
    window) next to the running interpreter with '-m volumex'.
    """
    if getattr(sys, "frozen", False):
        command = f'"{sys.executable}"'
    else:
        python = Path(sys.executable)
        pythonw = python.with_name("pythonw.exe")
        command = f'"{pythonw if pythonw.exists() else python}" -m volumex'
    return f"{command} --minimized" if minimized else command


def registered_command() -> str | None:
    """The command currently in the Run key, or None."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _type = winreg.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return None
    return str(value)


def is_enabled() -> bool:
    return registered_command() is not None


def enable(command: str | None = None) -> None:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command or default_command())


def disable() -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass

"""User settings, stored as versioned JSON in %APPDATA%\\VolumeX\\settings.json."""
from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

from .paths import atomic_write_text, settings_file

log = logging.getLogger(__name__)

SCHEMA = 1

DEFAULT_HOTKEYS = {
    "focused_up": "Ctrl+Alt+Up",
    "focused_down": "Ctrl+Alt+Down",
    "focused_reset": "Ctrl+Alt+0",
    "master_up": "Ctrl+Alt+PgUp",
    "master_down": "Ctrl+Alt+PgDown",
    "toggle_boost": "Ctrl+Alt+B",
}

DEFAULTS: dict[str, Any] = {
    "schema": SCHEMA,
    "max_gain": 3.0,  # 300%; 5.0 once the user unlocks it
    "boost_enabled": True,
    "guard": {"enabled": True, "ceiling_db": -1.0, "release_ms": 80.0},
    "apps": {},  # app key -> {"gain": float, "muted": bool, "name": str, "exe": str}
    "devices": {},  # endpoint id -> {"name": str, "boost": float}
    "rules": [],  # {"id", "trigger", "trigger_name", "target", "target_name", "gain", "enabled"}
    "hotkeys": DEFAULT_HOTKEYS,
    "engine": {"output": None, "target_latency_ms": 25.0},
    "ui": {
        "accent": "aurora",
        "onboarded": False,
        "start_minimized": False,
        "close_to_tray": True,
        "show_osd": True,
        "safety_notice_shown": False,
    },
}


def _merge(defaults: dict[str, Any], stored: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(defaults)
    for key, value in stored.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict) and key not in ("apps", "devices"):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class Settings:
    """Dict-backed settings with atomic saves. Access sections as attributes-free dicts."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings_file()
        self.data: dict[str, Any] = copy.deepcopy(DEFAULTS)

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        settings = cls(path)
        try:
            stored = json.loads(settings.path.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                settings.data = _merge(DEFAULTS, _migrate(stored))
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            log.warning("settings unreadable, using defaults: %s", exc)
            backup = settings.path.with_suffix(".broken.json")
            try:
                settings.path.replace(backup)
            except OSError:
                pass
        return settings

    def save(self) -> None:
        try:
            atomic_write_text(self.path, json.dumps(self.data, indent=2))
        except OSError as exc:
            log.error("could not save settings: %s", exc)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.data[key] = value

    # -- convenience -------------------------------------------------------------------
    def app(self, key: str) -> dict[str, Any] | None:
        return self.data["apps"].get(key)

    def remember_app(self, key: str, name: str, exe: str, gain: float, muted: bool) -> None:
        self.data["apps"][key] = {"gain": round(gain, 4), "muted": muted, "name": name, "exe": exe}

    def forget_app(self, key: str) -> None:
        self.data["apps"].pop(key, None)

    def device_boost(self, endpoint_id: str | None) -> float:
        if not endpoint_id:
            return 1.0
        return float(self.data["devices"].get(endpoint_id, {}).get("boost", 1.0))

    def set_device_boost(self, endpoint_id: str, name: str, boost: float) -> None:
        self.data["devices"][endpoint_id] = {"name": name, "boost": round(boost, 4)}

    def ui(self, key: str) -> Any:
        return self.data["ui"].get(key, DEFAULTS["ui"].get(key))

    def set_ui(self, key: str, value: Any) -> None:
        self.data["ui"][key] = value


def _migrate(stored: dict[str, Any]) -> dict[str, Any]:
    # Only one schema so far; future migrations go here, keyed on stored["schema"].
    stored["schema"] = SCHEMA
    return stored

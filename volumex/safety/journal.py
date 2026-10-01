"""Write-ahead journal of every change VolumeX makes to Windows audio routing.

An entry is written *before* an app is routed to the Boost Bus and removed only
after it has been routed back. If VolumeX or its engine dies, the journal says
exactly what to undo (see safety.restore).
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from volumex.storage.paths import atomic_write_text, journal_file

log = logging.getLogger(__name__)


class Journal:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or journal_file()
        self._lock = threading.Lock()
        self.routes: dict[str, dict[str, Any]] = {}  # app key -> {"exe": str, "restore_volume": float}
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.routes = dict(data.get("routes", {}))
        except FileNotFoundError:
            self.routes = {}
        except (OSError, ValueError) as exc:
            log.warning("journal unreadable (%s); starting empty", exc)
            self.routes = {}

    def reload(self) -> None:
        with self._lock:
            self._load()

    def _flush(self) -> None:
        try:
            atomic_write_text(self.path, json.dumps({"routes": self.routes}, indent=2))
        except OSError as exc:
            log.error("could not write journal: %s", exc)

    def add_route(self, key: str, exe: str, restore_volume: float) -> None:
        with self._lock:
            self.routes[key] = {"exe": exe, "restore_volume": round(min(1.0, max(0.0, restore_volume)), 4)}
            self._flush()

    def update_restore_volume(self, key: str, restore_volume: float) -> None:
        with self._lock:
            if key in self.routes:
                self.routes[key]["restore_volume"] = round(min(1.0, max(0.0, restore_volume)), 4)
                self._flush()

    def remove_route(self, key: str) -> None:
        with self._lock:
            if self.routes.pop(key, None) is not None:
                self._flush()

    def is_empty(self) -> bool:
        return not self.routes

"""Background thread that owns every COM object.

The GUI thread never calls Core Audio directly: it sends action tuples to this
worker and receives snapshots (every ~0.4 s) and peak meters (~30 Hz) back as
queued Qt signals.

Actions:
    ("session_volume", endpoint_id, pid, level)
    ("session_mute", endpoint_id, pid, muted)
    ("endpoint_volume", endpoint_id, level)
    ("endpoint_mute", endpoint_id, muted)
    ("route", pid, endpoint_id | None)
    ("set_default", endpoint_id)
    ("clear_routes",)
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

from PyQt5.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot

from .base import AudioSystem

log = logging.getLogger(__name__)


class AudioWorker(QObject):
    snapshotReady = pyqtSignal(object)  # AudioSnapshot
    peaksReady = pyqtSignal(object)  # PeakMap
    actionFailed = pyqtSignal(object, str)  # action tuple, error text
    fatal = pyqtSignal(str)

    def __init__(
        self,
        factory: Callable[[], AudioSystem],
        init_com: bool = True,
        snapshot_ms: int = 400,
        peaks_ms: int = 33,
    ) -> None:
        super().__init__()
        self._factory = factory
        self._init_com = init_com
        self._snapshot_ms = snapshot_ms
        self._peaks_ms = peaks_ms
        self.audio: AudioSystem | None = None
        self._last_error_log = 0.0

    @pyqtSlot()
    def start(self) -> None:
        if self._init_com:
            import comtypes

            try:
                comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            except OSError:
                pass
        try:
            self.audio = self._factory()
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            log.exception("audio backend failed to start")
            self.fatal.emit(str(exc))
            return
        self._snapshot_timer = QTimer(self)
        self._snapshot_timer.timeout.connect(self.refresh)
        self._snapshot_timer.start(self._snapshot_ms)
        self._peaks_timer = QTimer(self)
        self._peaks_timer.timeout.connect(self._poll_peaks)
        self._peaks_timer.start(self._peaks_ms)
        self.refresh()

    @pyqtSlot()
    def refresh(self) -> None:
        if self.audio is None:
            return
        try:
            self.snapshotReady.emit(self.audio.snapshot())
        except Exception as exc:  # noqa: BLE001 - devices come and go; keep polling
            self._log_error("snapshot failed: %s", exc)

    def _poll_peaks(self) -> None:
        if self.audio is None:
            return
        try:
            self.peaksReady.emit(self.audio.peaks())
        except Exception as exc:  # noqa: BLE001
            self._log_error("peaks failed: %s", exc)

    @pyqtSlot(list)
    def apply(self, actions: list[tuple]) -> None:
        if self.audio is None:
            return
        for action in actions:
            kind = action[0]
            try:
                if kind == "session_volume":
                    self.audio.set_session_volume(action[1], action[2], action[3])
                elif kind == "session_mute":
                    self.audio.set_session_mute(action[1], action[2], action[3])
                elif kind == "endpoint_volume":
                    self.audio.set_endpoint_volume(action[1], action[2])
                elif kind == "endpoint_mute":
                    self.audio.set_endpoint_mute(action[1], action[2])
                elif kind == "route":
                    self.audio.route_app(action[1], action[2])
                elif kind == "set_default":
                    self.audio.set_default_endpoint(action[1])
                elif kind == "clear_routes":
                    self.audio.clear_all_routes()
                else:
                    log.error("unknown action %r", action)
            except Exception as exc:  # noqa: BLE001 - reported per action
                log.warning("action %r failed: %s", action, exc)
                self.actionFailed.emit(action, str(exc))

    @pyqtSlot()
    def stop(self) -> None:
        for timer in (getattr(self, "_snapshot_timer", None), getattr(self, "_peaks_timer", None)):
            if timer:
                timer.stop()
        if self.audio is not None:
            try:
                self.audio.close()
            except Exception:  # noqa: BLE001
                pass
            self.audio = None

    def _log_error(self, msg: str, exc: Exception) -> None:
        now = time.monotonic()
        if now - self._last_error_log > 5.0:
            self._last_error_log = now
            log.warning(msg, exc)

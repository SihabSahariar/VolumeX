"""Installs VB-CABLE in the background so the UI stays responsive (see platform.vbcable)."""
from __future__ import annotations

import ctypes
import logging
import os

from PyQt5.QtCore import QThread, pyqtSignal

from volumex.platform import vbcable

log = logging.getLogger(__name__)


class VbCableInstall(QThread):
    progress = pyqtSignal(str)
    done = pyqtSignal(bool, bool, str)  # ok, cancelled by the user, message

    def __init__(self, silent: bool = True, parent=None) -> None:
        super().__init__(parent)
        self._silent = silent

    def run(self) -> None:
        if os.environ.get("VOLUMEX_DEMO") == "1" or os.environ.get("VOLUMEX_DRY_RUN") == "1":
            self.done.emit(False, False, "Demo and dry-run modes never install anything on this PC.")
            return
        ctypes.windll.ole32.CoInitializeEx(None, 0x2)  # ShellExecuteEx wants an STA thread
        try:
            self.progress.emit("Getting VB-CABLE ready…")
            package = vbcable.find_package(progress=self._on_download)
            setup = package / vbcable.SETUP_EXE
            self.progress.emit("Checking VB-Audio's signature…")
            if not vbcable.verify_signature(setup):
                raise vbcable.VbCableError("The VB-CABLE setup isn't signed by VB-Audio, so VolumeX won't run it.")
            self.progress.emit("Installing - please approve the Windows prompt…")
            result = vbcable.run_elevated(setup, vbcable.INSTALL_ARGS if self._silent else "")
        except vbcable.VbCableError as exc:
            self.done.emit(False, False, str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - reported to the user, never crash the UI
            log.exception("VB-CABLE install failed")
            self.done.emit(False, False, f"Something went wrong: {exc}")
            return
        finally:
            ctypes.windll.ole32.CoUninitialize()
        log.info("VB-CABLE setup finished: %s", result)
        self.done.emit(result.ok, result.cancelled, result.message)

    def _on_download(self, got: int, total: int) -> None:
        if total:
            self.progress.emit(f"Downloading VB-CABLE from vb-audio.com… {got * 100 // total}%")
        else:
            self.progress.emit(f"Downloading VB-CABLE from vb-audio.com… {got // 1024} KB")

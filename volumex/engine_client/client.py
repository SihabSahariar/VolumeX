"""Starts, talks to and supervises the audio engine process (protocol in engine/protocol.py)."""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from PyQt5.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, pyqtSignal

from volumex.engine import protocol

log = logging.getLogger(__name__)
engine_log = logging.getLogger("volumex.engine.child")

RESTART_DELAYS_MS = (500, 2000, 5000)
MAX_CRASHES = 3
CRASH_WINDOW_S = 60.0


def engine_command(fake_io: bool = False) -> tuple[str, list[str]]:
    """Program and arguments that start the engine without a console window."""
    extra = ["--fake-io"] if fake_io else []
    if getattr(sys, "frozen", False):
        engine_exe = Path(sys.executable).with_name("VolumeXEngine.exe")
        if engine_exe.exists():  # console build: its stdio pipes are always real handles
            return str(engine_exe), extra
        return sys.executable, ["--engine", *extra]
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    program = str(pythonw if pythonw.exists() else exe)
    return program, ["-m", "volumex.engine", *extra]


class EngineClient(QObject):
    ready = pyqtSignal(dict)
    stateChanged = pyqtSignal(dict)
    meters = pyqtSignal(dict)
    error = pyqtSignal(str, str)  # code, message
    stopped = pyqtSignal()  # process exited unexpectedly (a restart may follow)
    gaveUp = pyqtSignal(str)  # crashed too often; boost disabled

    def __init__(self, fake_io: bool = False, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fake_io = fake_io
        self._proc: QProcess | None = None
        self._buffer = b""
        self._stderr_buffer = b""
        self._crashes: list[float] = []
        self._shutting_down = False
        self.pid: int | None = None
        self.is_ready = False

    # -- lifecycle -----------------------------------------------------------------------
    def start(self) -> None:
        if self._proc is not None:
            return
        self._shutting_down = False
        self.is_ready = False
        proc = QProcess(self)
        program, args = engine_command(self._fake_io)
        env = QProcessEnvironment.systemEnvironment()
        project_root = str(Path(__file__).resolve().parents[2])
        env.insert("PYTHONPATH", project_root + os.pathsep + env.value("PYTHONPATH", ""))
        env.insert("PYTHONUNBUFFERED", "1")
        for key, value in os.environ.items():
            if key.startswith("VOLUMEX_"):  # demo / dry-run / data-dir flags reach the engine
                env.insert(key, value)
        proc.setProcessEnvironment(env)
        proc.setWorkingDirectory(project_root)
        proc.readyReadStandardOutput.connect(self._read_stdout)
        proc.readyReadStandardError.connect(self._read_stderr)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)
        self._proc = proc
        log.info("starting engine: %s %s", program, " ".join(args))
        proc.start(program, args)

    def shutdown(self, timeout_ms: int = 1500) -> None:
        self._shutting_down = True
        proc = self._proc
        if proc is None:
            return
        self.send({"cmd": "shutdown"})
        if not proc.waitForFinished(timeout_ms):
            proc.kill()
            proc.waitForFinished(500)
        self._proc = None

    def send(self, message: dict[str, Any]) -> None:
        if self._proc is None or self._proc.state() != QProcess.Running:
            return
        self._proc.write(protocol.encode(message))

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.state() == QProcess.Running

    # -- io --------------------------------------------------------------------------
    def _read_stdout(self) -> None:
        if self._proc is None:
            return
        self._buffer += bytes(self._proc.readAllStandardOutput())
        *lines, self._buffer = self._buffer.split(b"\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                message = protocol.decode(line)
            except ValueError:
                engine_log.info("%s", line.decode("utf-8", "replace"))
                continue
            self._dispatch(message)

    def _read_stderr(self) -> None:
        if self._proc is None:
            return
        self._stderr_buffer += bytes(self._proc.readAllStandardError())
        *lines, self._stderr_buffer = self._stderr_buffer.split(b"\n")
        for line in lines:
            text = line.decode("utf-8", "replace").rstrip()
            if text:
                engine_log.info("%s", text)

    def _dispatch(self, message: dict[str, Any]) -> None:
        event = message.get("event")
        if event == "meters":
            self.meters.emit(message)
        elif event == "state":
            self.stateChanged.emit(message)
        elif event == "ready":
            self.pid = int(message.get("pid") or 0) or None
            self.is_ready = True
            self.ready.emit(message)
        elif event == "error":
            self.error.emit(str(message.get("code", "error")), str(message.get("message", "")))
        elif event == "log":
            engine_log.log(logging.getLevelName(str(message.get("level", "INFO")).upper()), "%s", message.get("message"))

    def _on_error(self, err: QProcess.ProcessError) -> None:
        if err == QProcess.FailedToStart:
            log.error("engine failed to start")
            self._proc = None
            self._schedule_restart()

    def _on_finished(self, code: int, status: QProcess.ExitStatus) -> None:
        self._read_stdout()
        self._proc = None
        self.is_ready = False
        self.pid = None
        if self._shutting_down:
            return
        log.warning("engine exited unexpectedly (code %s, status %s)", code, int(status))
        self.stopped.emit()
        self._schedule_restart()

    def _schedule_restart(self) -> None:
        now = time.monotonic()
        self._crashes = [t for t in self._crashes if now - t < CRASH_WINDOW_S] + [now]
        if len(self._crashes) > MAX_CRASHES:
            self.gaveUp.emit("The boost engine stopped several times in a row.")
            return
        delay = RESTART_DELAYS_MS[min(len(self._crashes), len(RESTART_DELAYS_MS)) - 1]
        QTimer.singleShot(delay, self._restart_if_needed)

    def _restart_if_needed(self) -> None:
        if not self._shutting_down and self._proc is None:
            self.start()

    def reset_crash_budget(self) -> None:
        self._crashes.clear()

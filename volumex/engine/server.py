"""Protocol loop of the engine process (see volumex.engine.protocol for the wire format).

A reader thread turns stdin lines into queue items; the main thread handles one
item at a time (commands, stream errors reported by the bridge, EOF) and sends
meters at ~30 Hz while streaming. Events are written to the protocol output under
a lock and flushed per line, so any thread may emit.
"""
from __future__ import annotations

import logging
import math
import os
import queue
import threading
import time
from typing import Any, BinaryIO

from volumex.engine.audio_io import Bridge, DeviceNotFoundError
from volumex.engine.dsp import LimiterSettings
from volumex.engine.protocol import PROTOCOL_VERSION, decode, encode

log = logging.getLogger(__name__)

DEFAULT_RAMP_MS = 30.0
MAX_GAIN = 100.0  # +40 dB; sanity bound only, the controller keeps G far lower

_EOF = object()


class BadCommand(Exception):
    pass


def _number(msg: dict[str, Any], key: str, default: float, lo: float, hi: float) -> float:
    value = msg.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BadCommand(f"{key!r} must be a finite number")
    if not lo <= value <= hi:
        raise BadCommand(f"{key!r} must be between {lo} and {hi}")
    return float(value)


def _limiter_settings(msg: dict[str, Any], current: LimiterSettings) -> LimiterSettings:
    enabled = msg.get("enabled", current.enabled)
    if not isinstance(enabled, bool):
        raise BadCommand("'enabled' must be a boolean")
    return LimiterSettings(
        enabled=enabled,
        ceiling_db=_number(msg, "ceiling_db", current.ceiling_db, -60.0, 0.0),
        release_ms=_number(msg, "release_ms", current.release_ms, 1.0, 5000.0),
        lookahead_ms=_number(msg, "lookahead_ms", current.lookahead_ms, 0.0, 20.0),
    )


class EngineServer:
    def __init__(self, bridge: Bridge, inp: BinaryIO, out: BinaryIO, meter_hz: float = 30.0) -> None:
        self.bridge = bridge
        self._inp = inp
        self._out = out
        self._out_lock = threading.Lock()
        self._queue: queue.Queue[Any] = queue.Queue()
        self._meter_period = 1.0 / meter_hz
        self._next_meter = 0.0
        bridge.on_error = self._on_bridge_error
        self._handlers = {
            "configure": self._configure,
            "start": self._start,
            "stop": self._stop,
            "set_gain": self._set_gain,
            "set_limiter": self._set_limiter,
            "ping": lambda msg: self.emit("pong"),
        }

    def emit(self, event: str, **fields: Any) -> None:
        data = encode({"event": event, **fields})
        with self._out_lock:
            try:
                self._out.write(data)
                self._out.flush()
            except (OSError, ValueError):
                pass  # controller gone; stdin EOF will follow

    def run(self) -> int:
        """Serve until `shutdown` or stdin EOF; returns the process exit code."""
        self.emit("ready", version=PROTOCOL_VERSION, pid=os.getpid())
        threading.Thread(target=self._read_loop, name="stdin-reader", daemon=True).start()
        while True:
            timeout = None
            if self.bridge.streaming:
                timeout = self._next_meter - time.monotonic()
                if timeout <= 0:  # checked first, so a flood of commands can't starve the meters
                    self._tick()
                    continue
            try:
                item = self._queue.get(timeout=timeout)
            except queue.Empty:
                continue
            if item is _EOF:
                self._on_eof()
                return 0
            if isinstance(item, tuple):  # (code, message) from the bridge
                self._on_stream_failure(*item)
            elif self._handle_line(item):
                self.bridge.stop()
                log.info("shutdown requested")
                return 0

    # -- threads -----------------------------------------------------------------------------

    def _read_loop(self) -> None:
        try:
            while True:
                line = self._inp.readline()
                if not line:
                    break
                if line.strip():
                    self._queue.put(line)
        except (OSError, ValueError):
            log.exception("reading stdin failed")
        self._queue.put(_EOF)

    def _on_bridge_error(self, code: str, message: str) -> None:
        self._queue.put((code, message))  # audio threads never touch the bridge themselves

    # -- main thread -------------------------------------------------------------------------

    def _tick(self) -> None:
        self.bridge.poll()
        if self.bridge.streaming:
            self.emit("meters", **self.bridge.meters())
        now = time.monotonic()
        self._next_meter += self._meter_period
        if self._next_meter < now:  # fell behind: don't send a burst
            self._next_meter = now + self._meter_period

    def _handle_line(self, line: bytes) -> bool:
        """Handle one command line; True means shut down."""
        try:
            msg = decode(line)
            cmd = msg.get("cmd")
            if cmd == "shutdown":
                return True
            handler = self._handlers.get(cmd) if isinstance(cmd, str) else None
            if handler is None:
                raise BadCommand(f"unknown command {cmd!r}")
            handler(msg)
        except BadCommand as exc:
            self.emit("error", code="bad_command", message=str(exc))
        except ValueError as exc:  # JSON syntax (json.JSONDecodeError) or not an object
            self.emit("error", code="bad_command", message=f"invalid message: {exc}")
        except Exception as exc:
            log.exception("command failed: %r", line)
            self.emit("error", code="bad_command", message=f"command failed: {exc}")
        return False

    def _open_streams(self, action: Any) -> None:
        """Run bridge.start/reconfigure, turning failures into error events."""
        try:
            action()
        except DeviceNotFoundError as exc:
            self.emit("error", code="device_not_found", message=str(exc))
        except Exception as exc:
            log.exception("opening streams failed")
            self.emit("error", code="stream_failed", message=str(exc))
        self._next_meter = time.monotonic() + self._meter_period

    def _configure(self, msg: dict[str, Any]) -> None:
        b = self.bridge
        capture = msg.get("capture", b.capture)
        output = msg.get("output", b.output)
        if not isinstance(capture, str) or not isinstance(output, str):
            raise BadCommand("'capture' and 'output' must be strings")
        gain = _number(msg, "gain", b.gain, 0.0, MAX_GAIN)
        limiter = msg.get("limiter", {})
        if not isinstance(limiter, dict):
            raise BadCommand("'limiter' must be an object")
        settings = _limiter_settings(limiter, b.limiter)
        target = _number(msg, "target_latency_ms", b.target_latency_ms, 1.0, 500.0)

        b.set_gain(gain, DEFAULT_RAMP_MS if b.streaming else 0.0)
        b.set_limiter(settings)
        if (capture, output, target) != (b.capture, b.output, b.target_latency_ms):
            if b.streaming:
                log.info("devices changed while streaming: re-opening streams")
                self._open_streams(lambda: b.reconfigure(capture, output, target))
            else:
                b.configure(capture, output, target)
        self.emit("state", **b.state())

    def _start(self, msg: dict[str, Any]) -> None:
        if not self.bridge.capture or not self.bridge.output:
            raise BadCommand("send 'configure' with capture and output devices before 'start'")
        if not self.bridge.streaming:
            self._open_streams(self.bridge.start)
        self.emit("state", **self.bridge.state())

    def _stop(self, msg: dict[str, Any]) -> None:
        self.bridge.stop()
        self.emit("state", **self.bridge.state())

    def _set_gain(self, msg: dict[str, Any]) -> None:
        gain = _number(msg, "gain", math.nan, 0.0, MAX_GAIN)
        ramp_ms = _number(msg, "ramp_ms", DEFAULT_RAMP_MS, 0.0, 10000.0)
        self.bridge.set_gain(gain, ramp_ms)

    def _set_limiter(self, msg: dict[str, Any]) -> None:
        self.bridge.set_limiter(_limiter_settings(msg, self.bridge.limiter))

    def _on_stream_failure(self, code: str, message: str) -> None:
        if not self.bridge.streaming:
            return  # already stopped; stale report
        log.error("stream failure: %s", message)
        self.bridge.stop()
        self.emit("error", code=code, message=message)
        self.emit("state", **self.bridge.state())

    def _on_eof(self) -> None:
        log.info("stdin closed (controller gone): restoring audio routing and exiting")
        try:
            from volumex.safety.restore import restore_after_controller_exit

            restore_after_controller_exit()
        except ImportError:
            log.warning("volumex.safety.restore is not available; nothing restored")
        except Exception:
            log.exception("restore after controller exit failed")
        self.bridge.stop()


class EventLogHandler(logging.Handler):
    """Forwards log records to the controller as `log` events."""

    def __init__(self, server: EngineServer, level: int = logging.WARNING) -> None:
        super().__init__(level)
        self._server = server

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._server.emit("log", level=record.levelname.lower(), message=record.getMessage())
        except Exception:
            self.handleError(record)

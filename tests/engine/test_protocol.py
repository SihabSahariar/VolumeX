"""The engine's stdin/stdout protocol, against `python -m volumex.engine --fake-io`."""
from __future__ import annotations

import io
import json
import queue
import subprocess
import sys
import threading
import time
import types
from pathlib import Path
from typing import Any

import psutil
import pytest

from volumex.engine.audio_io import DeviceNotFoundError, FakeBridge
from volumex.engine.protocol import PROTOCOL_VERSION, encode
from volumex.engine.server import EngineServer

ROOT = Path(__file__).resolve().parents[2]
TIMEOUT = 10.0

CONFIGURE = {
    "cmd": "configure",
    "capture": "CABLE Output (VB-Audio Virtual Cable)",
    "output": "Speakers (Realtek(R) Audio)",
    "gain": 2.0,
    "limiter": {"enabled": True, "ceiling_db": -1.0, "release_ms": 80.0, "lookahead_ms": 3.0},
    "target_latency_ms": 10.0,
}


# Runs the same entry point as `-m volumex.engine`, with volumex.safety.restore stubbed out,
# so an EOF test never touches the real audio routing of this machine.
STUB_RESTORE_BOOTSTRAP = """
import sys, types
stub = types.ModuleType("volumex.safety.restore")
stub.restore_after_controller_exit = lambda: print("STUB RESTORE CALLED", file=sys.stderr, flush=True)
sys.modules["volumex.safety.restore"] = stub
from volumex.engine.__main__ import main
sys.exit(main(["--fake-io"]))
"""


class EngineProcess:
    def __init__(self, stub_restore: bool = False) -> None:
        args = ["-c", STUB_RESTORE_BOOTSTRAP] if stub_restore else ["-m", "volumex.engine", "--fake-io"]
        self.proc = subprocess.Popen(
            [sys.executable, *args],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self.stderr: list[str] = []
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self) -> None:
        for line in self.proc.stdout:
            self.events.put(json.loads(line))  # every stdout line must be protocol JSON

    def _read_stderr(self) -> None:
        for line in self.proc.stderr:
            self.stderr.append(line.decode("utf-8", "replace"))

    def send(self, message: dict[str, Any] | bytes) -> None:
        self.proc.stdin.write(message if isinstance(message, bytes) else encode(message))
        self.proc.stdin.flush()

    def expect(self, event: str, timeout: float = TIMEOUT) -> dict[str, Any]:
        """Next event of this type; meters arriving in between are skipped."""
        deadline = time.monotonic() + timeout
        while True:
            msg = self.events.get(timeout=max(0.0, deadline - time.monotonic()))
            if msg["event"] == event:
                return msg
            assert msg["event"] == "meters", f"unexpected event while waiting for {event}: {msg}"

    def drain(self, seconds: float) -> list[dict[str, Any]]:
        out, deadline = [], time.monotonic() + seconds
        while (left := deadline - time.monotonic()) > 0:
            try:
                out.append(self.events.get(timeout=left))
            except queue.Empty:
                break
        return out

    def kill(self) -> None:
        if self.proc.poll() is None:
            try:  # the real engine may be a child of the venv redirector
                for child in psutil.Process(self.proc.pid).children(recursive=True):
                    child.kill()
            except psutil.NoSuchProcess:
                pass
            self.proc.kill()
            self.proc.wait()


@pytest.fixture
def engine():
    e = EngineProcess()
    yield e
    e.kill()


def test_full_session(engine):
    ready = engine.expect("ready")
    assert set(ready) == {"event", "version", "pid"} and ready["version"] == PROTOCOL_VERSION
    # A venv python.exe on Windows is a redirector that runs the real interpreter as a child.
    engine_pids = {engine.proc.pid} | {c.pid for c in psutil.Process(engine.proc.pid).children()}
    assert ready["pid"] in engine_pids

    engine.send(CONFIGURE)
    state = engine.expect("state")
    assert state["streaming"] is False
    assert state["capture"] == CONFIGURE["capture"] and state["output"] == CONFIGURE["output"]
    assert set(state) == {"event", "streaming", "capture", "output", "in_rate", "out_rate", "latency_ms"}

    engine.send({"cmd": "start"})
    state = engine.expect("state")
    assert state["streaming"] is True
    assert state["in_rate"] == 48000 and state["out_rate"] == 48000
    assert 10.0 < state["latency_ms"] < 60.0

    events = engine.drain(1.0)
    meters = [e for e in events if e["event"] == "meters"]
    assert len(events) == len(meters)
    assert 15 <= len(meters) <= 45  # ~30 Hz
    m = meters[-1]
    assert set(m) == {"event", "peak", "gr_db", "underruns", "overruns"}
    assert m["peak"][0] == pytest.approx(0.5, abs=0.01)  # 0.25 test tone x gain 2
    assert m["gr_db"] == 0.0 and m["underruns"] == 0 and m["overruns"] == 0

    engine.send({"cmd": "set_gain", "gain": 5.0, "ramp_ms": 30.0})
    engine.drain(0.3)
    m = engine.expect("meters")
    assert m["peak"][0] == pytest.approx(10 ** (-1 / 20), abs=1e-4)  # held at the -1 dB ceiling
    assert m["gr_db"] > 2.5

    engine.send({"cmd": "set_limiter", "enabled": True, "ceiling_db": -6.0, "release_ms": 50.0})
    engine.drain(0.3)
    assert engine.expect("meters")["peak"][0] <= 10 ** (-6 / 20) + 1e-4

    engine.send({"cmd": "ping"})
    assert engine.expect("pong") == {"event": "pong"}

    engine.send({"cmd": "stop"})
    assert engine.expect("state")["streaming"] is False
    assert engine.drain(0.3) == []  # no meters while stopped

    engine.send({"cmd": "shutdown"})
    assert engine.proc.wait(timeout=TIMEOUT) == 0
    assert not any("Traceback" in line for line in engine.stderr)


def test_bad_commands_are_reported(engine):
    engine.expect("ready")
    bad = [
        b"not json\n",
        b"[1, 2]\n",
        encode({"cmd": "fly"}),
        encode({"nocmd": 1}),
        encode({"cmd": "set_gain", "gain": -1.0, "ramp_ms": 30}),
        encode({"cmd": "set_gain", "ramp_ms": 30}),
        encode({"cmd": "set_limiter", "enabled": "yes"}),
        encode({"cmd": "start"}),  # before configure
        encode({**CONFIGURE, "gain": "loud"}),
    ]
    for line in bad:
        engine.send(line)
        err = engine.expect("error")
        assert err["code"] == "bad_command" and err["message"]
    engine.send({"cmd": "ping"})
    engine.expect("pong")  # still alive
    engine.send({"cmd": "shutdown"})
    assert engine.proc.wait(timeout=TIMEOUT) == 0


def test_reconfigure_while_streaming(engine):
    engine.expect("ready")
    engine.send(CONFIGURE)
    engine.expect("state")
    engine.send({"cmd": "start"})
    assert engine.expect("state")["streaming"] is True
    engine.send({**CONFIGURE, "output": "Headphones"})
    state = engine.expect("state")
    assert state["streaming"] is True and state["output"] == "Headphones"
    assert engine.expect("meters")["event"] == "meters"
    engine.send({"cmd": "shutdown"})
    assert engine.proc.wait(timeout=TIMEOUT) == 0


def test_stdin_eof_restores_and_exits():
    engine = EngineProcess(stub_restore=True)
    try:
        _eof_session(engine)
    finally:
        engine.kill()


def _eof_session(engine: EngineProcess) -> None:
    engine.expect("ready")
    engine.send(CONFIGURE)
    engine.send({"cmd": "start"})
    engine.expect("state")
    assert engine.expect("state")["streaming"] is True
    engine.proc.stdin.close()  # controller died
    assert engine.proc.wait(timeout=TIMEOUT) == 0
    time.sleep(0.1)  # let the stderr reader catch up
    assert any("stdin closed" in line for line in engine.stderr)
    assert any("STUB RESTORE CALLED" in line for line in engine.stderr)


# -- in-process server (restore hook, device errors) ---------------------------------------


def run_server(commands: list[dict[str, Any]], bridge: FakeBridge | None = None) -> tuple[int, list[dict[str, Any]]]:
    out = io.BytesIO()
    inp = io.BytesIO(b"".join(encode(c) for c in commands))
    code = EngineServer(bridge or FakeBridge(), inp, out).run()
    return code, [json.loads(line) for line in out.getvalue().splitlines()]


@pytest.fixture(autouse=True)
def restore_calls(monkeypatch):
    """Never run the real restore from in-process tests; record calls instead."""
    calls: list[int] = []
    module = types.ModuleType("volumex.safety.restore")
    module.restore_after_controller_exit = lambda: calls.append(1)
    monkeypatch.setitem(sys.modules, "volumex.safety.restore", module)
    return calls


def test_eof_restores_routing_and_stops(restore_calls):
    bridge = FakeBridge()
    code, events = run_server([CONFIGURE, {"cmd": "start"}], bridge)
    assert code == 0
    assert restore_calls == [1]
    assert not bridge.streaming
    assert [e["event"] for e in events if e["event"] != "meters"] == ["ready", "state", "state"]


def test_shutdown_does_not_restore(restore_calls):
    code, events = run_server([{"cmd": "ping"}, {"cmd": "shutdown"}, {"cmd": "ping"}])
    assert code == 0
    assert restore_calls == []
    assert [e["event"] for e in events] == ["ready", "pong"]  # nothing after shutdown


def test_eof_survives_failing_restore(monkeypatch):
    module = types.ModuleType("volumex.safety.restore")

    def boom() -> None:
        raise RuntimeError("restore failed")

    module.restore_after_controller_exit = boom
    monkeypatch.setitem(sys.modules, "volumex.safety.restore", module)
    assert run_server([])[0] == 0


class MissingDeviceBridge(FakeBridge):
    def _open(self) -> None:
        raise DeviceNotFoundError(f"no WASAPI input device named {self.capture!r}")


def test_start_reports_device_not_found():
    code, events = run_server([CONFIGURE, {"cmd": "start"}], MissingDeviceBridge())
    error = next(e for e in events if e["event"] == "error")
    assert error["code"] == "device_not_found" and "CABLE Output" in error["message"]
    assert events[-1] == {**events[-1], "event": "state", "streaming": False}


def test_stream_failure_is_reported_and_stops():
    bridge = FakeBridge()
    server = EngineServer(bridge, io.BytesIO(), io.BytesIO())
    bridge.configure("a", "b")
    bridge.start()
    bridge._report_error("stream_failed", "device unplugged")
    bridge._report_error("stream_failed", "again")  # reported once per session
    code = server.run()  # handles the queued failure, then stdin EOF
    events = [json.loads(line) for line in server._out.getvalue().splitlines()]
    assert code == 0
    assert [e for e in events if e["event"] == "error"] == [
        {"event": "error", "code": "stream_failed", "message": "device unplugged"}
    ]
    assert not bridge.streaming

"""The real engine process (--fake-io) driven by EngineClient and by the Controller."""
from __future__ import annotations

import pytest

from volumex.core import controller as controller_mod
from volumex.core.controller import Controller
from volumex.engine_client.client import EngineClient
from volumex.platform.fake import FakeAudioSystem
from volumex.safety.journal import Journal
from volumex.storage.settings import Settings


@pytest.fixture(autouse=True)
def demo_env(monkeypatch, tmp_path):
    # the engine child restores via the journal on EOF; keep it away from the real one
    monkeypatch.setenv("VOLUMEX_DEMO", "1")
    monkeypatch.setenv("VOLUMEX_DATA_DIR", str(tmp_path))


def test_engine_client_round_trip(qtbot):
    client = EngineClient(fake_io=True)
    events: dict[str, list] = {"state": [], "meters": []}
    client.stateChanged.connect(events["state"].append)
    client.meters.connect(events["meters"].append)
    with qtbot.waitSignal(client.ready, timeout=15000):
        client.start()
    assert client.pid

    client.send({"cmd": "configure", "capture": "CABLE Output", "output": "Speakers", "gain": 2.0,
                 "limiter": {"enabled": True, "ceiling_db": -1.0, "release_ms": 80.0, "lookahead_ms": 3.0},
                 "target_latency_ms": 20.0})
    client.send({"cmd": "start"})
    qtbot.waitUntil(lambda: any(s.get("streaming") for s in events["state"]), timeout=5000)
    qtbot.waitUntil(lambda: len(events["meters"]) >= 3, timeout=5000)
    peak = events["meters"][-1]["peak"]
    assert max(peak) <= 10 ** (-1.0 / 20) + 1e-6  # the guard holds the ceiling

    client.shutdown()
    assert not client.running


def test_controller_with_real_engine_boosts_an_app(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(controller_mod, "LEAVE_DELAY_S", 0.3)
    audio = FakeAudioSystem()
    ctrl = Controller(Settings(tmp_path / "s.json"), Journal(tmp_path / "j.json"), lambda: audio,
                      real_windows=False, engine_fake_io=True)
    ctrl.start()
    try:
        qtbot.waitUntil(lambda: ctrl.bus_present and ctrl.engine.is_ready, timeout=15000)
        chrome = next(v.key for v in ctrl.app_views() if v.name == "Google Chrome")
        ctrl.set_app_gain(chrome, 2.5)
        qtbot.waitUntil(lambda: ctrl.engine_streaming, timeout=5000)
        qtbot.waitUntil(lambda: audio.routes.get(4120) == "fake-bus", timeout=5000)
        qtbot.waitUntil(lambda: ctrl.engine_gain_sent == pytest.approx(2.5), timeout=3000)
        qtbot.waitUntil(lambda: next(v for v in ctrl.app_views() if v.key == chrome).status == "boosted",
                        timeout=3000)
    finally:
        ctrl.shutdown()
    assert not ctrl.engine.running

"""Controller end to end: worker thread + FakeAudioSystem + a stand-in engine."""
from __future__ import annotations

import pytest
from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from volumex.core import controller as controller_mod
from volumex.core.controller import Controller
from volumex.platform.fake import FakeAudioSystem
from volumex.safety.journal import Journal
from volumex.storage.settings import Settings


class FakeEngine(QObject):
    ready = pyqtSignal(dict)
    stateChanged = pyqtSignal(dict)
    meters = pyqtSignal(dict)
    error = pyqtSignal(str, str)
    stopped = pyqtSignal()
    gaveUp = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[dict] = []
        self.is_ready = False
        self.pid = None
        self.gain = 1.0

    def start(self) -> None:
        self.is_ready = True
        QTimer.singleShot(0, lambda: self.ready.emit({"event": "ready", "pid": 0}))

    def shutdown(self, timeout_ms: int = 0) -> None:
        self.is_ready = False

    def reset_crash_budget(self) -> None:
        pass

    def send(self, message: dict) -> None:
        self.sent.append(message)
        if message["cmd"] == "start":
            QTimer.singleShot(0, lambda: self.stateChanged.emit({"streaming": True, "output": "Speakers", "latency_ms": 30}))
        elif message["cmd"] == "stop":
            QTimer.singleShot(0, lambda: self.stateChanged.emit({"streaming": False}))
        elif message["cmd"] == "set_gain":
            self.gain = message["gain"]


@pytest.fixture
def rig(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(controller_mod, "LEAVE_DELAY_S", 0.3)
    monkeypatch.setattr(controller_mod, "STALL_AFTER_S", 0.3)
    audio = FakeAudioSystem()
    engine = FakeEngine()
    ctrl = Controller(
        Settings(tmp_path / "settings.json"),
        Journal(tmp_path / "journal.json"),
        lambda: audio,
        real_windows=False,
        engine=engine,
    )
    ctrl.start()
    qtbot.waitUntil(lambda: len(ctrl.app_views()) >= 5, timeout=3000)
    yield ctrl, audio, engine
    ctrl.shutdown()


def key_of(ctrl: Controller, name: str) -> str:
    return next(v.key for v in ctrl.app_views() if v.name == name)


def session_state(audio: FakeAudioSystem, endpoint: str, pid: int) -> dict | None:
    return audio._sessions.get((endpoint, pid))


def test_startup_changes_nothing(rig):
    ctrl, audio, engine = rig
    assert not any(w[0] == "route" for w in audio.writes)
    assert {v.name for v in ctrl.app_views()} >= {"Google Chrome", "Spotify", "Discord"}
    spotify = next(v for v in ctrl.app_views() if v.name == "Spotify")
    assert spotify.gain == pytest.approx(0.6)  # adopted from Windows


def test_boosting_an_app_routes_it_and_sets_engine_gain(qtbot, rig):
    ctrl, audio, engine = rig
    chrome = key_of(ctrl, "Google Chrome")
    ctrl.set_app_gain(chrome, 2.0)

    qtbot.waitUntil(lambda: audio.routes.get(4120) == "fake-bus", timeout=3000)
    qtbot.waitUntil(lambda: engine.gain == pytest.approx(2.0), timeout=3000)
    qtbot.waitUntil(lambda: next(v for v in ctrl.app_views() if v.key == chrome).status == "boosted", timeout=3000)
    assert session_state(audio, "fake-bus", 4120)["volume"] == pytest.approx(1.0)
    assert any(m["cmd"] == "start" for m in engine.sent)


def test_two_boosted_apps_share_the_bus_with_ratio(qtbot, rig):
    ctrl, audio, engine = rig
    ctrl.set_app_gain(key_of(ctrl, "Google Chrome"), 3.0)
    ctrl.set_app_gain(key_of(ctrl, "Discord"), 1.5)
    qtbot.waitUntil(lambda: engine.gain == pytest.approx(3.0), timeout=3000)
    qtbot.waitUntil(lambda: (session_state(audio, "fake-bus", 6632) or {}).get("volume") == pytest.approx(0.5), timeout=3000)
    assert session_state(audio, "fake-bus", 4120)["volume"] == pytest.approx(1.0)


def test_newcomer_on_the_bus_is_never_louder_than_wanted(qtbot, rig):
    """A first-time join lands on the bus at an unknown volume (the fake uses 100%). With another app
    already boosted to 300%, the engine must be brought down first so the newcomer can't spike."""
    ctrl, audio, engine = rig
    ctrl.set_app_gain(key_of(ctrl, "Google Chrome"), 3.0)
    qtbot.waitUntil(lambda: engine.gain == pytest.approx(3.0), timeout=3000)
    qtbot.wait(300)

    ctrl.set_app_gain(key_of(ctrl, "Discord"), 1.35)
    loudest = 0.0
    for _ in range(150):  # 1.5 s of samples through the whole transition
        qtbot.wait(10)
        bus = audio._sessions.get(("fake-bus", 6632))
        if bus and bus["active"]:
            loudest = max(loudest, bus["volume"] * engine.gain)
    assert audio.routes.get(6632) == "fake-bus"
    assert loudest == pytest.approx(1.35, abs=0.02)  # reached, never exceeded
    qtbot.waitUntil(lambda: engine.gain == pytest.approx(3.0), timeout=3000)  # Chrome back at full boost


def test_app_that_ignores_routing_is_flagged(qtbot, rig):
    ctrl, audio, engine = rig
    spotify = key_of(ctrl, "Spotify")
    ctrl.set_app_gain(spotify, 1.5)
    qtbot.waitUntil(lambda: next(v for v in ctrl.app_views() if v.key == spotify).status == "needs_restart", timeout=4000)
    # plays directly at the most it can: 100%
    qtbot.waitUntil(lambda: session_state(audio, "fake-speakers", 5304)["volume"] == pytest.approx(1.0), timeout=3000)


def test_dropping_below_100_routes_back_after_delay(qtbot, rig):
    ctrl, audio, engine = rig
    chrome = key_of(ctrl, "Google Chrome")
    ctrl.set_app_gain(chrome, 2.0)
    qtbot.waitUntil(lambda: audio.routes.get(4120) == "fake-bus", timeout=3000)
    ctrl.set_app_gain(chrome, 0.8)
    qtbot.waitUntil(lambda: audio.routes.get(4120) is None, timeout=4000)
    qtbot.waitUntil(lambda: session_state(audio, "fake-speakers", 4120)["volume"] == pytest.approx(0.8), timeout=3000)
    assert ctrl.journal.is_empty()


def test_master_boost_routes_every_loud_app(qtbot, rig):
    ctrl, audio, engine = rig
    ctrl.set_master(1.5)
    qtbot.waitUntil(lambda: audio.endpoint_volume["fake-speakers"] == pytest.approx(1.0), timeout=3000)
    qtbot.waitUntil(lambda: audio.routes.get(4120) == "fake-bus" and audio.routes.get(6632) == "fake-bus", timeout=3000)
    # Spotify at 60% x 1.5 = 90%: stays direct
    assert 5304 not in audio.routes


def test_paused_boost_keeps_everything_direct(qtbot, rig):
    ctrl, audio, engine = rig
    ctrl.set_boost_enabled(False)
    chrome = key_of(ctrl, "Google Chrome")
    ctrl.set_app_gain(chrome, 2.5)
    qtbot.wait(600)
    assert 4120 not in audio.routes
    assert next(v for v in ctrl.app_views() if v.key == chrome).status == "paused"


def test_default_device_stuck_on_the_cable_can_be_fixed(qtbot, rig):
    ctrl, audio, engine = rig
    audio.set_default("fake-bus")
    qtbot.waitUntil(lambda: ctrl.master_view().default_is_bus, timeout=3000)
    ctrl.fix_default_device()
    qtbot.waitUntil(lambda: audio.default_id == "fake-speakers", timeout=3000)
    qtbot.waitUntil(lambda: not ctrl.master_view().default_is_bus, timeout=3000)


def test_windows_mixer_change_is_adopted(qtbot, rig):
    ctrl, audio, engine = rig
    discord = key_of(ctrl, "Discord")
    qtbot.wait(1200)  # past the grace period for our own writes
    audio._sessions[("fake-speakers", 6632)]["volume"] = 0.3
    qtbot.waitUntil(lambda: next(v for v in ctrl.app_views() if v.key == discord).gain == pytest.approx(0.3), timeout=3000)

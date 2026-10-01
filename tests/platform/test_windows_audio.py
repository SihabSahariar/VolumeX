"""WindowsAudioSystem: a read-only snapshot of the real system, plus logic tests on fakes.

Nothing here changes audio state: the real system is only used with dry_run=True and
Get* calls; every mutating test runs against fake COM objects.
"""
from __future__ import annotations

import gc
import logging
import threading

import comtypes
import pytest
from comtypes import COMError

from volumex.core.bus import is_bus_render_name
from volumex.core.models import SYSTEM_SOUNDS_KEY, AudioSnapshot, Endpoint, SessionInfo
from volumex.platform.windows_audio import WindowsAudioSystem, _Session

EP = "{0.0.0.00000000}.{11111111-2222-3333-4444-555555555555}"


def run_in_mta(fn):
    """Run fn on a fresh MTA thread, like the production audio worker."""
    result: dict = {}

    def target() -> None:
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        try:
            result["value"] = fn()
        except BaseException as exc:  # re-raised on the test thread
            result["error"] = exc
        finally:
            gc.collect()
            comtypes.CoUninitialize()

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(60)
    if "error" in result:
        raise result["error"]
    return result["value"]


def test_dry_run_snapshot_is_well_formed():
    def work():
        audio = WindowsAudioSystem(dry_run=True)
        try:
            return audio.snapshot(), audio.peaks()
        finally:
            audio.close()

    snap, peaks = run_in_mta(work)

    assert isinstance(snap, AudioSnapshot)
    ids = [ep.id for ep in snap.endpoints]
    assert len(ids) == len(set(ids))
    for ep in snap.endpoints:
        assert isinstance(ep, Endpoint)
        assert ep.id and ep.name
        assert ep.is_bus == is_bus_render_name(ep.name)
        assert ep.is_default == (ep.id == snap.default_endpoint_id)
    if snap.default_endpoint_id is not None:
        assert snap.default_endpoint_id in ids
    assert 0.0 <= snap.endpoint_volume <= 1.0
    assert isinstance(snap.endpoint_muted, bool)

    keys = [(s.endpoint_id, s.pid) for s in snap.sessions]
    assert len(keys) == len(set(keys))
    for s in snap.sessions:
        assert isinstance(s, SessionInfo)
        assert s.endpoint_id in ids
        assert 0.0 <= s.volume <= 1.0
        assert isinstance(s.muted, bool) and isinstance(s.active, bool)
        assert s.key and s.name
        if s.pid == 0:
            assert s.key == SYSTEM_SOUNDS_KEY and s.exe_path == "" and s.name == "System sounds"
        else:
            assert s.exe_path and s.key != SYSTEM_SOUNDS_KEY

    assert set(peaks) <= set(keys)
    assert all(0.0 <= level <= 1.0 for level in peaks.values())


# ---- fakes ----------------------------------------------------------------------


class Untouchable:
    """Fails the test on any attribute access: proves dry-run touched nothing."""

    def __getattr__(self, name):
        raise AssertionError(f"dry-run touched {name}")


class FakeVolume:
    def __init__(self, fail: bool = False) -> None:
        self.level: float | None = None
        self.muted: bool | None = None
        self.fail = fail

    def SetMasterVolume(self, level, _ctx):
        if self.fail:
            raise COMError(-2004287484, "AUDCLNT_E_DEVICE_INVALIDATED", None)
        self.level = level

    def SetMute(self, muted, _ctx):
        self.muted = muted


class FakeMeter:
    def __init__(self, peak: float | None) -> None:
        self.peak = peak

    def GetPeakValue(self):
        if self.peak is None:
            raise COMError(-2004287484, "AUDCLNT_E_DEVICE_INVALIDATED", None)
        return self.peak


class FakePolicy:
    def __init__(self, available: bool = True, route: str | None = None) -> None:
        self.available = available
        self.route = route
        self.calls: list = []

    def get_app_endpoint(self, pid):
        return self.route

    def set_app_endpoint(self, pid, endpoint_id):
        self.calls.append(("set", pid, endpoint_id))

    def clear_all(self):
        self.calls.append(("clear",))

    def close(self):
        pass


def fake_system(dry_run: bool, sessions=None, policy=None) -> WindowsAudioSystem:
    """A WindowsAudioSystem wired to fakes only (no COM at all)."""
    audio = object.__new__(WindowsAudioSystem)
    audio.dry_run = dry_run
    audio._enumerator = Untouchable()
    audio._policy = policy if policy is not None else Untouchable()
    audio._sessions = sessions if sessions is not None else {}
    audio._endpoint_volumes = {}
    audio._exe_cache = {}
    audio._endpoint_ids = (EP,)
    return audio


def test_dry_run_mutators_only_log(caplog):
    audio = fake_system(dry_run=True, sessions={(EP, 42): [_Session(Untouchable(), None)]})
    audio._endpoint_volumes = {EP: Untouchable()}
    with caplog.at_level(logging.INFO, logger="volumex.platform.windows_audio"):
        audio.set_session_volume(EP, 42, 1.7)
        audio.set_session_mute(EP, 42, True)
        audio.set_endpoint_volume(EP, -0.5)
        audio.set_endpoint_mute(EP, True)
        audio.route_app(42, EP)
        audio.route_app(42, None)
        audio.clear_all_routes()
    lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert len(lines) == 7 and all(line.startswith("DRY-RUN ") for line in lines)
    assert "1.0" in lines[0] and "0.0" in lines[2]  # clamped before logging


def test_set_session_volume_clamps_and_applies_to_every_session():
    a, b = FakeVolume(), FakeVolume()
    audio = fake_system(dry_run=False, sessions={(EP, 42): [_Session(a, None), _Session(b, None)]})
    audio.set_session_volume(EP, 42, 1.5)
    assert a.level == b.level == 1.0
    audio.set_session_volume(EP, 42, -3)
    assert a.level == b.level == 0.0
    audio.set_session_mute(EP, 42, True)
    assert a.muted is b.muted is True
    audio.set_session_volume(EP, 7, 0.5)  # unknown session: no-op, no error


def test_failing_session_is_dropped_but_siblings_still_set():
    good, bad = FakeVolume(), FakeVolume(fail=True)
    audio = fake_system(dry_run=False, sessions={(EP, 42): [_Session(bad, None), _Session(good, None)]})
    audio.set_session_volume(EP, 42, 0.25)
    assert good.level == 0.25
    assert [s.volume for s in audio._sessions[(EP, 42)]] == [good]


def test_peaks_takes_max_per_key_and_never_raises():
    audio = fake_system(
        dry_run=False,
        sessions={
            (EP, 1): [_Session(FakeVolume(), FakeMeter(0.2)), _Session(FakeVolume(), FakeMeter(0.7))],
            (EP, 2): [_Session(FakeVolume(), None)],
            (EP, 3): [_Session(FakeVolume(), FakeMeter(None))],  # device gone
        },
    )
    assert audio.peaks() == {(EP, 1): 0.7, (EP, 2): 0.0}
    assert (EP, 3) not in audio._sessions


def test_routing_uses_policy_and_degrades_when_unavailable():
    policy = FakePolicy(route=EP.upper())
    audio = fake_system(dry_run=False, policy=policy)
    assert audio.get_app_route(42) == EP  # spelled as the enumerator does
    audio.route_app(42, EP)
    audio.clear_all_routes()
    assert policy.calls == [("set", 42, EP), ("clear",)]

    unavailable = fake_system(dry_run=False, policy=FakePolicy(available=False))
    assert unavailable.get_app_route(42) is None
    with pytest.raises(OSError):
        unavailable.route_app(42, EP)
    unavailable.clear_all_routes()  # nothing to clear
    assert unavailable._policy.calls == []


def test_get_app_route_treats_untracked_pids_as_default():
    class Raising(FakePolicy):
        def __init__(self, errno):
            super().__init__()
            self.errno = errno

        def get_app_endpoint(self, pid):
            self.calls.append(("get", pid))
            raise OSError(self.errno, "failed")

    policy = Raising(0x80070057)  # E_INVALIDARG: audio service doesn't know the pid
    audio = fake_system(dry_run=False, policy=policy)
    assert audio.get_app_route(0) is None and policy.calls == []  # system sounds: not asked
    assert audio.get_app_route(42) is None
    with pytest.raises(OSError):
        fake_system(dry_run=False, policy=Raising(0x80004005)).get_app_route(42)

"""The brain of VolumeX.

Owns what the user wants (per-app gains, master, rules), watches what Windows
reports (snapshots from the AudioWorker thread) and makes Windows and the
engine match, using core.reconciler for every decision. The UI only talks to
this object.
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from PyQt5.QtCore import QMetaObject, QObject, Qt, QThread, QTimer, pyqtSignal

from volumex.engine_client.client import EngineClient
from volumex.platform.base import AudioSystem
from volumex.platform.worker import AudioWorker
from volumex.safety.journal import Journal
from volumex.safety.restore import restore_routes, running_pids
from volumex.storage.settings import Settings

from .app_identity import app_key, pretty_exe_name
from .bus import BUS_CAPTURE_MARKERS
from .models import SYSTEM_SOUNDS_KEY, AudioSnapshot, PeakMap, SessionInfo
from .reconciler import AppTarget, ReconcileInput, effective_gain, is_routable, plan, split_master

log = logging.getLogger(__name__)

LEAVE_DELAY_S = 3.0  # an app stays on the bus this long after dropping to <=100%
STALL_AFTER_S = 2.5  # routed app still playing on the normal device -> needs restart
GAIN_RAISE_DELAY_MS = 80  # let lowered session volumes reach the engine before raising G
GAIN_RAMP_MS = 40
GAIN_SETTLE_MS = 150  # after lowering G, when the engine is surely there
ENGINE_IDLE_STOP_S = 10.0
EXTERNAL_CHANGE_GRACE_S = 1.0  # ignore reads that may predate our own writes


@dataclass
class AppRecord:
    key: str
    name: str
    exe: str
    gain: float
    muted: bool
    remember: bool
    sessions: list[SessionInfo] = field(default_factory=list)
    present: bool = False
    absent_since: float = 0.0
    routed_at: float = 0.0
    stalled: bool = False
    route_retry_at: float = 0.0  # Windows refused to route it; don't retry before this


@dataclass(frozen=True)
class AppView:
    key: str
    name: str
    exe: str
    gain: float
    muted: bool
    remember: bool
    active: bool
    status: str  # "normal" | "boosted" | "pending" | "needs_restart" | "locked" | "paused"
    effective: float
    is_system: bool


@dataclass(frozen=True)
class MasterView:
    value: float  # what the master slider shows: endpoint volume x boost
    muted: bool
    device_id: str | None
    device_name: str
    boost_ready: bool  # a bus exists and the engine can stream
    boost_enabled: bool  # not paused by the user
    max_gain: float
    guard_enabled: bool
    default_is_bus: bool = False  # Windows itself sends everything into the cable (e.g. right after installing it)


@dataclass(frozen=True)
class EngineView:
    status: str  # "no_bus" | "starting" | "idle" | "streaming" | "error" | "failed"
    message: str = ""
    latency_ms: float | None = None
    underruns: int = 0
    output: str = ""


@dataclass(frozen=True)
class DeviceView:
    id: str
    name: str
    is_default: bool
    boost: float


class Controller(QObject):
    appsChanged = pyqtSignal(list)  # list[AppView]
    peaksChanged = pyqtSignal(dict)  # app key -> level 0..1 as heard
    masterChanged = pyqtSignal(object)  # MasterView
    engineChanged = pyqtSignal(object)  # EngineView
    engineMeters = pyqtSignal(dict)  # {"peak": [l, r], "gr_db": float, ...}
    devicesChanged = pyqtSignal(list)  # list[DeviceView]
    rulesChanged = pyqtSignal()
    osdRequested = pyqtSignal(str, str, float, float)  # title, exe for icon, value, max
    notify = pyqtSignal(str, str)  # title, message
    backendFailed = pyqtSignal(str)

    _applyActions = pyqtSignal(list)
    _requestRefresh = pyqtSignal()

    def __init__(
        self,
        settings: Settings,
        journal: Journal,
        audio_factory: Callable[[], AudioSystem],
        *,
        real_windows: bool = True,
        engine_fake_io: bool = False,
        foreground: Callable[[], tuple[int, str] | None] | None = None,
        engine: EngineClient | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.journal = journal
        self._audio_factory = audio_factory
        self._real = real_windows
        self._foreground = foreground

        self.snapshot: AudioSnapshot | None = None
        self.apps: dict[str, AppRecord] = {}
        self.routed: set[str] = set(journal.routes)  # survives crashes via the journal
        self._sticky_until: dict[str, float] = {}
        self._last_set: dict[tuple[str, int], tuple[float, float]] = {}  # ref -> (value, time)
        self._last_mute: dict[tuple[str, int], tuple[bool, float]] = {}  # ref -> (muted, time)
        self._pid_scans: dict[str, float] = {}
        # Apps whose first session on the bus hasn't been seen yet: that session starts at an unknown
        # volume (often 100%), so the engine stays at or below their gain until it has been set.
        self._joining: dict[str, tuple[float, float]] = {}  # key -> (effective gain, since)
        self._last_views: list[AppView] = []
        self._peaks: dict[str, float] = {}

        self.default_id: str | None = None
        self._last_real_default: str | None = None
        self.endpoint_volume = 1.0
        self.endpoint_muted = False
        self._endpoint_set_at = 0.0
        self.boost = 1.0  # B, remembered per output device

        self.engine_gain_sent = 1.0
        self.engine_gain_safe = 1.0  # never below what the engine really applies
        self._pending_raise: float | None = None
        self.engine_streaming = False
        self._start_requested = False
        self._configured_output: str | None = None
        self._engine_status = "no_bus"
        self._engine_message = ""
        self._engine_latency: float | None = None
        self._engine_underruns = 0
        self._last_boost_wanted = 0.0
        self._start_retry_at = 0.0  # after a stream error, wait before asking the engine to start again
        self._start_failures = 0
        self._last_plan_members: frozenset[str] = frozenset()

        # -- worker thread (all COM lives there) --
        self._thread = QThread()
        self._thread.setObjectName("VolumeX-Audio")
        self._worker = AudioWorker(audio_factory, init_com=real_windows)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.start)
        self._worker.snapshotReady.connect(self._on_snapshot)
        self._worker.peaksReady.connect(self._on_peaks)
        self._worker.actionFailed.connect(self._on_action_failed)
        self._worker.fatal.connect(self.backendFailed)
        self._applyActions.connect(self._worker.apply)
        self._requestRefresh.connect(self._worker.refresh)

        # -- engine process --
        self.engine = engine or EngineClient(fake_io=engine_fake_io, parent=self)
        self.engine.ready.connect(self._on_engine_ready)
        self.engine.stateChanged.connect(self._on_engine_state)
        self.engine.meters.connect(self._on_engine_meters)
        self.engine.error.connect(self._on_engine_error)
        self.engine.stopped.connect(self._on_engine_stopped)
        self.engine.gaveUp.connect(self._on_engine_gave_up)

        self._reconcile_timer = QTimer(self)
        self._reconcile_timer.setSingleShot(True)
        self._reconcile_timer.setInterval(15)
        self._reconcile_timer.timeout.connect(self.reconcile)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)
        self._save_timer.timeout.connect(self.settings.save)
        self._raise_timer = QTimer(self)
        self._raise_timer.setSingleShot(True)
        self._raise_timer.timeout.connect(self._send_raise)
        # All delayed work runs on timers owned by this object, so nothing fires after it is gone.
        self._settle_timer = self._one_shot(GAIN_SETTLE_MS, self._settle_gain)
        self._join_timer = self._one_shot(GAIN_SETTLE_MS + 20, self._flush_joins)
        self._pending_joins: list[tuple] = []
        self._refresh_timers = [self._one_shot(ms, self._requestRefresh.emit) for ms in (120, 350)]

    def _one_shot(self, interval_ms: int, slot) -> QTimer:
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(interval_ms)
        timer.timeout.connect(slot)
        return timer

    # ======================================================================================
    # lifecycle
    # ======================================================================================
    def start(self) -> None:
        self._thread.start()

    def shutdown(self) -> None:
        """Route every app back, stop the worker and the engine. Blocking, called on quit."""
        for timer in (self._reconcile_timer, self._raise_timer, self._settle_timer, self._join_timer,
                      *self._refresh_timers):
            timer.stop()
        if self._thread.isRunning():
            QMetaObject.invokeMethod(self._worker, "stop", Qt.BlockingQueuedConnection)
            self._thread.quit()
            self._thread.wait(3000)
        if self.routed and self._real:
            audio = self._audio_factory()
            try:
                volumes = {k: min(1.0, self._effective_unclamped(k)) for k in self.routed if k in self.apps}
                restore_routes(audio, self.journal, volumes)
            except Exception:  # noqa: BLE001 - never block quitting
                log.exception("restore on shutdown failed")
            finally:
                audio.close()
        self.engine.shutdown()
        self.settings.save()

    # ======================================================================================
    # views
    # ======================================================================================
    def master_view(self) -> MasterView:
        ep = self.snapshot.endpoint(self.default_id) if self.snapshot else None
        return MasterView(
            value=self.endpoint_volume * self.boost,
            muted=self.endpoint_muted,
            device_id=self.default_id,
            device_name=ep.name if ep else "No output device",
            boost_ready=self.boost_ready,
            boost_enabled=bool(self.settings["boost_enabled"]),
            max_gain=self.max_gain,
            guard_enabled=bool(self.settings["guard"]["enabled"]),
            default_is_bus=bool(ep and ep.is_bus),
        )

    def engine_view(self) -> EngineView:
        return EngineView(
            status=self._engine_status,
            message=self._engine_message,
            latency_ms=self._engine_latency,
            underruns=self._engine_underruns,
            output=self._configured_output or "",
        )

    def device_views(self) -> list[DeviceView]:
        if not self.snapshot:
            return []
        return [
            DeviceView(ep.id, ep.name, ep.id == self.default_id, self.settings.device_boost(ep.id))
            for ep in self.snapshot.endpoints
            if not ep.is_bus
        ]

    def app_views(self) -> list[AppView]:
        return list(self._last_views)

    @property
    def max_gain(self) -> float:
        return float(self.settings["max_gain"])

    @property
    def bus_present(self) -> bool:
        return bool(self.snapshot and self.snapshot.bus)

    @property
    def boost_ready(self) -> bool:
        return self.bus_present and self._engine_status not in ("failed",)

    @property
    def boost_available(self) -> bool:
        return self.bus_present and self.engine_streaming and bool(self.settings["boost_enabled"])

    # ======================================================================================
    # user actions (called by the UI)
    # ======================================================================================
    def set_app_gain(self, key: str, gain: float) -> None:
        rec = self.apps.get(key)
        if rec is None:
            return
        rec.gain = max(0.0, min(self.max_gain, gain))
        self._remember(rec)
        self.schedule_reconcile()

    def set_app_muted(self, key: str, muted: bool) -> None:
        rec = self.apps.get(key)
        if rec is None:
            return
        rec.muted = muted
        self._remember(rec)
        self.schedule_reconcile()

    def set_app_remember(self, key: str, remember: bool) -> None:
        rec = self.apps.get(key)
        if rec is None:
            if not remember:
                self.settings.forget_app(key)
                self._save_soon()
                self.rulesChanged.emit()
            return
        rec.remember = remember
        if remember:
            self._remember(rec)
        else:
            self.settings.forget_app(key)
            self._save_soon()
        self._emit_apps(force=True)
        self.rulesChanged.emit()

    def set_master(self, value: float) -> None:
        value = max(0.0, min(self.max_gain, value))
        volume, boost = split_master(value)
        self.boost = boost
        if self.default_id:
            if abs(volume - self.endpoint_volume) > 1e-4:
                self._applyActions.emit([("endpoint_volume", self.default_id, volume)])
                self._endpoint_set_at = time.monotonic()
            ep = self.snapshot.endpoint(self.default_id) if self.snapshot else None
            self.settings.set_device_boost(self.default_id, ep.name if ep else "", boost)
            self._save_soon()
        self.endpoint_volume = volume
        self.masterChanged.emit(self.master_view())
        self.schedule_reconcile()

    def set_master_muted(self, muted: bool) -> None:
        if self.default_id:
            self._applyActions.emit([("endpoint_mute", self.default_id, muted)])
            self._endpoint_set_at = time.monotonic()
        self.endpoint_muted = muted
        self.masterChanged.emit(self.master_view())

    def set_boost_enabled(self, enabled: bool) -> None:
        self.settings["boost_enabled"] = enabled
        self._save_soon()
        self.masterChanged.emit(self.master_view())
        self.schedule_reconcile()

    def set_guard(self, enabled: bool) -> None:
        self.settings["guard"]["enabled"] = enabled
        self._save_soon()
        self.engine.send({"cmd": "set_limiter", **self._limiter_params()})
        self.masterChanged.emit(self.master_view())

    def set_max_gain(self, max_gain: float) -> None:
        self.settings["max_gain"] = float(max_gain)
        for rec in self.apps.values():
            if rec.gain > max_gain:
                rec.gain = max_gain
                if rec.remember:
                    self._remember(rec)
        if self.endpoint_volume * self.boost > max_gain:
            self.set_master(max_gain)
        self._save_soon()
        self.masterChanged.emit(self.master_view())
        self.schedule_reconcile()

    def fix_default_device(self) -> None:
        """Windows is playing everything into the cable: point it back at a real device."""
        snap = self.snapshot
        if snap is None:
            return
        target = snap.endpoint(self._last_real_default) or next((e for e in snap.endpoints if not e.is_bus), None)
        if target is None:
            self.notify.emit("No speakers found", "Connect speakers or headphones, then try again.")
            return
        self._applyActions.emit([("set_default", target.id)])
        self._requestRefresh.emit()
        self.notify.emit("Sound fixed", f"Windows plays through {target.name} again.")

    def set_output_device(self, endpoint_id: str | None) -> None:
        self.settings["engine"]["output"] = endpoint_id
        self._save_soon()
        self._configure_engine()

    def nudge_master(self, delta: float) -> None:
        self.set_master(round((self.endpoint_volume * self.boost + delta) * 50) / 50)
        self.osdRequested.emit("Master volume", "", self.endpoint_volume * self.boost, self.max_gain)

    def nudge_focused(self, delta: float) -> None:
        rec = self._focused_app()
        if rec is None:
            return
        self.set_app_gain(rec.key, round((rec.gain + delta) * 50) / 50)
        self.osdRequested.emit(rec.name, rec.exe, rec.gain, self.max_gain)

    def reset_focused(self) -> None:
        rec = self._focused_app()
        if rec is None:
            return
        self.set_app_gain(rec.key, 1.0)
        self.osdRequested.emit(rec.name, rec.exe, rec.gain, self.max_gain)

    def toggle_boost(self) -> None:
        enabled = not bool(self.settings["boost_enabled"])
        self.set_boost_enabled(enabled)
        self.osdRequested.emit("Boost " + ("on" if enabled else "paused"), "", 1.0 if enabled else 0.0, 1.0)

    def reset_audio(self) -> None:
        """Panic button: every app back to 100%, no boost, everything routed back."""
        for rec in self.apps.values():
            rec.gain = 1.0
            rec.muted = False
            if rec.remember:
                self._remember(rec)
        self.set_master(min(self.endpoint_volume, 1.0))
        self._sticky_until.clear()
        self.schedule_reconcile()
        self.notify.emit("Audio reset", "Every app is back at 100% and boosting is off.")

    # -- rules ---------------------------------------------------------------------------
    def rules(self) -> list[dict]:
        return list(self.settings["rules"])

    def add_rule(self, trigger: str, trigger_name: str, target: str, target_name: str, gain: float) -> None:
        self.settings["rules"].append(
            {
                "id": uuid.uuid4().hex[:8],
                "trigger": trigger,
                "trigger_name": trigger_name,
                "target": target,
                "target_name": target_name,
                "gain": round(gain, 3),
                "enabled": True,
            }
        )
        self._save_soon()
        self.rulesChanged.emit()

    def remove_rule(self, rule_id: str) -> None:
        self.settings["rules"] = [r for r in self.settings["rules"] if r["id"] != rule_id]
        self._save_soon()
        self.rulesChanged.emit()

    def set_rule_enabled(self, rule_id: str, enabled: bool) -> None:
        for rule in self.settings["rules"]:
            if rule["id"] == rule_id:
                rule["enabled"] = enabled
        self._save_soon()
        self.rulesChanged.emit()

    def known_apps(self) -> list[tuple[str, str, str]]:
        """(key, name, exe) of every app seen now or remembered, for rule pickers."""
        seen = {k: (k, r.name, r.exe) for k, r in self.apps.items() if k != SYSTEM_SOUNDS_KEY}
        for key, entry in self.settings["apps"].items():
            seen.setdefault(key, (key, entry.get("name", key), entry.get("exe", "")))
        return sorted(seen.values(), key=lambda item: item[1].lower())

    # ======================================================================================
    # snapshots and meters from the worker
    # ======================================================================================
    def _excluded_pids(self) -> frozenset[int]:
        pids = {os.getpid()}
        if self.engine.pid:
            pids.add(self.engine.pid)
        return frozenset(pids)

    def _on_snapshot(self, snap: AudioSnapshot) -> None:
        now = time.monotonic()
        had_bus = self.bus_present
        self.snapshot = snap
        excluded = self._excluded_pids()

        # master / device
        default_ep = snap.endpoint(snap.default_endpoint_id)
        if default_ep is not None and not default_ep.is_bus:
            self._last_real_default = default_ep.id
        if snap.default_endpoint_id != self.default_id:
            self.default_id = snap.default_endpoint_id
            self.boost = self.settings.device_boost(self.default_id)
            self.endpoint_volume = snap.endpoint_volume
            self.endpoint_muted = snap.endpoint_muted
            self._configure_engine()
            self.devicesChanged.emit(self.device_views())
            self.masterChanged.emit(self.master_view())
        elif now - self._endpoint_set_at > EXTERNAL_CHANGE_GRACE_S and (
            abs(snap.endpoint_volume - self.endpoint_volume) > 0.004 or snap.endpoint_muted != self.endpoint_muted
        ):
            self.endpoint_volume = snap.endpoint_volume  # volume keys or the Windows mixer
            self.endpoint_muted = snap.endpoint_muted
            self.masterChanged.emit(self.master_view())

        if self.bus_present != had_bus:
            self._on_bus_presence_changed()

        # apps
        by_key: dict[str, list[SessionInfo]] = {}
        for s in snap.sessions:
            if s.pid not in excluded:
                by_key.setdefault(s.key, []).append(s)
        for key, sessions in by_key.items():
            rec = self.apps.get(key)
            appeared = rec is None or (not rec.present and now - rec.absent_since > 5.0)
            if rec is None:
                rec = self._new_record(key, sessions)
                self.apps[key] = rec
            rec.sessions = sessions
            rec.present = True
            self._detect_external_changes(rec, now)
            if appeared and key != SYSTEM_SOUNDS_KEY:
                self._run_rules(key)
        for key, rec in self.apps.items():
            if key not in by_key and rec.present:
                rec.present = False
                rec.sessions = []
                rec.absent_since = now

        self.reconcile()

    def _new_record(self, key: str, sessions: list[SessionInfo]) -> AppRecord:
        first = sessions[0]
        stored = self.settings.app(key)
        if stored:
            return AppRecord(key, first.name, first.exe_path, float(stored.get("gain", 1.0)),
                             bool(stored.get("muted", False)), True)
        bus_ids = self._bus_ids()
        direct = [s for s in sessions if s.endpoint_id not in bus_ids]
        observed = max(direct, key=lambda s: s.active) if direct else None
        gain = observed.volume if observed else 1.0
        muted = observed.muted if observed else False
        return AppRecord(key, first.name, first.exe_path, gain, muted, False)

    def _detect_external_changes(self, rec: AppRecord, now: float) -> None:
        """Someone changed this app in the Windows mixer: adopt it instead of fighting."""
        bus_ids = self._bus_ids()
        for s in rec.sessions:
            ref = (s.endpoint_id, s.pid)
            last = self._last_set.get(ref)
            if last is not None and now - last[1] > EXTERNAL_CHANGE_GRACE_S and abs(s.volume - last[0]) > 0.015:
                heard = s.volume * (self.engine_gain_sent if s.endpoint_id in bus_ids else 1.0)
                rec.gain = max(0.0, min(self.max_gain, heard / max(self.boost, 1.0)))
                self._last_set[ref] = (s.volume, now)
                log.info("external volume change on %s -> %.2f", rec.key, rec.gain)
                if rec.remember:
                    self._remember(rec)
            last_mute = self._last_mute.get(ref)
            if last_mute is not None and s.muted != last_mute[0] and now - last_mute[1] > EXTERNAL_CHANGE_GRACE_S:
                rec.muted = s.muted
                self._last_mute[ref] = (s.muted, now)
                if rec.remember:
                    self._remember(rec)

    def _on_peaks(self, peaks: PeakMap) -> None:
        bus_ids = self._bus_ids()
        levels: dict[str, float] = {}
        for rec in self.apps.values():
            if not rec.present:
                continue
            level = 0.0
            for s in rec.sessions:
                p = peaks.get((s.endpoint_id, s.pid), 0.0)
                if s.endpoint_id in bus_ids:
                    p *= self.engine_gain_sent
                level = max(level, p)
            levels[rec.key] = min(1.0, level)
        self._peaks = levels
        self.peaksChanged.emit(levels)

    def _on_action_failed(self, action: tuple, error: str) -> None:
        if action[0] == "route" and action[2] is not None:
            # could not route to the bus: forget the join and wait before trying again
            now = time.monotonic()
            for key, rec in self.apps.items():
                if any(s.pid == action[1] for s in rec.sessions) and key in self.routed:
                    self.routed.discard(key)
                    self.journal.remove_route(key)
                    self._joining.pop(key, None)
                    rec.stalled = True
                    if now >= rec.route_retry_at:
                        self.notify.emit(f"Couldn't boost {rec.name}", error)
                    rec.route_retry_at = now + 30.0

    # ======================================================================================
    # reconcile: make Windows and the engine match what the user wants
    # ======================================================================================
    def schedule_reconcile(self) -> None:
        if not self._reconcile_timer.isActive():
            self._reconcile_timer.start()

    def reconcile(self) -> None:
        snap = self.snapshot
        if snap is None:
            return
        now = time.monotonic()
        bus_ids = self._bus_ids()
        bus_id = next(iter(bus_ids), None)
        targets = {k: AppTarget(r.gain, r.muted) for k, r in self.apps.items() if r.present}
        boost_enabled = bool(self.settings["boost_enabled"])

        # does anyone want boost at all? then the engine must stream
        wants = boost_enabled and self.bus_present and any(
            effective_gain(t, self.boost, self.max_gain, True) > 1.0 + 1e-3 and is_routable(k)
            for k, t in targets.items()
        )
        if wants:
            self._last_boost_wanted = now
        self._drive_engine(wants or bool(self.routed & set(targets)), now)

        # stalled detection for apps we routed
        for key in self.routed:
            rec = self.apps.get(key)
            if not rec or not rec.present:
                continue
            on_bus = any(s.active and s.endpoint_id in bus_ids for s in rec.sessions)
            direct = any(s.active and s.endpoint_id not in bus_ids for s in rec.sessions)
            if on_bus:
                rec.stalled = False
            elif direct and now - rec.routed_at > STALL_AFTER_S:
                rec.stalled = True

        base = ReconcileInput(
            snapshot=snap,
            apps=targets,
            master_boost=self.boost,
            max_gain=self.max_gain,
            boost_available=self.boost_available,
            engine_gain=max(self.engine_gain_safe, self.engine_gain_sent),
            stalled=frozenset(k for k, r in self.apps.items() if r.stalled),
            excluded_pids=self._excluded_pids(),
        )
        raw = plan(base)
        # debounce leaving: keep an app on the bus a moment after it drops to <=100%
        for key in raw.members:
            self._sticky_until.pop(key, None)
        if self.boost_available:
            for key in self.routed - raw.members:
                self._sticky_until.setdefault(key, now + LEAVE_DELAY_S)
        else:
            self._sticky_until.clear()
        sticky = frozenset(k for k, t in self._sticky_until.items() if t > now and k in self.routed)
        result = plan(replace(base, sticky_members=sticky)) if sticky else raw
        self._last_plan_members = result.members

        actions: list[tuple] = []
        sessions = {(s.endpoint_id, s.pid): s for s in snap.sessions}
        for ref, vol in result.session_volumes.items():
            s = sessions[ref]
            last = self._last_set.get(ref)
            if abs(s.volume - vol) > 0.002 and (last is None or abs(last[0] - vol) > 0.002 or now - last[1] > 1.0):
                actions.append(("session_volume", ref[0], ref[1], vol))
                self._last_set[ref] = (vol, now)
            elif last is None:
                self._last_set[ref] = (s.volume, now - EXTERNAL_CHANGE_GRACE_S)
        for ref, muted in result.session_mutes.items():
            last_mute = self._last_mute.get(ref)
            if sessions[ref].muted != muted and (last_mute is None or last_mute[0] != muted or now - last_mute[1] > 1.0):
                actions.append(("session_mute", ref[0], ref[1], muted))
                self._last_mute[ref] = (muted, now)
            elif last_mute is None or last_mute[0] != muted:
                self._last_mute[ref] = (muted, now - EXTERNAL_CHANGE_GRACE_S)

        # joins in progress end once the app's bus session exists (its volume is set just above)
        for key, (_g, since) in list(self._joining.items()):
            rec = self.apps.get(key)
            on_bus = rec is not None and any(s.endpoint_id in bus_ids for s in rec.sessions)
            if key not in result.members or on_bus or now - since > STALL_AFTER_S:
                del self._joining[key]

        # routing: volumes above are already lowered, so joins/leaves can go now
        joins: list[tuple] = []
        for key in result.members - self.routed:
            rec = self.apps[key]
            pids = sorted({s.pid for s in rec.sessions})
            if not pids or bus_id is None or now < rec.route_retry_at:
                continue
            self.journal.add_route(key, rec.exe, min(1.0, result.effective.get(key, 1.0)))
            joins.extend(("route", pid, bus_id) for pid in pids)
            self.routed.add(key)
            self._joining[key] = (result.effective.get(key, 1.0), now)
            rec.routed_at = now
            rec.stalled = False
        cap = min((g for g, _ in self._joining.values()), default=None)
        gain_target = result.bus_gain if cap is None else max(1.0, min(result.bus_gain, cap))
        if joins:
            if gain_target < max(self.engine_gain_safe, self.engine_gain_sent) - 1e-4:
                # the engine must come down before the newcomer arrives on the bus
                self._pending_joins.extend(joins)
                self._join_timer.start()
            else:
                actions.extend(joins)
        for key in list(self.routed - result.members):
            rec = self.apps.get(key)
            pids = sorted({s.pid for s in rec.sessions}) if rec and rec.present else []
            if not pids and self._real and now - self._pid_scans.get(key, 0.0) > 5.0:
                self._pid_scans[key] = now  # running without a session? (scan is slow, so rate-limit it)
                pids = running_pids(key)
            if not pids:
                continue  # not running; it's reset the next time it shows up
            actions.extend(("route", pid, None) for pid in pids)
            self.routed.discard(key)
            self.journal.remove_route(key)
            self._sticky_until.pop(key, None)
            if rec:
                rec.stalled = False

        if actions:
            self._applyActions.emit(actions)
            if any(a[0] == "route" for a in actions):
                self._refresh_soon()

        self._drive_gain(gain_target)
        self._emit_apps()

    def _flush_joins(self) -> None:
        joins, self._pending_joins = self._pending_joins, []
        routed_pids = {s.pid for k, r in self.apps.items() if k in self.routed for s in r.sessions}
        still = [a for a in joins if a[1] in routed_pids]
        if still:
            self._applyActions.emit(still)
            self._refresh_soon()

    def _refresh_soon(self) -> None:
        """Look again quickly after routing, so new sessions get their volume without waiting a full poll."""
        for timer in self._refresh_timers:
            timer.start()

    def _drive_gain(self, target: float) -> None:
        if abs(target - self.engine_gain_sent) < 1e-4 and self._pending_raise is None:
            return
        if target > self.engine_gain_sent + 1e-4:
            # sessions were lowered just now; raise the engine a moment later
            self._pending_raise = target
            if not self._raise_timer.isActive():
                self._raise_timer.start(GAIN_RAISE_DELAY_MS)
            return
        if target < self.engine_gain_sent - 1e-4:
            self._pending_raise = None
            self._raise_timer.stop()
            self.engine_gain_sent = target
            self.engine.send({"cmd": "set_gain", "gain": target, "ramp_ms": GAIN_RAMP_MS})
            self._settle_timer.start()
        else:
            self._pending_raise = None

    def _send_raise(self) -> None:
        target = self._pending_raise
        self._pending_raise = None
        if target is None:
            return
        self.engine_gain_sent = target
        self.engine_gain_safe = max(self.engine_gain_safe, target)
        self.engine.send({"cmd": "set_gain", "gain": target, "ramp_ms": GAIN_RAMP_MS})

    def _settle_gain(self) -> None:
        if self.engine_gain_safe > self.engine_gain_sent and self._pending_raise is None:
            self.engine_gain_safe = self.engine_gain_sent
            self.schedule_reconcile()

    # ======================================================================================
    # engine
    # ======================================================================================
    def _on_bus_presence_changed(self) -> None:
        if self.bus_present:
            self._set_engine_status("starting", "Starting the boost engine…")
            self.engine.reset_crash_budget()
            self.engine.start()
        else:
            self.engine.shutdown()
            self.engine_streaming = False
            self._set_engine_status("no_bus", "Install VB-CABLE to unlock boost above 100%.")
        self.masterChanged.emit(self.master_view())

    def _output_device_name(self) -> str | None:
        snap = self.snapshot
        if snap is None:
            return None
        wanted = self.settings["engine"].get("output")
        ep = snap.endpoint(wanted) if wanted else None
        if ep is None or ep.is_bus:
            ep = snap.endpoint(snap.default_endpoint_id)
        if ep is None or ep.is_bus:
            ep = next((e for e in snap.endpoints if not e.is_bus), None)
        return ep.name if ep else None

    def _limiter_params(self) -> dict:
        guard = self.settings["guard"]
        return {
            "enabled": bool(guard["enabled"]),
            "ceiling_db": float(guard["ceiling_db"]),
            "release_ms": float(guard["release_ms"]),
        }

    def _configure_engine(self) -> None:
        output = self._output_device_name()
        if not self.engine.is_ready or output is None:
            return
        self._configured_output = output
        self.engine.send(
            {
                "cmd": "configure",
                "capture": BUS_CAPTURE_MARKERS[0],
                "output": output,
                "gain": self.engine_gain_sent,
                "limiter": {**self._limiter_params(), "lookahead_ms": 3.0},
                "target_latency_ms": float(self.settings["engine"]["target_latency_ms"]),
            }
        )

    def _drive_engine(self, wanted: bool, now: float) -> None:
        if not self.engine.is_ready:
            return
        if wanted and not self.engine_streaming and not self._start_requested and now >= self._start_retry_at:
            self._start_requested = True
            self.engine.send({"cmd": "start"})
        elif not wanted and self.engine_streaming and not self.routed and now - self._last_boost_wanted > ENGINE_IDLE_STOP_S:
            self.engine.send({"cmd": "stop"})

    def _on_engine_ready(self, _msg: dict) -> None:
        self._start_requested = False
        self.engine_streaming = False
        self._configure_engine()
        self._set_engine_status("idle", "Ready - starts automatically when an app is boosted.")
        self.schedule_reconcile()

    def _on_engine_state(self, msg: dict) -> None:
        self._start_requested = False
        self.engine_streaming = bool(msg.get("streaming"))
        self._engine_latency = msg.get("latency_ms")
        if self.engine_streaming:
            self._start_failures = 0
            self._set_engine_status("streaming", f"Boosting via {msg.get('output', '')}")
        else:
            self._set_engine_status("idle", "Ready - starts automatically when an app is boosted.")
        self.masterChanged.emit(self.master_view())
        self.schedule_reconcile()

    def _on_engine_meters(self, msg: dict) -> None:
        self._engine_underruns = int(msg.get("underruns", 0))
        self.engineMeters.emit(msg)

    def _on_engine_error(self, code: str, message: str) -> None:
        log.warning("engine error %s: %s", code, message)
        self._start_requested = False
        if code in ("device_not_found", "stream_failed"):
            self.engine_streaming = False
            self._start_failures += 1
            self._start_retry_at = time.monotonic() + min(30.0, 2.0 * self._start_failures)
            self._set_engine_status("error", message or "The boost engine could not open the audio devices.")
            self.schedule_reconcile()

    def _on_engine_stopped(self) -> None:
        self.engine_streaming = False
        self._start_requested = False
        self._set_engine_status("starting", "The boost engine stopped - restarting…")
        self.schedule_reconcile()  # boost unavailable -> apps are routed back right away

    def _on_engine_gave_up(self, reason: str) -> None:
        self._set_engine_status("failed", reason)
        self.notify.emit("Boost paused", reason + " Apps play normally at up to 100%.")
        self.masterChanged.emit(self.master_view())
        self.schedule_reconcile()

    def _set_engine_status(self, status: str, message: str) -> None:
        self._engine_status = status
        self._engine_message = message
        self.engineChanged.emit(self.engine_view())

    # ======================================================================================
    # helpers
    # ======================================================================================
    def _bus_ids(self) -> set[str]:
        return {ep.id for ep in self.snapshot.endpoints if ep.is_bus} if self.snapshot else set()

    def _effective_unclamped(self, key: str) -> float:
        rec = self.apps[key]
        return effective_gain(AppTarget(rec.gain), self.boost, self.max_gain, True)

    def _remember(self, rec: AppRecord) -> None:
        rec.remember = True
        self.settings.remember_app(rec.key, rec.name, rec.exe, rec.gain, rec.muted)
        if rec.key in self.routed:
            self.journal.update_restore_volume(rec.key, min(1.0, self._effective_unclamped(rec.key)))
        self._save_soon()

    def _save_soon(self) -> None:
        self._save_timer.start()

    def _focused_app(self) -> AppRecord | None:
        if self._foreground is None:
            return None
        found = self._foreground()
        if not found:
            return None
        pid, exe = found
        key = app_key(exe, pid)
        rec = self.apps.get(key)
        if rec is None or not rec.present:
            self.osdRequested.emit(f"{pretty_exe_name(exe)} isn't playing audio", exe, -1.0, self.max_gain)
            return None
        return rec

    def _run_rules(self, trigger_key: str) -> None:
        for rule in self.settings["rules"]:
            if not rule.get("enabled", True) or rule.get("trigger") != trigger_key:
                continue
            target = rule["target"]
            gain = float(rule["gain"])
            rec = self.apps.get(target)
            if rec is not None:
                rec.gain = max(0.0, min(self.max_gain, gain))
                self._remember(rec)
            else:
                entry = self.settings.app(target) or {"muted": False, "name": rule.get("target_name", target), "exe": ""}
                self.settings.remember_app(target, entry.get("name", target), entry.get("exe", ""), gain,
                                           bool(entry.get("muted", False)))
                self._save_soon()
            self.osdRequested.emit(f"{rule.get('target_name', 'App')} set by rule", "", gain, self.max_gain)

    def _status_for(self, rec: AppRecord, effective: float) -> str:
        wanted = effective_gain(AppTarget(rec.gain), self.boost, self.max_gain, True)
        if wanted <= 1.0 + 1e-3 or rec.key == SYSTEM_SOUNDS_KEY:
            return "normal"
        if not self.settings["boost_enabled"]:
            return "paused"
        if not self.bus_present or self._engine_status == "failed":
            return "locked"
        if not self.engine_streaming:
            return "pending"
        if rec.stalled:
            return "needs_restart"
        bus_ids = self._bus_ids()
        if any(s.active and s.endpoint_id in bus_ids for s in rec.sessions):
            return "boosted"
        return "pending"

    def _emit_apps(self, force: bool = False) -> None:
        views = []
        for rec in self.apps.values():
            if not rec.present:
                continue
            effective = effective_gain(
                AppTarget(rec.gain), self.boost, self.max_gain, self.boost_available and is_routable(rec.key)
            )
            views.append(
                AppView(
                    key=rec.key,
                    name=rec.name,
                    exe=rec.exe,
                    gain=rec.gain,
                    muted=rec.muted,
                    remember=rec.remember,
                    active=any(s.active for s in rec.sessions),
                    status=self._status_for(rec, effective),
                    effective=effective,
                    is_system=rec.key == SYSTEM_SOUNDS_KEY,
                )
            )
        views.sort(key=lambda v: (v.is_system, v.name.lower()))
        if force or views != self._last_views:
            self._last_views = views
            self.appsChanged.emit(views)

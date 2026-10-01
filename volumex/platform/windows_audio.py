"""Real Windows Core Audio backend (pycaw/comtypes) for the AudioSystem protocol.

The calling thread must already have called comtypes.CoInitializeEx(COINIT_MULTITHREADED);
every COM object created here stays owned by that thread.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import comtypes
import psutil
from comtypes import COMError
from pycaw.api.audioclient import ISimpleAudioVolume
from pycaw.api.audiopolicy import IAudioSessionControl2, IAudioSessionManager2
from pycaw.api.endpointvolume import IAudioEndpointVolume, IAudioMeterInformation
from pycaw.api.mmdeviceapi import IMMDeviceEnumerator
from pycaw.api.mmdeviceapi.depend.structures import PROPERTYKEY
from pycaw.constants import CLSID_MMDeviceEnumerator

from volumex.core.app_identity import app_key
from volumex.core.bus import is_bus_render_name
from volumex.core.models import AudioSnapshot, Endpoint, PeakMap, SessionInfo

from .appinfo import display_name
from .foreground import exe_path_for_pid
from .policy_config import AudioPolicyConfig

log = logging.getLogger(__name__)

E_RENDER = 0
E_MULTIMEDIA = 1
DEVICE_STATE_ACTIVE = 0x1
STGM_READ = 0
VT_LPWSTR = 31
AUDIO_SESSION_STATE_ACTIVE = 1
AUDIO_SESSION_STATE_EXPIRED = 2
SYSTEM_SOUNDS_NAME = "System sounds"
E_INVALIDARG = 0x80070057

# COM errors plus what comtypes raises for released/NULL pointers.
_COM_ERRORS = (COMError, OSError, ValueError)


def _property_key(fmtid: str, pid: int) -> PROPERTYKEY:
    key = PROPERTYKEY()
    key.fmtid = comtypes.GUID(fmtid)
    key.pid = pid
    return key


PKEY_Device_FriendlyName = _property_key("{a45c254e-df1c-4efd-8020-67d146a850e0}", 14)
PKEY_Device_DeviceDesc = _property_key("{a45c254e-df1c-4efd-8020-67d146a850e0}", 2)


def _clamp(level: float) -> float:
    return min(1.0, max(0.0, float(level)))


@dataclass
class _Session:
    """COM interfaces of one cached audio session."""

    volume: Any  # ISimpleAudioVolume
    meter: Any  # IAudioMeterInformation, or None if the session doesn't expose one


class WindowsAudioSystem:
    """AudioSystem backed by Windows Core Audio. With dry_run=True, nothing is ever changed:
    every mutating call only logs 'DRY-RUN ...'."""

    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self._enumerator = comtypes.CoCreateInstance(
            CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER
        )
        self._policy = AudioPolicyConfig()
        self._sessions: dict[tuple[str, int], list[_Session]] = {}
        self._endpoint_volumes: dict[str, Any] = {}  # endpoint id -> IAudioEndpointVolume
        self._exe_cache: dict[int, tuple[float, str]] = {}  # pid -> (create_time, exe path)
        self._endpoint_ids: tuple[str, ...] = ()

    @property
    def routing_available(self) -> bool:
        """False when IAudioPolicyConfigFactory can't be used on this Windows build."""
        return self._policy.available

    # ---- reading ---------------------------------------------------------------

    def snapshot(self) -> AudioSnapshot:
        default_id = self._default_endpoint_id()
        endpoints: list[Endpoint] = []
        sessions: list[SessionInfo] = []
        cache: dict[tuple[str, int], list[_Session]] = {}
        live_pids: set[int] = set()

        try:
            collection = self._enumerator.EnumAudioEndpoints(E_RENDER, DEVICE_STATE_ACTIVE)
            count = collection.GetCount()
        except _COM_ERRORS as exc:
            log.warning("Enumerating render endpoints failed: %s", exc)
            collection, count = None, 0

        for i in range(count):
            try:
                device = collection.Item(i)
                endpoint_id = device.GetId()
                name = self._friendly_name(device, endpoint_id)
            except _COM_ERRORS as exc:
                log.debug("Skipping endpoint %d: %s", i, exc)
                continue
            endpoints.append(Endpoint(endpoint_id, name, endpoint_id == default_id, is_bus_render_name(name)))
            try:
                sessions.extend(self._read_sessions(device, endpoint_id, cache, live_pids))
            except _COM_ERRORS as exc:
                log.debug("Reading sessions of %s failed: %s", name, exc)

        self._sessions = cache
        self._endpoint_ids = tuple(ep.id for ep in endpoints)
        self._endpoint_volumes = {k: v for k, v in self._endpoint_volumes.items() if k in self._endpoint_ids}
        self._exe_cache = {pid: v for pid, v in self._exe_cache.items() if pid in live_pids}
        volume, muted = self._read_endpoint_volume(default_id)
        return AudioSnapshot(tuple(endpoints), default_id, tuple(sessions), volume, muted)

    def peaks(self) -> PeakMap:
        result: PeakMap = {}
        stale: list[tuple[str, int]] = []
        for key, cached in self._sessions.items():
            try:
                result[key] = max((s.meter.GetPeakValue() for s in cached if s.meter is not None), default=0.0)
            except Exception:  # device or session gone; peaks() must never raise
                stale.append(key)
        for key in stale:
            self._sessions.pop(key, None)
        return result

    def get_app_route(self, pid: int) -> str | None:
        if not self._policy.available or pid <= 0:
            return None
        try:
            endpoint_id = self._policy.get_app_endpoint(pid)
        except OSError as exc:
            if exc.errno == E_INVALIDARG:  # a pid the audio service doesn't track (never played audio / exited)
                return None
            raise
        if endpoint_id is None:
            return None
        # The policy store may not preserve case; return the id as the enumerator spells it.
        for known in self._endpoint_ids:
            if known.lower() == endpoint_id.lower():
                return known
        return endpoint_id

    def _default_endpoint_id(self) -> str | None:
        try:
            return self._enumerator.GetDefaultAudioEndpoint(E_RENDER, E_MULTIMEDIA).GetId()
        except _COM_ERRORS:  # E_NOTFOUND when there is no render device
            return None

    @staticmethod
    def _friendly_name(device: Any, endpoint_id: str) -> str:
        try:
            store = device.OpenPropertyStore(STGM_READ)
        except _COM_ERRORS:
            return endpoint_id
        for key in (PKEY_Device_FriendlyName, PKEY_Device_DeviceDesc):
            try:
                value = store.GetValue(key)
            except _COM_ERRORS:
                continue
            try:
                text = value.GetValue() if value.vt == VT_LPWSTR else None  # pycaw returns "0:?" for VT_EMPTY
            finally:
                value.clear()
            if isinstance(text, str) and text.strip():
                return text.strip()
        return endpoint_id

    def _read_sessions(
        self,
        device: Any,
        endpoint_id: str,
        cache: dict[tuple[str, int], list[_Session]],
        live_pids: set[int],
    ) -> list[SessionInfo]:
        manager = device.Activate(IAudioSessionManager2._iid_, comtypes.CLSCTX_ALL, None)
        manager = manager.QueryInterface(IAudioSessionManager2)
        enumerator = manager.GetSessionEnumerator()

        # pid -> (exe, is_system, [(active, volume, muted)])
        found: dict[int, tuple[str, bool, list[tuple[bool, float, bool]]]] = {}
        for i in range(enumerator.GetCount()):
            try:
                control = enumerator.GetSession(i).QueryInterface(IAudioSessionControl2)
                state = control.GetState()
                if state == AUDIO_SESSION_STATE_EXPIRED:
                    continue
                pid = control.GetProcessId()
                is_system = control.IsSystemSoundsSession() == 0  # S_OK means yes
                exe = "" if is_system else self._exe_for_pid(pid)
                if exe is None:
                    continue  # process no longer exists
                volume = control.QueryInterface(ISimpleAudioVolume)
                level, muted = volume.GetMasterVolume(), bool(volume.GetMute())
                try:
                    meter = control.QueryInterface(IAudioMeterInformation)
                except _COM_ERRORS:
                    meter = None
            except _COM_ERRORS as exc:
                log.debug("Skipping session %d on %s: %s", i, endpoint_id, exc)
                continue
            live_pids.add(pid)
            cache.setdefault((endpoint_id, pid), []).append(_Session(volume, meter))
            entry = found.setdefault(pid, (exe, is_system, []))
            entry[2].append((state == AUDIO_SESSION_STATE_ACTIVE, level, muted))

        infos = []
        for pid, (exe, is_system, states) in found.items():
            # A process can own several sessions on one endpoint; report them as one app row.
            infos.append(
                SessionInfo(
                    endpoint_id=endpoint_id,
                    pid=pid,
                    key=app_key(exe, 0 if is_system else pid),
                    exe_path=exe,
                    name=SYSTEM_SOUNDS_NAME if is_system else display_name(exe),
                    active=any(s[0] for s in states),
                    volume=max(s[1] for s in states),
                    muted=all(s[2] for s in states),
                )
            )
        return infos

    def _exe_for_pid(self, pid: int) -> str | None:
        """Exe path, cached per (pid, create time). None if the process is gone."""
        try:
            created = psutil.Process(pid).create_time()
        except psutil.NoSuchProcess:
            return None
        except psutil.Error:
            created = 0.0
        cached = self._exe_cache.get(pid)
        if cached and cached[0] == created:
            return cached[1]
        exe = exe_path_for_pid(pid)
        if not exe:
            try:
                exe = psutil.Process(pid).name()  # still better than no identity at all
            except psutil.Error:
                return None
        self._exe_cache[pid] = (created, exe)
        return exe

    def _read_endpoint_volume(self, endpoint_id: str | None) -> tuple[float, bool]:
        if endpoint_id is None:
            return 0.0, False
        try:
            volume = self._endpoint_volume(endpoint_id)
            return float(volume.GetMasterVolumeLevelScalar()), bool(volume.GetMute())
        except _COM_ERRORS as exc:
            self._endpoint_volumes.pop(endpoint_id, None)
            log.debug("Reading endpoint volume failed: %s", exc)
            return 0.0, False

    def _endpoint_volume(self, endpoint_id: str) -> Any:
        volume = self._endpoint_volumes.get(endpoint_id)
        if volume is None:
            device = self._enumerator.GetDevice(endpoint_id)
            volume = device.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None)
            volume = volume.QueryInterface(IAudioEndpointVolume)
            self._endpoint_volumes[endpoint_id] = volume
        return volume

    # ---- changing --------------------------------------------------------------

    def _dry(self, action: str, *args: Any) -> bool:
        if self.dry_run:
            log.info("DRY-RUN %s%r", action, args)
        return self.dry_run

    def _for_sessions(self, endpoint_id: str, pid: int, action: str, apply: Callable[[Any], object]) -> None:
        """Apply to every cached session of (endpoint, pid); sessions that fail are dropped."""
        key = (endpoint_id, pid)
        cached = self._sessions.get(key)
        if not cached:
            log.debug("%s: no session for pid %d on %s", action, pid, endpoint_id)
            return
        alive = []
        for session in cached:
            try:
                apply(session.volume)
                alive.append(session)
            except _COM_ERRORS as exc:
                log.warning("%s failed for pid %d on %s: %s", action, pid, endpoint_id, exc)
        if alive:
            self._sessions[key] = alive
        else:
            self._sessions.pop(key, None)

    def set_session_volume(self, endpoint_id: str, pid: int, level: float) -> None:
        level = _clamp(level)
        if self._dry("set_session_volume", endpoint_id, pid, level):
            return
        self._for_sessions(endpoint_id, pid, "set_session_volume", lambda v: v.SetMasterVolume(level, None))

    def set_session_mute(self, endpoint_id: str, pid: int, muted: bool) -> None:
        if self._dry("set_session_mute", endpoint_id, pid, muted):
            return
        self._for_sessions(endpoint_id, pid, "set_session_mute", lambda v: v.SetMute(bool(muted), None))

    def set_endpoint_volume(self, endpoint_id: str, level: float) -> None:
        level = _clamp(level)
        if self._dry("set_endpoint_volume", endpoint_id, level):
            return
        try:
            self._endpoint_volume(endpoint_id).SetMasterVolumeLevelScalar(level, None)
        except _COM_ERRORS as exc:
            self._endpoint_volumes.pop(endpoint_id, None)
            log.warning("set_endpoint_volume failed for %s: %s", endpoint_id, exc)

    def set_endpoint_mute(self, endpoint_id: str, muted: bool) -> None:
        if self._dry("set_endpoint_mute", endpoint_id, muted):
            return
        try:
            self._endpoint_volume(endpoint_id).SetMute(bool(muted), None)
        except _COM_ERRORS as exc:
            self._endpoint_volumes.pop(endpoint_id, None)
            log.warning("set_endpoint_mute failed for %s: %s", endpoint_id, exc)

    def route_app(self, pid: int, endpoint_id: str | None) -> None:
        """Raises OSError if routing is unavailable or the call fails."""
        if self._dry("route_app", pid, endpoint_id):
            return
        if not self._policy.available:
            raise OSError("Per-app routing is not available on this Windows build")
        self._policy.set_app_endpoint(pid, endpoint_id)

    def set_default_endpoint(self, endpoint_id: str) -> None:
        """Make endpoint_id the Windows default output (console, multimedia and communications)."""
        if self._dry("set_default_endpoint", endpoint_id):
            return
        from pycaw.pycaw import AudioUtilities, ERole

        AudioUtilities.SetDefaultDevice(endpoint_id, [ERole.eConsole, ERole.eMultimedia, ERole.eCommunications])

    def clear_all_routes(self) -> None:
        if self._dry("clear_all_routes"):
            return
        if self._policy.available:
            self._policy.clear_all()

    def close(self) -> None:
        self._sessions.clear()
        self._endpoint_volumes.clear()
        self._enumerator = None
        self._policy.close()

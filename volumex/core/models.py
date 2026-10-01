"""Plain data types shared by the controller, the platform adapters and the UI.

Nothing in here talks to Windows or Qt, so these types are safe to use from
any thread and in tests.
"""
from __future__ import annotations

from dataclasses import dataclass

# App key used for the Windows "System Sounds" session (pid 0).
SYSTEM_SOUNDS_KEY = "system"


@dataclass(frozen=True)
class Endpoint:
    """An active render (playback) endpoint."""

    id: str  # MMDevice endpoint id, e.g. "{0.0.0.00000000}.{5549d092-...}"
    name: str  # friendly name, e.g. "Speakers (Realtek(R) Audio)"
    is_default: bool = False  # Windows default for eConsole/eMultimedia
    is_bus: bool = False  # the virtual cable input that boosted apps are routed to


@dataclass(frozen=True)
class SessionInfo:
    """One Windows audio session: one process playing on one endpoint."""

    endpoint_id: str
    pid: int
    key: str  # app identity, see core.app_identity.app_key()
    exe_path: str  # "" for system sounds
    name: str  # display name, e.g. "Google Chrome"
    active: bool  # AudioSessionStateActive (currently has an open, running stream)
    volume: float  # ISimpleAudioVolume level, 0.0-1.0 (linear amplitude)
    muted: bool


@dataclass(frozen=True)
class AudioSnapshot:
    """Everything the controller needs to know about Windows audio at one instant."""

    endpoints: tuple[Endpoint, ...]
    default_endpoint_id: str | None
    sessions: tuple[SessionInfo, ...]  # sessions on all active render endpoints, expired ones excluded
    endpoint_volume: float  # master volume scalar of the default endpoint, 0.0-1.0
    endpoint_muted: bool

    def endpoint(self, endpoint_id: str | None) -> Endpoint | None:
        for ep in self.endpoints:
            if ep.id == endpoint_id:
                return ep
        return None

    @property
    def bus(self) -> Endpoint | None:
        for ep in self.endpoints:
            if ep.is_bus:
                return ep
        return None


# (endpoint_id, pid) -> peak level 0.0-1.0, as reported by IAudioMeterInformation
PeakMap = dict[tuple[str, int], float]

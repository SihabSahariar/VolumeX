"""Interface every audio backend implements (real Windows or the fake used in tests/demo).

All methods are called from a single worker thread that has COM initialised as
MTA. Implementations may cache COM objects between calls.
"""
from __future__ import annotations

from typing import Protocol

from volumex.core.models import AudioSnapshot, PeakMap


class AudioSystem(Protocol):
    def snapshot(self) -> AudioSnapshot:
        """Enumerate active render endpoints and their sessions (expired sessions and
        sessions of dead processes are skipped). Also refreshes the cache used by peaks()."""

    def peaks(self) -> PeakMap:
        """Peak meter per (endpoint_id, pid) for sessions seen by the last snapshot(). Must be cheap."""

    def set_session_volume(self, endpoint_id: str, pid: int, level: float) -> None:
        """Set ISimpleAudioVolume level (clamped to 0.0-1.0) for that process's session on that endpoint."""

    def set_session_mute(self, endpoint_id: str, pid: int, muted: bool) -> None: ...

    def set_endpoint_volume(self, endpoint_id: str, level: float) -> None:
        """Set IAudioEndpointVolume master scalar (0.0-1.0)."""

    def set_endpoint_mute(self, endpoint_id: str, muted: bool) -> None: ...

    def route_app(self, pid: int, endpoint_id: str | None) -> None:
        """Persist the app's default render endpoint (eConsole + eMultimedia).
        endpoint_id=None resets the app to follow the Windows default."""

    def get_app_route(self, pid: int) -> str | None:
        """The app's persisted render endpoint id, or None if it follows the Windows default."""

    def set_default_endpoint(self, endpoint_id: str) -> None:
        """Make endpoint_id the Windows default output device."""

    def clear_all_routes(self) -> None:
        """Reset every app's persisted endpoint (last-resort cleanup)."""

    def close(self) -> None: ...

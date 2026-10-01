"""In-memory audio system for demo mode, UI development and tests.

Behaves like Windows closely enough for the controller: apps have sessions on
endpoints, routing an app moves its session to another endpoint (except apps
flagged ``follows_routing=False``, which - like Spotify - need a restart), and
peak meters move like real audio.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, replace

from volumex.core.app_identity import app_key
from volumex.core.models import AudioSnapshot, Endpoint, PeakMap, SessionInfo


@dataclass
class _FakeApp:
    pid: int
    exe: str
    name: str
    active: bool
    follows_routing: bool = True
    tempo: float = 1.0


DEMO_APPS = [
    _FakeApp(4120, r"C:\Program Files\Google\Chrome\Application\chrome.exe", "Google Chrome", True, tempo=1.3),
    _FakeApp(5304, r"C:\Users\Demo\AppData\Roaming\Spotify\Spotify.exe", "Spotify", True, follows_routing=False, tempo=0.9),
    _FakeApp(6632, r"C:\Users\Demo\AppData\Local\Discord\app-1.0.9200\Discord.exe", "Discord", True, tempo=2.1),
    _FakeApp(7710, r"C:\Riot Games\VALORANT\live\VALORANT.exe", "VALORANT", False),
    _FakeApp(8012, r"C:\Program Files\VideoLAN\VLC\vlc.exe", "VLC media player", False, tempo=0.7),
    _FakeApp(0, "", "System sounds", False),
]


class FakeAudioSystem:
    def __init__(self, with_bus: bool = True, apps: list[_FakeApp] | None = None) -> None:
        self.endpoints = [
            Endpoint("fake-speakers", "Speakers (Realtek(R) Audio)", is_default=True),
            Endpoint("fake-headphones", "Headphones (WH-1000XM5)"),
        ]
        if with_bus:
            self.endpoints.append(Endpoint("fake-bus", "CABLE Input (VB-Audio Virtual Cable)", is_bus=True))
        self.default_id = "fake-speakers"
        self.endpoint_volume = {ep.id: 0.72 for ep in self.endpoints}
        self.endpoint_mute = {ep.id: False for ep in self.endpoints}
        self.apps = {a.pid: replace(a) for a in (apps if apps is not None else DEMO_APPS)}
        self.routes: dict[int, str | None] = {}
        self._sessions: dict[tuple[str, int], dict] = {}
        for app in self.apps.values():
            self._sessions[(self.default_id, app.pid)] = {"active": app.active, "volume": 1.0, "muted": False}
        self._sessions[(self.default_id, 5304)]["volume"] = 0.6
        self._seed = random.Random(7)
        self.writes: list[tuple] = []  # every mutating call, for tests

    # -- AudioSystem ---------------------------------------------------------------------
    def snapshot(self) -> AudioSnapshot:
        endpoints = tuple(replace(ep, is_default=ep.id == self.default_id) for ep in self.endpoints)
        sessions = []
        for (ep_id, pid), state in self._sessions.items():
            app = self.apps[pid]
            sessions.append(
                SessionInfo(
                    endpoint_id=ep_id,
                    pid=pid,
                    key=app_key(app.exe, pid),
                    exe_path=app.exe,
                    name=app.name,
                    active=state["active"],
                    volume=state["volume"],
                    muted=state["muted"],
                )
            )
        return AudioSnapshot(
            endpoints,
            self.default_id,
            tuple(sessions),
            self.endpoint_volume[self.default_id],
            self.endpoint_mute[self.default_id],
        )

    def peaks(self) -> PeakMap:
        t = time.monotonic()
        result: PeakMap = {}
        for (ep_id, pid), state in self._sessions.items():
            if not state["active"] or state["muted"]:
                result[(ep_id, pid)] = 0.0
                continue
            tempo = self.apps[pid].tempo
            beat = abs(math.sin(t * math.pi * tempo)) ** 3
            body = 0.35 + 0.25 * math.sin(t * 1.7 * tempo + pid) + 0.3 * beat
            noise = self._seed.uniform(-0.06, 0.06)
            result[(ep_id, pid)] = max(0.0, min(1.0, (body + noise) * state["volume"]))
        return result

    def set_session_volume(self, endpoint_id: str, pid: int, level: float) -> None:
        self.writes.append(("volume", endpoint_id, pid, level))
        if (endpoint_id, pid) in self._sessions:
            self._sessions[(endpoint_id, pid)]["volume"] = min(1.0, max(0.0, level))

    def set_session_mute(self, endpoint_id: str, pid: int, muted: bool) -> None:
        self.writes.append(("mute", endpoint_id, pid, muted))
        if (endpoint_id, pid) in self._sessions:
            self._sessions[(endpoint_id, pid)]["muted"] = muted

    def set_endpoint_volume(self, endpoint_id: str, level: float) -> None:
        self.writes.append(("endpoint_volume", endpoint_id, level))
        self.endpoint_volume[endpoint_id] = min(1.0, max(0.0, level))

    def set_endpoint_mute(self, endpoint_id: str, muted: bool) -> None:
        self.writes.append(("endpoint_mute", endpoint_id, muted))
        self.endpoint_mute[endpoint_id] = muted

    def route_app(self, pid: int, endpoint_id: str | None) -> None:
        self.writes.append(("route", pid, endpoint_id))
        if pid not in self.apps:
            raise OSError(f"no such process {pid}")
        self.routes[pid] = endpoint_id
        app = self.apps[pid]
        if not app.follows_routing:
            return
        target = endpoint_id or self.default_id
        current = [key for key in self._sessions if key[1] == pid and self._sessions[key]["active"]]
        was_active = bool(current) or app.active
        for key in current:
            self._sessions[key]["active"] = False
        state = self._sessions.setdefault((target, pid), {"active": False, "volume": 1.0, "muted": False})
        state["active"] = was_active

    def set_default_endpoint(self, endpoint_id: str) -> None:
        self.writes.append(("default", endpoint_id))
        self.set_default(endpoint_id)

    def get_app_route(self, pid: int) -> str | None:
        return self.routes.get(pid)

    def clear_all_routes(self) -> None:
        self.writes.append(("clear_routes",))
        for pid in list(self.routes):
            self.route_app(pid, None)
        self.routes.clear()

    def close(self) -> None:
        pass

    # -- demo helpers --------------------------------------------------------------------
    def set_default(self, endpoint_id: str) -> None:
        self.default_id = endpoint_id
        for pid, app in self.apps.items():
            if self.routes.get(pid):
                continue
            for key in [k for k in self._sessions if k[1] == pid]:
                self._sessions[key]["active"] = False
            self._sessions.setdefault((endpoint_id, pid), {"active": False, "volume": 1.0, "muted": False})
            self._sessions[(endpoint_id, pid)]["active"] = app.active

    def set_playing(self, pid: int, playing: bool) -> None:
        self.apps[pid].active = playing
        for key, state in self._sessions.items():
            if key[1] == pid:
                target = self.routes.get(pid) if self.apps[pid].follows_routing else None
                on_target = key[0] == (target or self.default_id)
                state["active"] = playing and on_target

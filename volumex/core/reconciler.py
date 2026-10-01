"""Turns what the user wants into what Windows and the engine must do (plan §3).

Pure functions only - no Windows, no Qt - so every rule is unit-tested.

Model
-----
* Each app has a wanted gain ``a`` (1.0 = 100%). The master slider above 100%
  is a boost factor ``B >= 1``. The app's effective gain is ``g = a * B``.
* Apps with ``g <= 1`` stay on their normal device; their Windows session volume
  is simply ``g``.
* Apps with ``g > 1`` ("members") are routed to the Boost Bus. The engine applies
  one gain ``G = max(g of members)`` and each member's session volume is ``g / G``
  (the "ratio trick"), so every app still gets its own loudness.

Dip, never spike
----------------
``engine_gain`` is a conservative (never lower than reality) value of the gain
the engine currently applies. Session volumes on the bus are divided by
``max(G, engine_gain)``, so a mismatch while the engine ramps can only make an
app briefly quieter, never louder. Apps moving between devices use the lower of
their two volumes until the move is observed.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

from .models import SYSTEM_SOUNDS_KEY, AudioSnapshot

BOOST_EPSILON = 1e-3

SessionRef = tuple[str, int]  # (endpoint_id, pid)


@dataclass(frozen=True)
class AppTarget:
    gain: float  # wanted loudness, 1.0 = 100%
    muted: bool = False


@dataclass(frozen=True)
class ReconcileInput:
    snapshot: AudioSnapshot
    apps: Mapping[str, AppTarget]  # apps not in here are left untouched
    master_boost: float = 1.0  # B >= 1, the part of the master slider above 100%
    max_gain: float = 3.0  # safety cap on the effective gain of any app
    boost_available: bool = False  # bus present, engine streaming, boost not paused
    engine_gain: float = 1.0  # conservative current engine gain
    sticky_members: frozenset[str] = frozenset()  # kept on the bus while leaving is debounced
    stalled: frozenset[str] = frozenset()  # routed but still playing on the normal device
    excluded_pids: frozenset[int] = frozenset()  # our own processes


@dataclass(frozen=True)
class Plan:
    members: frozenset[str]
    bus_gain: float
    effective: dict[str, float]
    session_volumes: dict[SessionRef, float] = field(default_factory=dict)
    session_mutes: dict[SessionRef, bool] = field(default_factory=dict)


def is_routable(key: str) -> bool:
    return key != SYSTEM_SOUNDS_KEY


def effective_gain(target: AppTarget, master_boost: float, max_gain: float, can_boost: bool) -> float:
    g = max(0.0, target.gain) * max(1.0, master_boost)
    g = min(g, max_gain)
    if not can_boost:
        g = min(g, 1.0)
    return g


def plan(inp: ReconcileInput) -> Plan:
    snap = inp.snapshot
    bus_ids = {ep.id for ep in snap.endpoints if ep.is_bus}
    sessions = [s for s in snap.sessions if s.pid not in inp.excluded_pids and s.key in inp.apps]
    present = {s.key for s in sessions}

    effective: dict[str, float] = {}
    for key in present:
        can_boost = inp.boost_available and is_routable(key)
        effective[key] = effective_gain(inp.apps[key], inp.master_boost, inp.max_gain, can_boost)

    members: set[str] = set()
    if inp.boost_available:
        members = {k for k, g in effective.items() if g > 1.0 + BOOST_EPSILON}
        members |= {k for k in inp.sticky_members if k in present and is_routable(k)}
    for key in effective:
        if key not in members:
            effective[key] = min(effective[key], 1.0)  # within BOOST_EPSILON of 100%: plays at exactly 100%

    bus_gain = max([1.0] + [effective[k] for k in members])
    divisor = max(bus_gain, inp.engine_gain, 1.0)

    active_on_bus = {s.key for s in sessions if s.active and s.endpoint_id in bus_ids}

    volumes: dict[SessionRef, float] = {}
    mutes: dict[SessionRef, bool] = {}
    for s in sessions:
        g = effective[s.key]
        if s.endpoint_id in bus_ids:
            vol = g / divisor
        elif s.key in members and s.key not in inp.stalled:
            vol = g / divisor  # joining: quieter until the move to the bus is observed
        elif s.key in active_on_bus:
            vol = g / divisor  # leaving: stays quiet until it has left the bus
        else:
            vol = min(g, 1.0)
        ref = (s.endpoint_id, s.pid)
        volumes[ref] = min(1.0, max(0.0, vol))
        mutes[ref] = inp.apps[s.key].muted

    return Plan(
        members=frozenset(members),
        bus_gain=bus_gain,
        effective=effective,
        session_volumes=volumes,
        session_mutes=mutes,
    )


def split_master(master: float) -> tuple[float, float]:
    """Master slider value -> (Windows endpoint volume, boost factor B)."""
    master = max(0.0, master)
    return min(master, 1.0), max(master, 1.0)


def gain_to_db(gain: float) -> float:
    return 20.0 * math.log10(gain) if gain > 1e-6 else float("-inf")

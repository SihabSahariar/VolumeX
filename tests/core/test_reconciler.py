from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from volumex.core.models import SYSTEM_SOUNDS_KEY, AudioSnapshot, Endpoint, SessionInfo
from volumex.core.reconciler import AppTarget, ReconcileInput, plan, split_master

SPK = Endpoint("spk", "Speakers", is_default=True)
BUS = Endpoint("bus", "CABLE Input (VB-Audio Virtual Cable)", is_bus=True)


def session(key: str, pid: int, endpoint: Endpoint = SPK, active: bool = True, volume: float = 1.0) -> SessionInfo:
    return SessionInfo(endpoint.id, pid, key, f"C:/{key}.exe", key, active, volume, False)


def snapshot(*sessions: SessionInfo) -> AudioSnapshot:
    return AudioSnapshot((SPK, BUS), SPK.id, tuple(sessions), 1.0, False)


def test_plan_matches_design_example():
    snap = snapshot(session("chrome", 1, BUS), session("vlc", 2, BUS), session("discord", 3))
    apps = {"chrome": AppTarget(3.0), "vlc": AppTarget(1.5), "discord": AppTarget(0.9)}
    p = plan(ReconcileInput(snap, apps, boost_available=True, engine_gain=3.0))

    assert p.members == {"chrome", "vlc"}
    assert p.bus_gain == pytest.approx(3.0)
    assert p.session_volumes[("bus", 1)] == pytest.approx(1.0)
    assert p.session_volumes[("bus", 2)] == pytest.approx(0.5)
    assert p.session_volumes[("spk", 3)] == pytest.approx(0.9)


def test_without_boost_everything_is_capped_at_100_percent():
    snap = snapshot(session("chrome", 1), session("vlc", 2))
    apps = {"chrome": AppTarget(3.0), "vlc": AppTarget(0.4)}
    p = plan(ReconcileInput(snap, apps, boost_available=False))

    assert p.members == frozenset()
    assert p.bus_gain == 1.0
    assert p.session_volumes[("spk", 1)] == pytest.approx(1.0)
    assert p.session_volumes[("spk", 2)] == pytest.approx(0.4)


def test_master_boost_multiplies_every_app():
    snap = snapshot(session("a", 1), session("b", 2))
    apps = {"a": AppTarget(1.0), "b": AppTarget(0.5)}
    p = plan(ReconcileInput(snap, apps, master_boost=1.5, boost_available=True))

    assert p.members == {"a"}  # b: 0.5 * 1.5 = 0.75 stays direct
    assert p.effective["a"] == pytest.approx(1.5)
    assert p.session_volumes[("spk", 2)] == pytest.approx(0.75)


def test_joining_app_is_quieter_until_it_moves():
    # chrome wants the bus but is still on the speakers; vlc already drives G to 3
    snap = snapshot(session("chrome", 1), session("vlc", 2, BUS))
    apps = {"chrome": AppTarget(2.0), "vlc": AppTarget(3.0)}
    p = plan(ReconcileInput(snap, apps, boost_available=True, engine_gain=1.0))
    assert p.members == {"chrome", "vlc"}
    assert p.session_volumes[("spk", 1)] == pytest.approx(2.0 / 3.0)


def test_stalled_app_plays_at_most_100_percent_directly():
    snap = snapshot(session("spotify", 1))
    inp = ReconcileInput(snap, {"spotify": AppTarget(2.0)}, boost_available=True, stalled=frozenset({"spotify"}))
    assert plan(inp).session_volumes[("spk", 1)] == pytest.approx(1.0)


def test_leaving_app_stays_quiet_until_it_left_the_bus():
    snap = snapshot(session("vlc", 1, BUS, active=True), session("vlc", 1, SPK, active=False))
    p = plan(ReconcileInput(snap, {"vlc": AppTarget(0.8)}, boost_available=True, engine_gain=2.0))
    assert p.members == frozenset()
    assert p.session_volumes[("spk", 1)] == pytest.approx(0.4)
    assert p.session_volumes[("bus", 1)] == pytest.approx(0.4)


def test_system_sounds_and_excluded_pids_are_never_routed():
    snap = snapshot(session(SYSTEM_SOUNDS_KEY, 0), session("engine", 99))
    apps = {SYSTEM_SOUNDS_KEY: AppTarget(3.0), "engine": AppTarget(3.0)}
    p = plan(ReconcileInput(snap, apps, boost_available=True, excluded_pids=frozenset({99})))
    assert p.members == frozenset()
    assert ("spk", 99) not in p.session_volumes
    assert p.session_volumes[("spk", 0)] == pytest.approx(1.0)


def test_max_gain_caps_effective_gain():
    snap = snapshot(session("a", 1, BUS))
    p = plan(ReconcileInput(snap, {"a": AppTarget(3.0)}, master_boost=3.0, max_gain=3.0, boost_available=True))
    assert p.bus_gain == pytest.approx(3.0)


def test_split_master():
    assert split_master(0.4) == (0.4, 1.0)
    assert split_master(1.0) == (1.0, 1.0)
    assert split_master(2.5) == (1.0, 2.5)


# ---- properties -------------------------------------------------------------

app_keys = st.sampled_from(["a", "b", "c", "d", SYSTEM_SOUNDS_KEY])


@st.composite
def scenarios(draw):
    keys = draw(st.lists(app_keys, min_size=1, max_size=5, unique=True))
    apps = {k: AppTarget(draw(st.floats(0.0, 5.0)), draw(st.booleans())) for k in keys}
    sessions = []
    for pid, key in enumerate(keys, start=1):
        for ep in draw(st.lists(st.sampled_from([SPK, BUS]), min_size=1, max_size=2, unique=True)):
            sessions.append(session(key, pid, ep, active=draw(st.booleans())))
    return ReconcileInput(
        snapshot(*sessions),
        apps,
        master_boost=draw(st.floats(1.0, 3.0)),
        max_gain=draw(st.sampled_from([3.0, 5.0])),
        boost_available=draw(st.booleans()),
        engine_gain=draw(st.floats(1.0, 6.0)),
        sticky_members=frozenset(draw(st.lists(app_keys, max_size=2))),
        stalled=frozenset(draw(st.lists(app_keys, max_size=2))),
    )


@settings(max_examples=400)
@given(scenarios())
def test_never_louder_than_wanted(inp: ReconcileInput):
    p = plan(inp)
    for s in inp.snapshot.sessions:
        vol = p.session_volumes[(s.endpoint_id, s.pid)]
        assert 0.0 <= vol <= 1.0
        g = p.effective[s.key]
        if s.endpoint_id == BUS.id:
            # whatever the engine is doing right now or is heading to
            for engine in (inp.engine_gain, p.bus_gain):
                assert vol * engine <= g + 1e-9
        else:
            assert vol <= g + 1e-9


@settings(max_examples=400)
@given(scenarios())
def test_steady_state_is_exact(inp: ReconcileInput):
    # Steady state: nothing in transition (no sticky or stalled apps), engine already at the bus gain,
    # every member only on the bus, every other app only on the speakers.
    p = plan(ReconcileInput(inp.snapshot, inp.apps, master_boost=inp.master_boost, max_gain=inp.max_gain,
                            boost_available=inp.boost_available))
    sessions = tuple(
        session(key, pid, BUS if key in p.members else SPK)
        for pid, key in enumerate(sorted({s.key for s in inp.snapshot.sessions}), start=1)
    )
    steady = ReconcileInput(
        snapshot(*sessions),
        inp.apps,
        master_boost=inp.master_boost,
        max_gain=inp.max_gain,
        boost_available=inp.boost_available,
        engine_gain=p.bus_gain,
    )
    q = plan(steady)
    for s in sessions:
        heard = q.session_volumes[(s.endpoint_id, s.pid)] * (q.bus_gain if s.endpoint_id == BUS.id else 1.0)
        assert heard == pytest.approx(q.effective[s.key], abs=1e-9)
        if s.key in q.members:
            assert q.effective[s.key] > 1.0

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from volumex.engine.dsp import (
    DriftController,
    GainRamp,
    LookaheadLimiter,
    StreamResampler,
    _sliding_max,
    db_to_linear,
)

FS = 48000


def run_blocks(proc, x: np.ndarray, sizes: list[int]) -> np.ndarray:
    """Feed x through proc(block) in blocks of the given sizes (cycled until x is used up)."""
    out, pos, i = [], 0, 0
    while pos < x.shape[0]:
        n = sizes[i % len(sizes)]
        out.append(proc(x[pos : pos + n]))
        pos += n
        i += 1
    return np.concatenate(out)


def make_signal(kind: str, n: int, channels: int, rng: np.random.Generator) -> np.ndarray:
    if kind == "noise":
        x = rng.standard_normal((n, channels)) * 0.5
    elif kind == "square":
        half = int(rng.integers(1, 1000))
        wave = ((np.arange(n) // half) % 2) * 2.0 - 1.0
        x = wave[:, None] * rng.uniform(0.2, 1.0, channels)
    elif kind == "impulses":
        x = np.zeros((n, channels))
        idx = rng.integers(0, n, size=max(1, n // 200))
        x[idx] = rng.uniform(-1.0, 1.0, (idx.size, channels))
        x[idx[: idx.size // 2] // 2] = 1.0  # some full-scale clusters
    else:  # abrupt sine bursts
        t = np.arange(n) / FS
        env = (rng.random(n // 256 + 1) > 0.5).repeat(256)[:n]
        x = (np.sin(2 * np.pi * rng.uniform(50, 15000) * t) * env)[:, None].repeat(channels, axis=1)
    return x.astype(np.float32)


# -- sliding max ---------------------------------------------------------------------------


@pytest.mark.parametrize("width", [1, 2, 3, 7, 8, 9, 144, 145, 300])
def test_sliding_max_matches_naive(width):
    a = np.random.default_rng(width).random(400 + width - 1)
    expected = np.array([a[i : i + width].max() for i in range(400)])
    assert np.array_equal(_sliding_max(a, width), expected)


# -- limiter -------------------------------------------------------------------------------


@settings(max_examples=120, deadline=None)
@given(
    seed=st.integers(0, 2**32 - 1),
    kind=st.sampled_from(["noise", "square", "impulses", "bursts"]),
    gain=st.floats(0.1, 10.0),
    ceiling_db=st.floats(-12.0, 0.0),
    lookahead_ms=st.floats(0.0, 10.0),
    release_ms=st.floats(1.0, 500.0),
    sizes=st.lists(st.integers(1, 1500), min_size=1, max_size=8),
    channels=st.integers(1, 3),
)
def test_limiter_never_exceeds_ceiling(seed, kind, gain, ceiling_db, lookahead_ms, release_ms, sizes, channels):
    rng = np.random.default_rng(seed)
    x = make_signal(kind, 6000, channels, rng) * np.float32(gain)
    lim = LookaheadLimiter(FS, channels, ceiling_db, lookahead_ms, release_ms)
    y = run_blocks(lim.process, x, sizes)
    assert y.dtype == np.float32
    assert y.shape == x.shape
    assert np.abs(y).max() <= np.float32(lim.ceiling)
    assert lim.ceiling == pytest.approx(db_to_linear(ceiling_db), rel=1e-6)
    assert lim.clip_count == 0  # the algorithm itself held the ceiling, not the safety clip


@settings(max_examples=30, deadline=None)
@given(seed=st.integers(0, 2**32 - 1), sizes=st.lists(st.integers(1, 2000), min_size=1, max_size=6))
def test_limiter_output_independent_of_block_size(seed, sizes):
    rng = np.random.default_rng(seed)
    x = make_signal("noise", 8000, 2, rng) * np.float32(4.0)
    whole = LookaheadLimiter(FS, 2).process(x)
    blocked = run_blocks(LookaheadLimiter(FS, 2).process, x, sizes)
    np.testing.assert_allclose(blocked, whole, atol=1e-6)


@pytest.mark.parametrize("lookahead_ms, expected", [(3.0, 144), (0.0, 0), (5.0, 240)])
def test_latency_equals_lookahead_and_quiet_audio_is_exact(lookahead_ms, expected):
    lim = LookaheadLimiter(FS, 2, ceiling_db=-1.0, lookahead_ms=lookahead_ms)
    assert lim.latency_samples == expected
    x = (np.random.default_rng(1).uniform(-0.8, 0.8, (5000, 2))).astype(np.float32)  # below -1 dBFS
    y = run_blocks(lim.process, x, [480, 1, 333])
    assert np.array_equal(y[expected:], x[: x.shape[0] - expected])
    assert not y[:expected].any()
    assert lim.last_gain_reduction_db == 0.0


def test_gain_is_smooth():
    L = 145  # 3 ms at 48 kHz, plus one
    level = np.concatenate([np.full(2000, 0.1), np.full(3000, 5.0), np.full(3000, 0.2), np.full(50, 3.0), np.full(24000, 0.3)])
    x = level[:, None].astype(np.float32)
    lim = LookaheadLimiter(FS, 1, ceiling_db=-1.0, lookahead_ms=3.0, release_ms=50.0)
    y = run_blocks(lim.process, x, [480, 17, 1024])[:, 0]
    d = lim.latency_samples
    gain = y[d:] / x[: x.shape[0] - d, 0]  # positive DC input: output / delayed input is the gain
    assert np.abs(np.diff(gain)).max() <= 1.0 / L + 1e-6  # the averaging stage bounds every step
    assert gain.max() <= 1.0 + 1e-7
    assert np.abs(y).max() <= np.float32(lim.ceiling)
    assert lim.last_gain_reduction_db == pytest.approx(0.0, abs=1e-3)  # released by the end


def test_release_returns_gain_to_unity():
    release_ms = 80.0
    x = np.concatenate([np.full(1000, 4.0), np.full(FS, 0.1)])[:, None].astype(np.float32)
    lim = LookaheadLimiter(FS, 1, release_ms=release_ms)
    y = run_blocks(lim.process, x, [480])[:, 0]
    d = lim.latency_samples
    gain = y[d:] / x[: x.shape[0] - d, 0]
    quiet = gain[1000:]  # from the first quiet sample at the output
    assert quiet[0] < 0.5
    assert np.all(np.diff(quiet) >= -1e-7)  # recovery never dips
    five_tau = 1000 + int(5 * release_ms / 1000 * FS) + 2 * d
    assert gain[five_tau:].min() > 0.99
    assert gain[-1] == pytest.approx(1.0, abs=1e-5)  # e**-12.5 of the reduction left after 1 s


def test_disabled_passes_through_with_same_delay_and_clips_at_0dbfs():
    x = (np.random.default_rng(2).uniform(-3.0, 3.0, (4000, 2))).astype(np.float32)
    lim = LookaheadLimiter(FS, 2, lookahead_ms=3.0)
    lim.set_params(enabled=False)
    y = run_blocks(lim.process, x, [480, 77])
    d = lim.latency_samples
    assert d == 144
    np.testing.assert_array_equal(y[d:], np.clip(x[: x.shape[0] - d], -1.0, 1.0))
    assert lim.last_gain_reduction_db == 0.0


def test_toggling_enabled_keeps_the_delay_line_continuous():
    ramp = np.linspace(-0.5, 0.5, 3000, dtype=np.float32)[:, None]
    lim = LookaheadLimiter(FS, 1)
    a = lim.process(ramp[:1000])
    lim.enabled = False
    b = lim.process(ramp[1000:2000])
    lim.enabled = True
    c = lim.process(ramp[2000:])
    y = np.concatenate([a, b, c])[:, 0]
    d = lim.latency_samples
    np.testing.assert_array_equal(y[d:], ramp[: 3000 - d, 0])


def test_set_params_updates_ceiling_and_latency():
    lim = LookaheadLimiter(FS, 2)
    lim.set_params(ceiling_db=-6.0)
    y = lim.process(np.full((4000, 2), 0.9, dtype=np.float32))
    assert np.abs(y).max() <= np.float32(db_to_linear(-6.0))
    assert lim.last_gain_reduction_db == pytest.approx(20 * np.log10(0.9 / db_to_linear(-6.0)), abs=0.01)
    lim.set_params(lookahead_ms=5.0)
    assert lim.latency_samples == 240


# -- gain ramp -----------------------------------------------------------------------------


def test_gain_ramp_reaches_target_within_ramp_time_without_steps():
    ramp = GainRamp(FS, 1.0)
    ramp.set_target(2.0, ramp_ms=10.0)  # 480 samples
    g = run_blocks(ramp.process, np.ones((2000, 1), dtype=np.float32), [100, 7, 373, 200])[:, 0]
    assert g[479] == np.float32(2.0)
    assert np.all(g[480:] == np.float32(2.0))
    steps = np.diff(np.concatenate([[1.0], g]))
    assert np.all(steps[:480] > 0)
    assert np.abs(steps).max() <= 1.0 / 480 + 1e-6
    assert not ramp.ramping and ramp.current == 2.0


def test_gain_ramp_retarget_mid_ramp_is_continuous():
    ramp = GainRamp(FS, 1.0)
    ramp.set_target(3.0, ramp_ms=10.0)
    a = ramp.process(np.ones((240, 1), dtype=np.float32))
    ramp.set_target(0.5, ramp_ms=5.0)
    b = ramp.process(np.ones((1000, 1), dtype=np.float32))
    g = np.concatenate([a, b])[:, 0]
    steps = np.abs(np.diff(g))
    assert steps.max() <= (2.0 - 0.5) / 240 + 1e-5  # at most the steeper of the two slopes
    assert g[-1] == np.float32(0.5)


def test_gain_ramp_zero_ramp_and_unity():
    ramp = GainRamp(FS)
    block = np.full((10, 2), 0.3, dtype=np.float32)
    assert ramp.process(block) is block  # unity gain is free
    ramp.set_target(0.0, ramp_ms=0.0)
    assert not ramp.process(block).any()


# -- resampler -----------------------------------------------------------------------------


def sine(freq: float, rate: float, n: int, amp: float = 0.5) -> np.ndarray:
    return (amp * np.sin(2 * np.pi * freq * np.arange(n) / rate)).astype(np.float32)[:, None].repeat(2, axis=1)


def test_resampler_is_continuous_across_calls():
    ratio = 48000 / 44100
    x = sine(1000.0, 44100, 44100)
    whole = StreamResampler(2).process(x, ratio)
    rng = np.random.default_rng(3)
    sizes = [int(s) for s in rng.integers(1, 900, size=200)]
    r = StreamResampler(2)
    blocked = run_blocks(lambda b: r.process(b, ratio), x, sizes)
    n = min(whole.shape[0], blocked.shape[0])
    np.testing.assert_allclose(blocked[:n], whole[:n], atol=1e-5)
    # a clean 1 kHz sine at 48 kHz: the second difference is bounded by A*(2*pi*f/fs)^2
    body = blocked[200:-200, 0]
    assert np.abs(np.diff(body, 2)).max() < 0.5 * (2 * np.pi * 1000 / 48000) ** 2 * 1.1


def test_resampler_output_length_44100_to_48000():
    r = StreamResampler(2)
    total = sum(r.process(np.zeros((441, 2), np.float32), 48000 / 44100).shape[0] for _ in range(100))
    assert abs(total - 48000) <= 64  # libsamplerate keeps a few frames in flight


def test_resampler_variable_ratio():
    r = StreamResampler(2)
    x = sine(440.0, 48000, 48000 * 2)
    ratios = [1.0 + 200e-6 * (1 if i % 2 else -1) * (i % 7) / 6 for i in range(200)]
    out, expected = [], 0.0
    for i, ratio in enumerate(ratios):
        block = x[i * 480 : (i + 1) * 480]
        out.append(r.process(block, ratio))
        expected += block.shape[0] * ratio
    y = np.concatenate(out)
    assert abs(y.shape[0] - expected) <= 64
    body = y[200:-200, 0]
    assert np.abs(np.diff(body, 2)).max() < 0.5 * (2 * np.pi * 440 / 48000) ** 2 * 1.1
    # a big jump glides over a few calls (libsamplerate interpolates the ratio), then holds
    counts = [r.process(x[i * 4800 : (i + 1) * 4800], 2.0).shape[0] for i in range(6)]
    assert 4800 < counts[0] < 9600
    assert counts[-1] == pytest.approx(9600, abs=2)


# -- drift controller ----------------------------------------------------------------------


def test_drift_controller_direction_and_clamp():
    too_full = DriftController(target_frames=1000, rate=48000, max_ppm=500)
    for _ in range(1000):
        too_full.update(3000, 0.01)
    assert too_full.ppm == pytest.approx(-500.0)  # consume faster: lower out/in ratio
    too_empty = DriftController(target_frames=1000, rate=48000, max_ppm=500)
    for _ in range(1000):
        too_empty.update(0, 0.01)
    assert too_empty.ppm == pytest.approx(500.0)
    on_target = DriftController(target_frames=1000, rate=48000)
    on_target.update(1000, 0.01)
    assert on_target.factor == 1.0

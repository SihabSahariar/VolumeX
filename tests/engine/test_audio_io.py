"""BusPipeline, bridges and device lookup, all without opening any audio device."""
from __future__ import annotations

import time

import numpy as np
import pytest

from volumex.engine.audio_io import (
    BusBridge,
    BusPipeline,
    DeviceNotFoundError,
    FakeBridge,
    RingBuffer,
    find_wasapi_device,
    write_output,
)
from volumex.engine.dsp import LimiterSettings

# -- ring buffer / channel mapping ---------------------------------------------------------


def frames(start: int, n: int) -> np.ndarray:
    v = np.arange(start, start + n, dtype=np.float32)
    return np.stack([v, -v], axis=1)


def test_ring_buffer_wraps_and_drops_oldest():
    ring = RingBuffer(10)
    assert ring.write(frames(0, 7)) == 0
    np.testing.assert_array_equal(ring.read(5), frames(0, 5))
    assert ring.write(frames(7, 6)) == 0  # wraps around the end
    np.testing.assert_array_equal(ring.read(100), frames(5, 8))
    assert ring.write(frames(0, 13)) == 3  # overflow: the 3 oldest are dropped
    np.testing.assert_array_equal(ring.read(10), frames(3, 10))
    assert ring.available == 0 and ring.read(4).shape == (0, 2)


def test_ring_buffer_broadcasts_mono_and_discards():
    ring = RingBuffer(8)
    ring.write(np.array([[1.0], [2.0], [3.0]], dtype=np.float32))
    assert ring.discard(1) == 1
    np.testing.assert_array_equal(ring.read(2), [[2.0, 2.0], [3.0, 3.0]])


@pytest.mark.parametrize("channels", [1, 2, 6])
def test_write_output_channel_mapping(channels):
    stereo = np.array([[0.2, 0.4], [-0.5, 0.1]], dtype=np.float32)
    out = np.full((2, channels), 9.0, dtype=np.float32)
    write_output(out, stereo)
    if channels == 1:
        np.testing.assert_allclose(out[:, 0], [0.3, -0.2], rtol=1e-6)
    else:
        np.testing.assert_array_equal(out[:, :2], stereo)
        assert not out[:, 2:].any()


# -- pipeline ------------------------------------------------------------------------------


def run(p: BusPipeline, block: np.ndarray, count: int, out_n: int = 480) -> np.ndarray:
    ys = []
    for _ in range(count):
        p.push(block)
        ys.append(p.render(out_n))
    return np.concatenate(ys)


def test_pipeline_primes_then_applies_gain():
    p = BusPipeline(48000, 48000, target_latency_ms=10.0, gain=2.0)
    p.expect_blocks(480, 480)
    y = run(p, np.full((480, 2), 0.2, dtype=np.float32), 50)
    first_sound = int(np.argmax(np.abs(y[:, 0]) > 1e-3))
    assert first_sound >= 480  # silent until the ring holds the target
    np.testing.assert_allclose(y[-2000:], 0.4, atol=2e-3)
    assert p.underruns == 0 and p.overruns == 0
    assert p.latency_ms == pytest.approx(1000 * (480 + 480 + 48) / 48000 + 3.0, abs=0.1)


@pytest.mark.parametrize(
    "block, expected",
    [
        (np.full((441, 1), 0.3, dtype=np.float32), (0.3, 0.3)),  # mono capture -> both sides
        (np.tile(np.array([0.1, 0.2, 0.9, 0.9, 0.9, 0.9], dtype=np.float32), (441, 1)), (0.1, 0.2)),  # 5.1
    ],
)
def test_pipeline_capture_channel_mapping_with_rate_conversion(block, expected):
    p = BusPipeline(44100, 48000)
    y = run(p, block, 60)
    np.testing.assert_allclose(y[-2000:, 0], expected[0], atol=2e-3)
    np.testing.assert_allclose(y[-2000:, 1], expected[1], atol=2e-3)
    assert p.underruns == 0


def test_pipeline_underrun_outputs_silence_and_reprimes():
    p = BusPipeline(48000, 48000, target_latency_ms=10.0)
    block = np.full((480, 2), 0.5, dtype=np.float32)
    run(p, block, 20)
    for _ in range(4):  # input stops
        p.render(480)
    assert p.underruns == 1  # counted once, then it waits for the target again
    y = p.render(480)
    assert np.abs(y).max() < 0.5  # tail of the limiter delay line, then silence
    assert not p.render(480).any()
    y = run(p, block, 20)
    assert p.underruns == 1
    np.testing.assert_allclose(y[-480:], 0.5, atol=2e-3)


def test_pipeline_overrun_resyncs_to_target():
    p = BusPipeline(48000, 48000, target_latency_ms=10.0)
    block = np.full((480, 2), 0.1, dtype=np.float32)
    run(p, block, 10)
    for _ in range(40):  # render side stalls
        p.push(block)
    assert p.overruns >= 1
    assert p._ring.available <= 2 * p.target_frames + 0.05 * 48000 + 480


def test_pipeline_meters_and_queued_parameters():
    p = BusPipeline(48000, 48000, gain=1.0)
    sig = np.sin(np.arange(480) * 2 * np.pi / 48)[:, None].astype(np.float32) * np.array([0.5, 0.25], np.float32)
    run(p, sig, 20)
    pl, pr, gr = p.take_meters()
    assert pl == pytest.approx(0.5, abs=0.01) and pr == pytest.approx(0.25, abs=0.01) and gr == 0.0
    assert p.take_meters() == (0.0, 0.0, 0.0)  # reset by reading
    p.set_gain(4.0, 10.0)
    p.set_limiter(LimiterSettings(ceiling_db=-3.0))
    run(p, sig, 20)
    pl, pr, gr = p.take_meters()
    assert pl <= np.float32(10 ** (-3 / 20)) and gr > 3.0


@pytest.mark.parametrize(
    "in_rate, out_rate, ppm, in_block, out_block",
    [
        (48000, 48000, 100.0, 480, 480),
        (48000, 48000, -100.0, 480, 144),
        (44100, 48000, 100.0, 441, 480),
    ],
)
def test_drift_controller_converges(in_rate, out_rate, ppm, in_block, out_block):
    """Producer and consumer on independent clocks, simulated in virtual time."""
    p = BusPipeline(in_rate, out_rate, target_latency_ms=10.0)
    true_in_rate = in_rate * (1 + ppm * 1e-6)
    rng = np.random.default_rng(0)
    block = (0.1 * rng.standard_normal((in_block, 2))).astype(np.float32)
    t_in, t_out, seconds = 0.0, 0.0037, 120.0
    tail = []  # (smoothed fill, ppm) over the last 30 s
    while t_out < seconds:
        if t_in <= t_out:
            p.push(block, now=t_in + rng.uniform(0, 0.0005))  # callback jitter
            t_in += in_block / true_in_rate
        else:
            p.render(out_block, now=t_out + rng.uniform(0, 0.0005))
            t_out += out_block / out_rate
            if t_out > seconds - 30:
                tail.append((p.drift.fill, p.drift.ppm))
    fill, correction = np.array(tail).T
    assert p.underruns == 0 and p.overruns == 0
    assert correction.mean() == pytest.approx(-ppm, abs=3.0)  # ratio trimmed by exactly the drift
    assert np.abs(fill - p.target_frames).max() < 0.001 * in_rate  # within 1 ms of target


# -- device lookup -------------------------------------------------------------------------

HOSTAPIS = [{"name": "MME"}, {"name": "Windows WASAPI"}]
DEVICES = [
    {"index": 0, "name": "CABLE Output (VB-Audio Virtual Cable)", "hostapi": 0, "max_input_channels": 2, "max_output_channels": 0},
    {"index": 1, "name": "Speakers (Realtek(R) Audio)", "hostapi": 1, "max_input_channels": 0, "max_output_channels": 2},
    {"index": 2, "name": "CABLE Output (VB-Audio Virtual Cable)", "hostapi": 1, "max_input_channels": 2, "max_output_channels": 0},
    {"index": 3, "name": "CABLE Input (VB-Audio Virtual Cable)", "hostapi": 1, "max_input_channels": 0, "max_output_channels": 2},
    {"index": 4, "name": "Speakers (Realtek(R) Audio) 2", "hostapi": 1, "max_input_channels": 0, "max_output_channels": 8},
]


def test_find_wasapi_device_exact_then_contains():
    find = lambda name, kind: find_wasapi_device(name, kind, DEVICES, HOSTAPIS)["index"]  # noqa: E731
    assert find("CABLE Output (VB-Audio Virtual Cable)", "input") == 2  # WASAPI only, not MME
    assert find("Speakers (Realtek(R) Audio) 2", "output") == 4  # exact wins over contains
    assert find("speakers (realtek", "output") == 1  # case-insensitive contains
    assert find("CABLE", "output") == 3  # kind filters the candidates
    with pytest.raises(DeviceNotFoundError):
        find_wasapi_device("CABLE Output", "output", DEVICES, HOSTAPIS)
    with pytest.raises(DeviceNotFoundError):
        find_wasapi_device("", "input", DEVICES, HOSTAPIS)
    with pytest.raises(DeviceNotFoundError):
        find_wasapi_device("Speakers", "output", DEVICES, [{"name": "MME"}])


# -- bridges -------------------------------------------------------------------------------


def test_bus_bridge_callbacks_without_devices():
    """Drive BusBridge's stream callbacks with plain arrays (no PortAudio stream)."""
    errors = []
    bridge = BusBridge(on_error=lambda code, msg: errors.append(code))
    bridge.pipeline = BusPipeline(48000, 48000, gain=1.0)
    indata = np.zeros((480, 8), dtype=np.float32)
    indata[:, 0], indata[:, 1] = 0.25, -0.25
    outdata = np.zeros((480, 6), dtype=np.float32)
    for _ in range(30):
        bridge._in_callback(indata, 480, None, 0)
        bridge._out_callback(outdata, 480, None, 0)
    np.testing.assert_allclose(outdata[:, 0], 0.25, atol=2e-3)
    np.testing.assert_allclose(outdata[:, 1], -0.25, atol=2e-3)
    assert not outdata[:, 2:].any()
    mono = np.zeros((480, 1), dtype=np.float32)
    bridge._out_callback(mono, 480, None, 0)
    assert np.abs(mono).max() < 2e-3  # L and R cancel in the average

    bridge._last_in = bridge._last_out = time.monotonic() - 5.0
    bridge.poll()
    bridge.poll()
    assert errors == ["stream_failed"]  # stalled output reported once


def test_fake_bridge_streams_in_real_time():
    bridge = FakeBridge()
    with pytest.raises(DeviceNotFoundError):
        bridge.start()  # not configured
    bridge.configure("CABLE Output", "Speakers", target_latency_ms=10.0)
    bridge.set_gain(5.0, 0.0)
    bridge.start()
    try:
        state = bridge.state()
        assert state["streaming"] and state["in_rate"] == 48000 and state["out_rate"] == 48000
        assert state["latency_ms"] == pytest.approx(21.0 + 3.0 + 20.0, abs=0.1)
        time.sleep(0.3)
        m = bridge.meters()
        assert m["peak"][0] == pytest.approx(10 ** (-1 / 20), abs=1e-4)  # 0.25 * 5 limited to -1 dBFS
        assert m["gr_db"] == pytest.approx(20 * np.log10(1.25 / 10 ** (-1 / 20)), abs=0.05)
        assert m["underruns"] == 0 and m["overruns"] == 0
    finally:
        bridge.stop()
    assert bridge.state()["streaming"] is False

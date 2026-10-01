"""Real-time DSP blocks for the engine: gain ramp, look-ahead limiter, resampler, drift loop.

Pure numpy (plus libsamplerate for the resampler); nothing here touches a device.
Every class keeps its state between calls, so audio can be fed in blocks of any
size and the result matches processing the whole signal at once.
Audio blocks are float32 arrays of shape (frames, channels).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import samplerate


def db_to_linear(db: float) -> float:
    return 10.0 ** (db / 20.0)


def linear_to_db(value: float, floor_db: float = -120.0) -> float:
    return 20.0 * math.log10(value) if value > db_to_linear(floor_db) else floor_db


@dataclass(frozen=True)
class LimiterSettings:
    enabled: bool = True
    ceiling_db: float = -1.0
    release_ms: float = 80.0
    lookahead_ms: float = 3.0


class GainRamp:
    """Linear gain whose changes are spread over a per-sample linear ramp (no zipper noise)."""

    def __init__(self, sample_rate: float, gain: float = 1.0) -> None:
        self.sample_rate = float(sample_rate)
        self.current = float(gain)  # gain applied to the last processed sample
        self.target = float(gain)
        self._step = 0.0
        self._remaining = 0  # samples left in the current ramp

    @property
    def ramping(self) -> bool:
        return self._remaining > 0

    def set_target(self, gain: float, ramp_ms: float = 30.0) -> None:
        """Move from the current gain to `gain` over `ramp_ms` (0 = jump immediately)."""
        self.target = float(gain)
        n = int(round(max(0.0, ramp_ms) * self.sample_rate / 1000.0))
        if n <= 0 or self.target == self.current:
            self.current = self.target
            self._remaining = 0
        else:
            self._remaining = n
            self._step = (self.target - self.current) / n

    def process(self, block: np.ndarray) -> np.ndarray:
        if self._remaining == 0:
            if self.current == 1.0:
                return block
            return block * np.float32(self.current)
        n = block.shape[0]
        k = min(n, self._remaining)
        g = np.full(n, self.target, dtype=np.float32)
        g[:k] = self.current + self._step * np.arange(1, k + 1)
        self._remaining -= k
        if self._remaining == 0:
            g[k - 1] = self.target  # land exactly on the target
            self.current = self.target
        else:
            self.current += self._step * k
        return block * g[:, None]


def _sliding_max(a: np.ndarray, width: int) -> np.ndarray:
    """out[i] = max(a[i : i + width]) for every full window, in log2(width) numpy passes."""
    n = a.shape[0] - width + 1
    m = a
    w = 1
    while 2 * w <= width:
        m = np.maximum(m[:-w], m[w:])  # m[i] = max(a[i : i + 2w])
        w *= 2
    if w == width:
        return m[:n]
    return np.maximum(m[:n], m[width - w : width - w + n])


class LookaheadLimiter:
    """Brick-wall look-ahead limiter: with `enabled`, |output| <= ceiling is guaranteed.

    Per frame: required gain r = min(1, ceiling / peak) -> hold (min over L frames)
    -> release (instant attack, exponential recovery) -> L-frame moving average.
    The audio is delayed by L-1 frames, so the averaged gain is already down to r
    when a peak comes out. L-1 = round(lookahead_ms * fs / 1000) = latency_samples.
    """

    _CHUNK = 1024  # release is vectorised per chunk so a**-k stays finite

    def __init__(
        self,
        sample_rate: float,
        channels: int,
        ceiling_db: float = -1.0,
        lookahead_ms: float = 3.0,
        release_ms: float = 80.0,
    ) -> None:
        self.sample_rate = float(sample_rate)
        self.channels = int(channels)
        self.enabled = True
        self.last_gain_reduction_db = 0.0  # max reduction in the last block, as a positive dB value
        self.clip_count = 0  # blocks where the final safety clip had to change something
        self._length = 0
        self.set_params(ceiling_db=ceiling_db, lookahead_ms=lookahead_ms, release_ms=release_ms)

    @property
    def latency_samples(self) -> int:
        return self._length - 1

    def set_params(
        self,
        ceiling_db: float | None = None,
        lookahead_ms: float | None = None,
        release_ms: float | None = None,
        enabled: bool | None = None,
    ) -> None:
        """Change any parameter; a new look-ahead length resets the limiter (latency changes)."""
        if enabled is not None:
            self.enabled = bool(enabled)
        if ceiling_db is not None:
            self.ceiling_db = min(0.0, float(ceiling_db))
            # float32-exact, so the float32 output can reach but never exceed it
            self.ceiling = float(np.float32(db_to_linear(self.ceiling_db)))
        if release_ms is not None:
            self.release_ms = max(1.0, float(release_ms))
            tau = self.release_ms / 1000.0 * self.sample_rate  # release time constant, samples
            k = np.arange(self._CHUNK, dtype=np.float64) / tau
            self._a = math.exp(-1.0 / tau)
            self._apow = np.exp(-k)  # a**k
            self._apow_neg = np.exp(k)  # a**-k (<= e**128 since tau >= 8 samples)
        if lookahead_ms is not None:
            self.lookahead_ms = max(0.0, float(lookahead_ms))
            length = int(round(self.lookahead_ms * self.sample_rate / 1000.0)) + 1
            if length != self._length:
                self._length = length
                self.reset()

    def reset(self) -> None:
        h = self._length - 1
        self._peak_hist = np.zeros(h)
        self._gain_hist = np.ones(h)
        self._audio_hist = np.zeros((h, self.channels), dtype=np.float32)
        self._u = 0.0  # release state, in the reduction domain (1 - gain)
        self._settled = True  # no gain reduction anywhere in the state

    def _release(self, v: np.ndarray) -> np.ndarray:
        """u[n] = max(v[n], a*u[n-1]), vectorised as u[n] = a^n * cummax(v[k] * a^-k)."""
        u = np.empty_like(v)
        prev = self._u
        a = self._a
        for start in range(0, v.shape[0], self._CHUNK):
            seg = v[start : start + self._CHUNK]
            m = seg.shape[0]
            acc = np.maximum.accumulate(seg * self._apow_neg[:m])
            np.maximum(acc, prev * a, out=acc)
            out = u[start : start + m]
            np.multiply(acc, self._apow[:m], out=out)
            np.maximum(out, seg, out=out)  # exact u >= v despite rounding in a^k * a^-k
            prev = out[-1]
        self._u = float(prev)
        return u

    def process(self, block: np.ndarray) -> np.ndarray:
        n = block.shape[0]
        if n == 0:
            return np.zeros((0, self.channels), dtype=np.float32)
        length = self._length
        c = self.ceiling

        peak = np.abs(block[:, 0])  # column-wise max is ~10x faster than max(axis=1)
        for ch in range(1, block.shape[1]):
            np.maximum(peak, np.abs(block[:, ch]), out=peak)
        peaks = np.concatenate((self._peak_hist, peak))
        audio = np.concatenate((self._audio_hist, block.astype(np.float32, copy=False)))
        delayed = audio[:n]
        self._peak_hist = peaks[n:]
        self._audio_hist = audio[n:]

        if self._settled and peaks.max() <= c:
            # Fast path: unity gain in the whole window, the output is the delayed input.
            self.last_gain_reduction_db = 0.0
            return delayed.copy()

        held = c / np.maximum(_sliding_max(peaks, length), c)  # min of r over the last L frames
        gain = 1.0 - self._release(1.0 - held)
        gains = np.concatenate((self._gain_hist, gain))
        csum = np.empty(gains.shape[0] + 1)
        csum[0] = 0.0
        np.cumsum(gains, out=csum[1:])
        smooth = (csum[length:] - csum[:-length]) / length
        self._gain_hist = gains[n:]
        if self._u < 1e-7 and (length == 1 or self._gain_hist.min() > 1.0 - 1e-7):
            # Fully released (residual reduction < 1e-6 dB): snap to exact unity.
            self._u = 0.0
            self._gain_hist[:] = 1.0
            self._settled = True
        else:
            self._settled = False

        if self.enabled:
            out = (delayed * smooth[:, None]).astype(np.float32)
            lim = np.float32(c)
            min_gain = float(smooth.min())
            self.last_gain_reduction_db = -20.0 * math.log10(min_gain) if min_gain < 1.0 else 0.0
        else:
            out = delayed.copy()
            lim = np.float32(1.0)
            self.last_gain_reduction_db = 0.0
        if np.abs(out).max() > lim:  # safety net; never triggers while enabled
            np.clip(out, -lim, lim, out=out)
            if self.enabled:
                self.clip_count += 1
        return out


class StreamResampler:
    """Streaming libsamplerate converter whose ratio (out_rate / in_rate) may change on
    every call: one instance does rate conversion and clock-drift correction together.
    libsamplerate glides from the previous ratio to the new one across the block."""

    def __init__(self, channels: int, converter: str = "sinc_fastest") -> None:
        self.channels = int(channels)
        self._resampler = samplerate.Resampler(converter, self.channels)

    def process(self, block: np.ndarray, ratio: float) -> np.ndarray:
        if block.shape[0] == 0:
            return np.zeros((0, self.channels), dtype=np.float32)
        out = self._resampler.process(np.ascontiguousarray(block, dtype=np.float32), float(ratio))
        return out.reshape(-1, self.channels)

    def reset(self) -> None:
        self._resampler.reset()


class DriftController:
    """Slow PI loop that holds a FIFO's (smoothed) fill level at `target_frames` by
    nudging the resampling ratio. `factor` multiplies the nominal ratio out_rate/in_rate."""

    def __init__(
        self,
        target_frames: float,
        rate: float,
        kp: float = 0.2,  # ratio change per second of fill error
        ki: float = 0.01,  # ... per second^2 of integrated error (critically damped with kp)
        max_ppm: float = 500.0,
        smoothing_s: float = 1.0,
    ) -> None:
        self.target_frames = float(target_frames)
        self.rate = float(rate)
        self.kp = kp
        self.ki = ki
        self.max_ppm = max_ppm
        self.smoothing_s = smoothing_s
        self._integral = 0.0
        self.factor = 1.0
        self.fill: float | None = None  # smoothed fill, frames

    @property
    def ppm(self) -> float:
        return (self.factor - 1.0) * 1e6

    def reset_filter(self) -> None:
        """Forget the smoothed fill (after a resync) but keep the learned drift."""
        self.fill = None

    def update(self, fill_frames: float, dt: float) -> float:
        if self.fill is None:
            self.fill = float(fill_frames)
        else:
            self.fill += (1.0 - math.exp(-dt / self.smoothing_s)) * (fill_frames - self.fill)
        err = (self.fill - self.target_frames) / self.rate  # seconds; > 0 means too much buffered
        integral = self._integral + err * dt
        corr = -(self.kp * err + self.ki * integral)
        limit = self.max_ppm * 1e-6
        if -limit <= corr <= limit:
            self._integral = integral
        else:  # saturated: clamp and freeze the integrator (anti-windup)
            corr = max(-limit, min(limit, corr))
        self.factor = 1.0 + corr
        return self.factor

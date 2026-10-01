"""Device I/O for the engine: capture the Boost Bus, process, render to the real device.

BusPipeline is everything between the two device callbacks and is pure numpy, so
it is shared by BusBridge (WASAPI shared mode via sounddevice), FakeBridge (test
signal, no devices) and the tests. sounddevice is imported lazily: the fake and
the tests never load PortAudio.

Capture thread:  push()   -> RingBuffer
Render thread:   render() <- RingBuffer -> StreamResampler (rate + drift) -> GainRamp -> LookaheadLimiter
"""
from __future__ import annotations

import collections
import logging
import math
import threading
import time
from typing import Any, Callable

import numpy as np

from volumex.engine.dsp import (
    DriftController,
    GainRamp,
    LimiterSettings,
    LookaheadLimiter,
    StreamResampler,
)

log = logging.getLogger(__name__)

ErrorCallback = Callable[[str, str], None]  # (protocol error code, message)

DEFAULT_TARGET_LATENCY_MS = 10.0


class DeviceNotFoundError(Exception):
    pass


class StreamError(Exception):
    pass


class RingBuffer:
    """Thread-safe FIFO of float32 frames between the capture and the render thread."""

    def __init__(self, capacity: int, channels: int = 2) -> None:
        self._buf = np.zeros((capacity, channels), dtype=np.float32)
        self._cap = capacity
        self._read = 0
        self._count = 0
        self._lock = threading.Lock()

    @property
    def capacity(self) -> int:
        return self._cap

    @property
    def available(self) -> int:
        return self._count

    def write(self, block: np.ndarray) -> int:
        """Append frames (a mono block is broadcast to every channel). If the buffer is
        full the oldest frames are dropped; returns how many were dropped."""
        m = block.shape[0]
        dropped = 0
        with self._lock:
            if m > self._cap:
                dropped += m - self._cap
                block = block[m - self._cap :]
                m = self._cap
            over = self._count + m - self._cap
            if over > 0:
                self._read = (self._read + over) % self._cap
                self._count -= over
                dropped += over
            w = (self._read + self._count) % self._cap
            first = min(m, self._cap - w)
            self._buf[w : w + first] = block[:first]
            if first < m:
                self._buf[: m - first] = block[first:]
            self._count += m
        return dropped

    def read(self, n: int) -> np.ndarray:
        """Remove and return up to n frames (fewer if fewer are buffered)."""
        with self._lock:
            k = min(n, self._count)
            out = np.empty((k, self._buf.shape[1]), dtype=np.float32)
            first = min(k, self._cap - self._read)
            out[:first] = self._buf[self._read : self._read + first]
            if first < k:
                out[first:] = self._buf[: k - first]
            self._read = (self._read + k) % self._cap
            self._count -= k
        return out

    def discard(self, n: int) -> int:
        with self._lock:
            k = max(0, min(n, self._count))
            self._read = (self._read + k) % self._cap
            self._count -= k
        return k


def write_output(outdata: np.ndarray, stereo: np.ndarray) -> None:
    """Map a stereo block onto the device's channels: L/R to the first two, silence on the
    rest; a mono device gets the average of L and R."""
    channels = outdata.shape[1]
    if channels == 1:
        np.add(stereo[:, 0], stereo[:, 1], out=outdata[:, 0])
        outdata *= 0.5
    else:
        outdata[:, :2] = stereo
        if channels > 2:
            outdata[:, 2:] = 0.0


class BusPipeline:
    """Ring buffer -> drift-corrected resampler -> gain -> limiter, plus meters and xrun counters.

    push() runs on the capture thread, render() on the render thread. Parameter changes
    from other threads are queued and applied at the start of the next render().

    Drift loop: at every render the "virtual" fill (ring + resampler FIFO + the part of
    the current capture period that has elapsed since the last push) is fed to a slow
    PI controller that trims the resampling ratio. Interpolating the bursty capture
    this way keeps the measurement free of callback-phase beats. The target is floored
    at one capture burst + one render block (+1 ms), the minimum that cannot underrun.
    """

    def __init__(
        self,
        in_rate: int,
        out_rate: int,
        *,
        target_latency_ms: float = DEFAULT_TARGET_LATENCY_MS,
        gain: float = 1.0,
        limiter: LimiterSettings = LimiterSettings(),
    ) -> None:
        self.in_rate = int(in_rate)
        self.out_rate = int(out_rate)
        self.base_ratio = self.out_rate / self.in_rate
        self.target_latency_ms = float(target_latency_ms)
        self._target = self.in_rate * self.target_latency_ms / 1000.0  # requested fill, input frames
        self._burst = 0  # largest capture block seen, input frames
        self._block = 0  # largest render block seen, in input frames
        self._seen = [False, False]  # observed sizes replace expect_blocks() guesses
        self.target_frames = self._target  # effective target (with the floor)

        self._ring = RingBuffer(int(self.in_rate * 0.5) + 8192)  # physical room; see _high_water
        self._resampler = StreamResampler(2)
        self._fifo = np.zeros((8192, 2), dtype=np.float32)  # resampled frames not yet rendered
        self._fifo_len = 0
        self._out = np.zeros((4096, 2), dtype=np.float32)
        self.drift = DriftController(self.target_frames, self.in_rate)
        self.gain = GainRamp(self.out_rate, gain)
        self.limiter = LookaheadLimiter(
            self.out_rate, 2, limiter.ceiling_db, limiter.lookahead_ms, limiter.release_ms
        )
        self.limiter.enabled = limiter.enabled

        self._pending: collections.deque[Callable[[], None]] = collections.deque()
        self._priming = True
        self._last_push: tuple[float, int] | None = None  # (time, frames) of the last capture block
        self.fill_frames = 0.0  # last virtual fill measurement, input frames
        self.underruns = 0
        self.overruns = 0
        self._meter = (0.0, 0.0, 0.0)  # peak L, peak R, gain reduction dB; max since last take
        self._high_water = 0
        self._update_target()

    # -- control (any thread) ----------------------------------------------------------------

    def set_gain(self, gain: float, ramp_ms: float) -> None:
        self._pending.append(lambda: self.gain.set_target(gain, ramp_ms))

    def set_limiter(self, s: LimiterSettings) -> None:
        self._pending.append(
            lambda: self.limiter.set_params(s.ceiling_db, s.lookahead_ms, s.release_ms, s.enabled)
        )

    def take_meters(self) -> tuple[float, float, float]:
        """(peak L, peak R, gain reduction dB), the maximum since the previous call."""
        m = self._meter
        self._meter = (0.0, 0.0, 0.0)
        return m

    def expect_blocks(self, capture_frames: int, render_frames: int) -> None:
        """Seed the target floor with guessed callback sizes (render in output frames) so
        latency_ms is meaningful before the first callback; observed sizes replace them."""
        self._burst = int(capture_frames)
        self._block = int(math.ceil(render_frames / self.base_ratio))
        self._update_target()

    @property
    def latency_ms(self) -> float:
        """Buffering added by the pipeline itself: ring target + limiter look-ahead."""
        return 1000.0 * (self.target_frames / self.in_rate + self.limiter.latency_samples / self.out_rate)

    # -- capture thread ----------------------------------------------------------------------

    def push(self, block: np.ndarray, now: float | None = None) -> None:
        """Queue captured frames; any channel count (mono is duplicated, >2 keeps the first two)."""
        m = block.shape[0]
        if m == 0:
            return
        if m > self._burst or not self._seen[0]:
            self._seen[0] = True
            self._burst = m
            self._update_target()
        if self._ring.write(block[:, :2] if block.shape[1] > 2 else block):
            self.overruns += 1
        self._last_push = (time.perf_counter() if now is None else now, m)
        if self._ring.available > self._high_water:
            # Consumer stalled or far too slow: resync to the target instead of drifting back.
            self._ring.discard(self._ring.available - int(self.target_frames))
            self.overruns += 1

    # -- render thread -----------------------------------------------------------------------

    def render(self, n: int, now: float | None = None) -> np.ndarray:
        """Produce exactly n processed stereo frames at out_rate (silence where input is missing)."""
        while self._pending:
            self._pending.popleft()()
        if n > self._out.shape[0]:
            self._out = np.zeros((n, 2), dtype=np.float32)
        out = self._out[:n]
        ratio = self.base_ratio * self.drift.factor
        n_in = n / ratio
        if n_in > self._block or not self._seen[1]:
            self._seen[1] = True
            self._block = int(math.ceil(n_in))
            self._update_target()

        if self._priming:
            avail = self._ring.available
            if avail >= self.target_frames:
                # Start (or restart after an underrun) at exactly the target fill.
                self._ring.discard(avail - int(math.ceil(self.target_frames)))
                self._priming = False
                self.drift.reset_filter()

        if self._priming:
            out[:] = 0.0
        else:
            now = time.perf_counter() if now is None else now
            self._measure_fill(now, ratio, n / self.out_rate)
            got = self._fill_fifo(n, ratio)
            take = min(got, n)
            out[:take] = self._fifo[:take]
            self._fifo[: got - take] = self._fifo[take:got]
            self._fifo_len = got - take
            if take < n:
                out[take:] = 0.0
                self.underruns += 1
                self._priming = True

        y = self.limiter.process(self.gain.process(out))
        self._update_meters(y)
        return y

    def _measure_fill(self, now: float, ratio: float, dt: float) -> None:
        fill = self._ring.available + self._fifo_len / ratio
        last = self._last_push
        if last is not None:
            fill += min(last[1], max(0.0, (now - last[0]) * self.in_rate))
        self.fill_frames = fill
        self.drift.update(fill, dt)

    def _fill_fifo(self, n: int, ratio: float) -> int:
        for _ in range(4):  # normally 1 pass; libsamplerate holds back a few frames at start
            missing = n - self._fifo_len
            if missing <= 0:
                break
            chunk = self._ring.read(int(math.ceil(missing / ratio)) + 1)
            if chunk.shape[0] == 0:
                break
            res = self._resampler.process(chunk, ratio)
            end = self._fifo_len + res.shape[0]
            if end > self._fifo.shape[0]:
                grown = np.zeros((2 * end, 2), dtype=np.float32)
                grown[: self._fifo_len] = self._fifo[: self._fifo_len]
                self._fifo = grown
            self._fifo[self._fifo_len : end] = res
            self._fifo_len = end
        return self._fifo_len

    def _update_target(self) -> None:
        floor = self._burst + self._block + self.in_rate / 1000.0
        self.target_frames = max(self._target, floor)
        self.drift.target_frames = self.target_frames
        # Resync when the fill is this far above target (drift correction alone would take minutes).
        self._high_water = min(self._ring.capacity - 1, int(2 * self.target_frames + 0.05 * self.in_rate))

    def _update_meters(self, y: np.ndarray) -> None:
        pl = float(np.abs(y[:, 0]).max()) if y.shape[0] else 0.0
        pr = float(np.abs(y[:, 1]).max()) if y.shape[0] else 0.0
        m = self._meter
        self._meter = (max(m[0], pl), max(m[1], pr), max(m[2], self.limiter.last_gain_reduction_db))


class Bridge:
    """Configuration, control and meters shared by BusBridge and FakeBridge.
    Subclasses implement _open() (create the pipeline, start I/O) and _close()."""

    def __init__(self, on_error: ErrorCallback | None = None) -> None:
        self.on_error = on_error
        self.capture = ""
        self.output = ""
        self.target_latency_ms = DEFAULT_TARGET_LATENCY_MS
        self.gain = 1.0
        self.limiter = LimiterSettings()
        self.in_rate = 0
        self.out_rate = 0
        self.pipeline: BusPipeline | None = None
        self._device_latency_s = 0.0  # input + output stream latency
        self._error_reported = False
        self._next_stats = 0.0

    @property
    def streaming(self) -> bool:
        return self.pipeline is not None

    def configure(self, capture: str, output: str, target_latency_ms: float | None = None) -> None:
        """Store the devices (and ring target); takes effect at the next start()."""
        self.capture = capture
        self.output = output
        if target_latency_ms is not None:
            self.target_latency_ms = float(target_latency_ms)

    def reconfigure(self, capture: str, output: str, target_latency_ms: float | None = None) -> None:
        """Like configure(), but re-opens the streams if currently streaming."""
        was_streaming = self.streaming
        if was_streaming:
            self.stop()
        self.configure(capture, output, target_latency_ms)
        if was_streaming:
            self.start()

    def start(self) -> None:
        """Open the streams and start processing. Raises DeviceNotFoundError or StreamError."""
        if self.streaming:
            return
        self._error_reported = False
        self._next_stats = time.monotonic() + self.STATS_EVERY_S
        self._open()

    def stop(self) -> None:
        if self.streaming:
            self._close()
        self.pipeline = None
        self.in_rate = self.out_rate = 0
        self._device_latency_s = 0.0

    def set_gain(self, gain: float, ramp_ms: float) -> None:
        self.gain = float(gain)
        if self.pipeline is not None:
            self.pipeline.set_gain(self.gain, ramp_ms)

    def set_limiter(self, settings: LimiterSettings) -> None:
        self.limiter = settings
        if self.pipeline is not None:
            self.pipeline.set_limiter(settings)

    def meters(self) -> dict[str, Any]:
        p = self.pipeline
        if p is None:
            return {"peak": [0.0, 0.0], "gr_db": 0.0, "underruns": 0, "overruns": 0}
        pl, pr, gr = p.take_meters()
        return {
            "peak": [round(pl, 5), round(pr, 5)],
            "gr_db": round(gr, 2),
            "underruns": p.underruns,
            "overruns": p.overruns,
        }

    @property
    def latency_ms(self) -> float:
        """Estimated capture-to-render latency: input + ring + look-ahead + output."""
        if self.pipeline is None:
            return 0.0
        return self.pipeline.latency_ms + 1000.0 * self._device_latency_s

    def state(self) -> dict[str, Any]:
        return {
            "streaming": self.streaming,
            "capture": self.capture,
            "output": self.output,
            "in_rate": self.in_rate,
            "out_rate": self.out_rate,
            "latency_ms": round(self.latency_ms, 2),
        }

    STATS_EVERY_S = 10.0

    def poll(self) -> None:
        """Called periodically by the server while streaming: health checks and a stats log line."""
        p = self.pipeline
        now = time.monotonic()
        if p is None or now < self._next_stats:
            return
        self._next_stats = now + self.STATS_EVERY_S
        log.info(
            "drift %+.1f ppm, ring %.1f ms (target %.1f), underruns %d, overruns %d, limiter safety clips %d",
            p.drift.ppm,
            1000.0 * p.fill_frames / p.in_rate,
            1000.0 * p.target_frames / p.in_rate,
            p.underruns,
            p.overruns,
            p.limiter.clip_count,
        )

    def _new_pipeline(self, in_rate: int, out_rate: int) -> BusPipeline:
        return BusPipeline(
            in_rate,
            out_rate,
            target_latency_ms=self.target_latency_ms,
            gain=self.gain,
            limiter=self.limiter,
        )

    def _report_error(self, code: str, message: str) -> None:
        if self._error_reported:
            return
        self._error_reported = True
        if self.on_error is not None:
            self.on_error(code, message)

    def _open(self) -> None:
        raise NotImplementedError

    def _close(self) -> None:
        raise NotImplementedError


def _sounddevice() -> Any:
    import sounddevice

    return sounddevice


def find_wasapi_device(
    name: str,
    kind: str,
    devices: list[dict[str, Any]] | None = None,
    hostapis: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Find a WASAPI device by friendly name: exact match first, then case-insensitive
    'contains'. kind is "input" or "output". Raises DeviceNotFoundError."""
    if devices is None or hostapis is None:
        sd = _sounddevice()
        devices = list(sd.query_devices())
        hostapis = list(sd.query_hostapis())
    wasapi = [i for i, api in enumerate(hostapis) if "WASAPI" in api["name"]]
    if not wasapi:
        raise DeviceNotFoundError("the WASAPI host API is not available")
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    candidates = [d for d in devices if d["hostapi"] in wasapi and d[key] > 0]
    for d in candidates:
        if d["name"] == name:
            return d
    wanted = name.strip().lower()
    if wanted:
        for d in candidates:
            if wanted in d["name"].lower():
                return d
    raise DeviceNotFoundError(f"no WASAPI {kind} device named {name!r}")


class BusBridge(Bridge):
    """Captures the bus device and renders the processed audio to the output device, both
    in WASAPI shared mode at each device's mix-format rate."""

    STALL_S = 1.0  # render callbacks missing this long -> stream_failed

    def __init__(self, on_error: ErrorCallback | None = None, latency: str | float = "low") -> None:
        super().__init__(on_error)
        self.latency = latency  # passed to PortAudio for both streams
        self._in_stream: Any = None
        self._out_stream: Any = None
        self._stopping = False
        self._fail_reason = ""
        self._last_in = 0.0
        self._last_out = 0.0
        self._input_stall_logged = False

    def _open(self) -> None:
        sd = _sounddevice()
        sd._terminate()  # PortAudio caches the device list; re-scan so new/changed devices show up
        sd._initialize()
        cap = find_wasapi_device(self.capture, "input")
        out = find_wasapi_device(self.output, "output")
        in_rate = int(cap["default_samplerate"])
        out_rate = int(out["default_samplerate"])
        pipeline = self._new_pipeline(in_rate, out_rate)
        self._stopping = False
        self._fail_reason = ""
        try:
            self._out_stream = sd.OutputStream(
                device=out["index"],
                samplerate=out_rate,
                channels=out["max_output_channels"],
                dtype="float32",
                latency=self.latency,
                extra_settings=sd.WasapiSettings(exclusive=False),
                callback=self._out_callback,
                finished_callback=self._finished,
            )
            self._in_stream = sd.InputStream(
                device=cap["index"],
                samplerate=in_rate,
                channels=cap["max_input_channels"],
                dtype="float32",
                latency=self.latency,
                extra_settings=sd.WasapiSettings(exclusive=False),
                callback=self._in_callback,
                finished_callback=self._finished,
            )
            in_latency, out_latency = float(self._in_stream.latency), float(self._out_stream.latency)
            # Blocksize is variable (0); the stream latency is our best guess of a callback's size.
            pipeline.expect_blocks(int(in_latency * in_rate), int(out_latency * out_rate))
            self.pipeline = pipeline  # callbacks read it; set before the streams run
            self.in_rate, self.out_rate = in_rate, out_rate
            self._device_latency_s = in_latency + out_latency
            self._last_in = self._last_out = time.monotonic()
            self._input_stall_logged = False
            # Output first: it renders silence until the capture side has primed the ring.
            self._out_stream.start()
            self._in_stream.start()
        except Exception as exc:
            self._close()
            self.pipeline = None
            self.in_rate = self.out_rate = 0
            raise StreamError(f"could not open audio streams: {exc}") from exc
        log.info(
            "streaming %r (%d Hz, %d ch) -> %r (%d Hz, %d ch), est. latency %.1f ms",
            cap["name"],
            in_rate,
            cap["max_input_channels"],
            out["name"],
            out_rate,
            out["max_output_channels"],
            self.latency_ms,
        )

    def _close(self) -> None:
        self._stopping = True
        for stream in (self._in_stream, self._out_stream):
            if stream is not None:
                try:
                    stream.close(ignore_errors=True)  # discards pending buffers, like abort()
                except Exception:
                    log.exception("closing audio stream failed")
        self._in_stream = self._out_stream = None

    def _in_callback(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        self._last_in = time.monotonic()
        p = self.pipeline
        try:
            if status and status.input_overflow:
                p.overruns += 1
            p.push(indata)
        except Exception as exc:
            self._fail_reason = f"capture callback failed: {exc!r}"
            raise _sounddevice().CallbackAbort from exc

    def _out_callback(self, outdata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        self._last_out = time.monotonic()
        p = self.pipeline
        try:
            if status and status.output_underflow:
                p.underruns += 1
            write_output(outdata, p.render(frames))
        except Exception as exc:
            outdata.fill(0.0)
            self._fail_reason = f"render callback failed: {exc!r}"
            raise _sounddevice().CallbackAbort from exc

    def _finished(self) -> None:
        if not self._stopping:
            self._report_error("stream_failed", self._fail_reason or "audio stream stopped unexpectedly")

    def poll(self) -> None:
        if self.pipeline is None:
            return
        super().poll()
        now = time.monotonic()
        if now - self._last_out > self.STALL_S:
            self._report_error("stream_failed", f"output device {self.output!r} stopped processing audio")
        if now - self._last_in > 2.0 and not self._input_stall_logged:
            # Not fatal: the render side keeps playing silence (and counts underruns).
            self._input_stall_logged = True
            log.warning("capture device %r delivers no audio", self.capture)


class FakeBridge(Bridge):
    """Device-free stand-in for BusBridge (`--fake-io`): a thread generates a test tone,
    runs it through the same BusPipeline and discards the output at real-time pace."""

    def __init__(
        self,
        on_error: ErrorCallback | None = None,
        in_rate: int = 48000,
        out_rate: int = 48000,
        period_ms: float = 10.0,
    ) -> None:
        super().__init__(on_error)
        self._rates = (in_rate, out_rate)
        self.period_ms = period_ms
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _open(self) -> None:
        if not self.capture or not self.output:
            raise DeviceNotFoundError("fake device name must not be empty")
        in_rate, out_rate = self._rates
        pipeline = self._new_pipeline(in_rate, out_rate)
        period = self.period_ms / 1000.0
        pipeline.expect_blocks(int(math.ceil(in_rate * period)), int(round(out_rate * period)))
        self.pipeline = pipeline
        self.in_rate, self.out_rate = in_rate, out_rate
        self._device_latency_s = 2 * self.period_ms / 1000.0
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, args=(self.pipeline,), name="fake-io", daemon=True)
        self._thread.start()

    def _close(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None

    def _run(self, p: BusPipeline) -> None:
        period = self.period_ms / 1000.0
        out_n = int(round(p.out_rate * period))
        in_pos = 0.0  # fractional input frame counter, so any rate pair works
        phase = 0
        amp = np.array([0.25, 0.125], dtype=np.float32)  # -12 / -18 dBFS, 440 Hz
        deadline = time.perf_counter()
        while not self._stop_event.is_set():
            in_pos += p.in_rate * period
            in_n = int(in_pos)
            in_pos -= in_n
            t = np.arange(phase, phase + in_n) * (2.0 * np.pi * 440.0 / p.in_rate)
            phase = (phase + in_n) % p.in_rate  # 440 Hz completes whole cycles every second
            p.push(np.sin(t).astype(np.float32)[:, None] * amp)
            p.render(out_n)
            deadline += period
            delay = deadline - time.perf_counter()
            if delay > 0:
                self._stop_event.wait(delay)
            elif delay < -0.1:
                deadline = time.perf_counter()  # fell far behind (e.g. suspended): don't burst

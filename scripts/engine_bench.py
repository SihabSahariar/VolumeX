"""Time the engine's per-block DSP chain (no audio devices are opened).

    .venv\\Scripts\\python.exe scripts\\engine_bench.py [--blocks N] [--frames 480]

Measures, per render block of stereo audio at 48 kHz: the resampler (with drift
trim), gain ramp and limiter on their own, and the full BusPipeline push+render
(ring buffer, resampler, gain, limiter, meters) with the limiter idle and busy.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Callable

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from volumex.engine.audio_io import BusPipeline  # noqa: E402
from volumex.engine.dsp import GainRamp, LookaheadLimiter, StreamResampler  # noqa: E402

RATE = 48000


def bench(name: str, fn: Callable[[int], None], blocks: int, frames: int) -> None:
    for i in range(50):  # warm-up
        fn(i)
    times = np.empty(blocks)
    for i in range(blocks):
        t0 = time.perf_counter()
        fn(i)
        times[i] = time.perf_counter() - t0
    us = times * 1e6
    budget = frames / RATE * 1e6
    print(
        f"{name:34s} mean {us.mean():7.1f} us   p99 {np.percentile(us, 99):7.1f} us   "
        f"max {us.max():7.1f} us   ({100 * us.mean() / budget:4.1f}% of a {budget / 1000:.0f} ms block)"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--blocks", type=int, default=5000)
    parser.add_argument("--frames", type=int, default=480)
    args = parser.parse_args()
    n = args.frames
    rng = np.random.default_rng(0)
    quiet = (0.1 * rng.standard_normal((n, 2))).astype(np.float32)
    loud = (0.5 * rng.standard_normal((n, 2))).astype(np.float32)  # x5 gain -> limiter busy
    overload = loud * np.float32(5.0)

    resampler = StreamResampler(2)
    drift = (1.0 - 1e-4, 1.0, 1.0 + 1e-4)
    bench("resampler (ratio 1 +- 100 ppm)", lambda i: resampler.process(quiet, drift[i % 3]), args.blocks, n)
    gain = GainRamp(RATE, 1.0)

    def ramp(i: int) -> None:
        if i % 10 == 0:
            gain.set_target(1.0 + (i // 10) % 4, 30.0)
        gain.process(quiet)

    bench("gain ramp (ramping)", ramp, args.blocks, n)
    limiter = LookaheadLimiter(RATE, 2)
    bench("limiter (idle, fast path)", lambda i: limiter.process(quiet), args.blocks, n)
    bench("limiter (busy, x5 overload)", lambda i: limiter.process(overload), args.blocks, n)

    for label, block, g in (("idle", quiet, 1.0), ("busy", loud, 5.0)):
        p = BusPipeline(RATE, RATE, gain=g)

        def chain(i: int, p: BusPipeline = p, block: np.ndarray = block) -> None:
            p.push(block)
            p.render(n)

        bench(f"full chain push+render ({label})", chain, args.blocks, n)
        assert p.underruns == 0


if __name__ == "__main__":
    main()

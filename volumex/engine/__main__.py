"""Engine process entry point: `python -m volumex.engine [--fake-io]`.

Speaks the JSON-lines protocol (volumex.engine.protocol) on stdin/stdout; logs go
to stderr. --fake-io replaces the audio devices with a generated test signal.
"""
from __future__ import annotations

import argparse
import gc
import logging
import os
import sys

log = logging.getLogger("volumex.engine")


def _raise_priority() -> None:
    try:
        import psutil

        psutil.Process().nice(psutil.ABOVE_NORMAL_PRIORITY_CLASS)
    except Exception as exc:  # not Windows, or not allowed
        log.debug("could not raise process priority: %s", exc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m volumex.engine")
    parser.add_argument("--fake-io", action="store_true", help="generated test signal instead of audio devices")
    parser.add_argument("--log-level", default="INFO", help="stderr log level (default INFO)")
    parser.add_argument(
        "--latency",
        default="low",
        help="PortAudio latency of both streams: 'low' (default), 'high' or seconds, e.g. 0.02",
    )
    args = parser.parse_args(argv)
    latency: str | float = args.latency if args.latency in ("low", "high") else float(args.latency)

    # Keep the protocol channel private: our own handles on the original stdin/stdout,
    # and fd 1 now points at stderr, so a stray print (ours or a library's) can't corrupt it.
    proto_in = os.fdopen(os.dup(sys.stdin.fileno()), "rb", buffering=0)  # unbuffered: no lock at exit
    proto_out = os.fdopen(os.dup(sys.stdout.fileno()), "wb")
    try:
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        sys.stdout = sys.stderr
    except (OSError, AttributeError, ValueError):
        pass

    logging.basicConfig(
        stream=sys.stderr,
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _raise_priority()

    from volumex.engine.audio_io import BusBridge, FakeBridge
    from volumex.engine.server import EngineServer, EventLogHandler

    bridge = FakeBridge() if args.fake_io else BusBridge(latency=latency)
    server = EngineServer(bridge, proto_in, proto_out)
    logging.getLogger().addHandler(EventLogHandler(server))
    gc.freeze()  # startup objects never need scanning again: shorter GC pauses in callbacks
    sys.setswitchinterval(0.001)  # an audio callback waits at most ~1 ms (not 5) for the GIL
    log.info("engine started (pid %d, %s)", os.getpid(), "fake io" if args.fake_io else "WASAPI")
    code = server.run()
    logging.shutdown()
    proto_out.close()
    return code


if __name__ == "__main__":
    sys.exit(main())

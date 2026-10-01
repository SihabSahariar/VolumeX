"""Engine <-> controller protocol: one JSON object per line, UTF-8.

The controller starts the engine as a child process (`python -m volumex.engine`,
or `VolumeX.exe --engine` when frozen) and talks to it over stdin/stdout.
stderr carries logs only. A future native (C++) engine speaks the same protocol,
so the controller never needs to change when the engine is swapped.

Commands (controller -> engine), discriminated by "cmd":
  configure    {capture: str, output: str, gain: float,
                limiter: {enabled: bool, ceiling_db: float, release_ms: float, lookahead_ms: float},
                target_latency_ms: float}
               capture/output are WASAPI device friendly names. If already streaming and a
               device changed, the engine re-opens its streams.
  start        open streams and start processing; answered with a "state" event
  stop         close streams (engine idles at ~0% CPU); answered with a "state" event
  set_gain     {gain: float, ramp_ms: float}   linear gain (>= 0) applied before the limiter
  set_limiter  {enabled: bool, ceiling_db: float, release_ms: float}
  ping         answered with "pong"
  shutdown     close streams and exit(0) without restoring anything

Events (engine -> controller), discriminated by "event":
  ready    {version: str, pid: int}                               once, at startup
  state    {streaming: bool, capture: str, output: str,
            in_rate: int, out_rate: int, latency_ms: float}
  meters   {peak: [float, float], gr_db: float,
            underruns: int, overruns: int}                          ~30 Hz while streaming
  error    {code: str, message: str}   codes: device_not_found, stream_failed, bad_command
  pong     {}
  log      {level: str, message: str}

If stdin reaches EOF (the controller died), the engine calls
volumex.safety.restore.restore_after_controller_exit() and exits, so apps are
never left routed to a bus that nobody is listening to.
"""
from __future__ import annotations

import json
from typing import Any

PROTOCOL_VERSION = "1"


def encode(message: dict[str, Any]) -> bytes:
    return (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")


def decode(line: bytes | str) -> dict[str, Any]:
    if isinstance(line, bytes):
        line = line.decode("utf-8")
    message = json.loads(line)
    if not isinstance(message, dict):
        raise ValueError("protocol message must be a JSON object")
    return message

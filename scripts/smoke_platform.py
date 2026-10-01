"""READ-ONLY smoke test of the Windows platform layer on this PC.

Changes nothing: the audio system runs with dry_run=True and only Get* calls are made
(GetPersistedDefaultAudioEndpoint validates the IAudioPolicyConfigFactory vtable).

    .venv\\Scripts\\python.exe scripts\\smoke_platform.py
"""
from __future__ import annotations

import sys

sys.coinit_flags = 0  # COINIT_MULTITHREADED; comtypes initialises COM on import
import logging  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import comtypes  # noqa: E402

from volumex.platform.appinfo import display_name  # noqa: E402
from volumex.platform.foreground import foreground_process  # noqa: E402
from volumex.platform.policy_config import AudioPolicyConfig  # noqa: E402
from volumex.platform.windows_audio import WindowsAudioSystem  # noqa: E402


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
    print(f"Windows build {sys.getwindowsversion().build}")

    audio = WindowsAudioSystem(dry_run=True)
    print(f"Per-app routing available: {audio.routing_available}")

    t0 = time.perf_counter()
    snap = audio.snapshot()
    print(f"\nsnapshot() took {(time.perf_counter() - t0) * 1000:.1f} ms")
    print(f"Default endpoint: {snap.default_endpoint_id}")
    print(f"Endpoint volume: {snap.endpoint_volume:.3f}  muted: {snap.endpoint_muted}")
    print("Endpoints:")
    for ep in snap.endpoints:
        flags = ("default " if ep.is_default else "") + ("BUS" if ep.is_bus else "")
        print(f"  {ep.name!r:50} {ep.id}  {flags}")
    print("Sessions:")
    for s in snap.sessions:
        ep = snap.endpoint(s.endpoint_id)
        print(
            f"  pid={s.pid:<6} name={s.name!r:32} vol={s.volume:.2f} muted={s.muted!s:5} "
            f"active={s.active!s:5} on={ep.name if ep else '?'!r}\n      key={s.key}"
        )

    print("\nPeaks:")
    for round_no in range(3):
        t0 = time.perf_counter()
        peaks = audio.peaks()
        elapsed = (time.perf_counter() - t0) * 1000
        shown = ", ".join(f"{pid}:{level:.3f}" for (_ep, pid), level in sorted(peaks.items(), key=lambda kv: kv[0][1]))
        print(f"  round {round_no + 1} ({elapsed:.2f} ms): {shown}")
        time.sleep(0.2)

    print("\nPersisted app routes (GetPersistedDefaultAudioEndpoint):")
    for pid in sorted({s.pid for s in snap.sessions}):
        try:
            route = audio.get_app_route(pid)
            ep = snap.endpoint(route)
            print(f"  pid={pid:<6} -> {route or 'Windows default'}" + (f" ({ep.name})" if ep else ""))
        except OSError as exc:
            print(f"  pid={pid:<6} -> ERROR {exc}")
    raw = AudioPolicyConfig()
    try:
        raw.get_app_endpoint(999999)
        print("  raw pid=999999 -> S_OK (unexpected)")
    except OSError as exc:
        print(f"  raw pid=999999 -> {exc} (expected E_INVALIDARG: the method validates the pid)")
    finally:
        raw.close()

    print(f"\nForeground process: {foreground_process()}")

    print("\nDisplay names:")
    for exe in sorted({s.exe_path for s in snap.sessions if s.exe_path}):
        print(f"  {display_name(exe)!r:40} <- {exe}")
    print(f"  {display_name(sys.executable)!r:40} <- {sys.executable}")
    missing = r"C:\nope\my_cool-app.exe"
    print(f"  {display_name(missing)!r:40} <- {missing} (missing file)")

    audio.close()


if __name__ == "__main__":
    main()

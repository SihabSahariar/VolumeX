"""Undo VolumeX's changes to Windows audio, driven by the journal.

Used on normal quit, on startup after a crash, by the engine when the controller
dies, by the "Reset audio" button and by the uninstaller (`VolumeX --restore`).
"""
from __future__ import annotations

import logging
import os
import time

import psutil

from volumex.core.app_identity import app_key
from volumex.platform.base import AudioSystem

from .journal import Journal

log = logging.getLogger(__name__)


def running_pids(key: str) -> list[int]:
    pids = []
    for proc in psutil.process_iter(["pid", "exe"]):
        exe = proc.info.get("exe")
        if exe and app_key(exe, proc.info["pid"]) == key:
            pids.append(proc.info["pid"])
    return pids


def restore_routes(
    audio: AudioSystem,
    journal: Journal,
    volumes: dict[str, float] | None = None,
    clear_closed_apps: bool = False,
) -> list[str]:
    """Route every journaled app back to the Windows default device.

    ``volumes`` overrides the journaled restore volume per app key. Apps that are
    not running cannot be reset through the Windows API (it needs a live process);
    they stay in the journal unless ``clear_closed_apps`` resets every app's
    per-app device choice. Returns the keys still pending.
    """
    if journal.is_empty():
        return []
    volumes = volumes or {}
    snap = audio.snapshot()
    pending: list[str] = []
    restored: dict[str, float] = {}
    for key, entry in list(journal.routes.items()):
        pids = {s.pid for s in snap.sessions if s.key == key} or set(running_pids(key))
        if not pids:
            pending.append(key)
            continue
        ok = False
        for pid in pids:
            try:
                audio.route_app(pid, None)
                ok = True
            except OSError as exc:
                log.warning("could not reset route of %s (pid %s): %s", key, pid, exc)
        if ok:
            restored[key] = volumes.get(key, float(entry.get("restore_volume", 1.0)))
            journal.remove_route(key)

    if restored:
        time.sleep(0.3)  # let the apps move back before their volume goes up
        for s in audio.snapshot().sessions:
            if s.key in restored:
                try:
                    audio.set_session_volume(s.endpoint_id, s.pid, restored[s.key])
                except OSError as exc:
                    log.warning("could not restore volume of %s: %s", s.key, exc)

    if pending and clear_closed_apps:
        try:
            audio.clear_all_routes()
            for key in pending:
                journal.remove_route(key)
            pending = []
        except OSError as exc:
            log.error("could not clear per-app routes: %s", exc)
    return pending


def restore_after_controller_exit() -> None:
    """Called by the engine process when the controller vanished without cleaning up."""
    if os.environ.get("VOLUMEX_DEMO") == "1":
        return
    journal = Journal()
    if journal.is_empty():
        return
    import comtypes

    try:
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
    except OSError:
        pass  # COM already initialised on this thread
    from volumex.platform.windows_audio import WindowsAudioSystem

    audio = WindowsAudioSystem(dry_run=os.environ.get("VOLUMEX_DRY_RUN") == "1")
    try:
        pending = restore_routes(audio, journal)
        log.info("restored after controller exit; pending: %s", pending)
    finally:
        audio.close()

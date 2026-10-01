"""Application bootstrap: logging, single instance, controller, windows, tray, hotkeys."""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
import tempfile

from PyQt5.QtCore import QCoreApplication, Qt
from PyQt5.QtWidgets import QApplication, QWidget

from volumex import APP_NAME, __version__

log = logging.getLogger("volumex")


def _setup_logging(verbose: bool) -> None:
    from volumex.storage.paths import log_dir

    handler = logging.handlers.RotatingFileHandler(log_dir() / "volumex.log", maxBytes=1_000_000, backupCount=3,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    if verbose and sys.stderr:
        root.addHandler(logging.StreamHandler())
    root.setLevel(logging.DEBUG if verbose else logging.INFO)


def _init_qt() -> None:
    QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    try:
        from PyQt5.QtGui import QGuiApplication

        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except AttributeError:
        pass


def _style_app(app: QApplication) -> None:
    from volumex.ui.theme import apply_stylesheet, theme

    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    theme.init_fonts()
    app.setFont(theme.font(10))
    apply_stylesheet()


def build_pages(controller, settings, on_setup, on_boost) -> list[QWidget]:
    from volumex.ui.pages.about_page import AboutPage
    from volumex.ui.pages.automations_page import AutomationsPage
    from volumex.ui.pages.devices_page import DevicesPage
    from volumex.ui.pages.mixer_page import MixerPage
    from volumex.ui.pages.settings_page import SettingsPage

    mixer = MixerPage(controller)
    mixer.setupRequested.connect(on_setup)
    mixer.boostCommitted.connect(on_boost)
    devices = DevicesPage(controller)
    devices.setupRequested.connect(on_setup)
    automations = AutomationsPage(controller)
    settings_page = SettingsPage(controller, settings)
    settings_page.setupRequested.connect(on_setup)
    return [mixer, devices, automations, settings_page, AboutPage()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="volumex", description="Per-app and system-wide volume booster")
    parser.add_argument("--minimized", action="store_true", help="start in the tray")
    parser.add_argument("--demo", action="store_true", help="simulated apps and devices; real audio untouched")
    parser.add_argument("--dry-run", action="store_true", help="read real audio state but never change it")
    parser.add_argument("--restore", action="store_true", help="undo VolumeX's audio changes and exit")
    parser.add_argument("--clear-closed-apps", action="store_true", help="with --restore: also reset closed apps")
    parser.add_argument("--engine", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--fake-io", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    if args.engine:  # frozen builds run the engine through the same executable
        from volumex.engine.__main__ import main as engine_main

        return engine_main(["--fake-io"] if args.fake_io else [])

    if args.demo:
        os.environ["VOLUMEX_DEMO"] = "1"
        os.environ.setdefault("VOLUMEX_DATA_DIR", os.path.join(tempfile.gettempdir(), "volumex-demo"))
    if args.dry_run:
        os.environ["VOLUMEX_DRY_RUN"] = "1"
    _setup_logging(args.verbose)
    log.info("VolumeX %s starting (demo=%s dry_run=%s)", __version__, args.demo, args.dry_run)

    if args.restore:
        return _restore_and_exit(args.clear_closed_apps)

    _init_qt()
    app = QApplication(sys.argv if argv is None else [sys.argv[0], *argv])
    app.setQuitOnLastWindowClosed(False)
    _style_app(app)

    from volumex.ui.shell import AppShell

    shell = AppShell(app, demo=args.demo, dry_run=args.dry_run, start_minimized=args.minimized)
    if not shell.acquire_single_instance():
        return 0
    shell.start()
    return app.exec_()


def _restore_and_exit(clear_closed_apps: bool) -> int:
    import comtypes

    try:
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
    except OSError:
        pass
    from volumex.platform.windows_audio import WindowsAudioSystem
    from volumex.safety.journal import Journal
    from volumex.safety.restore import restore_routes

    audio = WindowsAudioSystem(dry_run=os.environ.get("VOLUMEX_DRY_RUN") == "1")
    try:
        pending = restore_routes(audio, Journal(), clear_closed_apps=clear_closed_apps)
    finally:
        audio.close()
    log.info("restore finished; still pending: %s", pending)
    return 0 if not pending else 2

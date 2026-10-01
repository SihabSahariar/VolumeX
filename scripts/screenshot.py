"""Capture every VolumeX screen as PNG for the website, the user manual and the README.

    python scripts/screenshot.py [out_dir]          (default: docs/assets/img)

The real UI runs against the simulated audio system (demo data), so nothing touches real audio or
installs anything. Windows use the native renderer but are never put on screen.
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["VOLUMEX_DATA_DIR"] = tempfile.mkdtemp(prefix="volumex-shots-")
os.environ["VOLUMEX_DEMO"] = "1"

from PyQt5.QtCore import QObject, QRectF, QSize, Qt, QTimer, pyqtSignal  # noqa: E402
from PyQt5.QtGui import QColor, QPainter, QPixmap  # noqa: E402
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QWidget  # noqa: E402

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


class DemoEngine(QObject):
    """Stands in for the engine process: always 'streaming', with lively meters."""

    ready = pyqtSignal(dict)
    stateChanged = pyqtSignal(dict)
    meters = pyqtSignal(dict)
    error = pyqtSignal(str, str)
    stopped = pyqtSignal()
    gaveUp = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.is_ready = False
        self.pid = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self.is_ready = True
        QTimer.singleShot(0, lambda: self.ready.emit({"pid": 0}))

    def shutdown(self, timeout_ms: int = 0) -> None:
        self._timer.stop()

    def reset_crash_budget(self) -> None:
        pass

    def send(self, msg: dict) -> None:
        if msg["cmd"] == "start":
            QTimer.singleShot(0, lambda: self.stateChanged.emit(
                {"streaming": True, "output": "Speakers (Realtek(R) Audio)", "latency_ms": 28.0}))
            self._timer.start(33)

    def _tick(self) -> None:
        t = time.monotonic()
        a = 0.62 + 0.25 * abs(math.sin(t * 2.2))
        self.meters.emit({"peak": [a, a * 0.93], "gr_db": 1.6 if a > 0.8 else 0.0, "underruns": 0})


class Shooter:
    def __init__(self, out: Path) -> None:
        self.out = out
        self.out.mkdir(parents=True, exist_ok=True)
        self.keep: list = []
        self.saved: list[str] = []

    @staticmethod
    def settle(ms: int) -> None:
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            QApplication.processEvents()
            time.sleep(0.005)

    def save(self, pixmap: QPixmap, name: str) -> None:
        path = self.out / f"{name}.png"
        pixmap.save(str(path), "PNG")
        self.saved.append(name)
        print("saved", path)

    def window(self, widget: QWidget, name: str, size: tuple[int, int] | None = None, wait: int = 900) -> None:
        if size:
            widget.resize(*size)
        widget.setAttribute(Qt.WA_DontShowOnScreen)
        widget.show()
        self.settle(wait)
        self.save(widget.grab(), name)
        self.keep.append(widget)

    def hidden(self, widget: QWidget, name: str, wait: int = 600) -> None:
        """Popups (flyout, menus) are rendered without showing them, so they never take the mouse."""
        widget.adjustSize()
        self.settle(wait)
        self.save(widget.grab(), name)
        self.keep.append(widget)

    def part(self, widget: QWidget, name: str) -> None:
        self.save(widget.grab(), name)


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "assets" / "img"
    from volumex.app import _init_qt, _style_app, build_pages

    _init_qt()
    app = QApplication(sys.argv)
    _style_app(app)

    from volumex.core import controller as controller_mod
    from volumex.core.controller import Controller
    from volumex.platform.fake import FakeAudioSystem
    from volumex.safety.journal import Journal
    from volumex.storage.settings import Settings
    from volumex.ui.background import Backdrop
    from volumex.ui.flyout import Flyout
    from volumex.ui.main_window import MainWindow
    from volumex.ui.onboarding import OnboardingDialog
    from volumex.ui.osd import OsdWindow
    from volumex.ui.pages.about_page import AboutPage
    from volumex.ui.pages.automations_page import RuleDialog
    from volumex.ui.pages.settings_page import SettingsPage
    from volumex.ui.shell import SafetyNotice, make_tray_menu
    from volumex.ui.widgets.logo import tray_icon

    controller_mod.STALL_AFTER_S = 0.6  # show "Restart app to boost" without a long wait
    shots = Shooter(out)
    controllers: list[Controller] = []

    def controller(bus: bool = True) -> tuple[Controller, FakeAudioSystem]:
        audio = FakeAudioSystem(with_bus=bus)
        ctrl = Controller(Settings(), Journal(), lambda: audio, real_windows=False, engine=DemoEngine(),
                          foreground=lambda: (4120, CHROME))
        ctrl.start()
        controllers.append(ctrl)
        deadline = time.monotonic() + 5
        while len(ctrl.app_views()) < 5 and time.monotonic() < deadline:
            shots.settle(50)
        return ctrl, audio

    def keys(ctrl: Controller) -> dict[str, str]:
        return {v.name: v.key for v in ctrl.app_views()}

    def boost(ctrl: Controller) -> None:
        k = keys(ctrl)
        ctrl.set_app_gain(k["Google Chrome"], 2.2)
        ctrl.set_app_gain(k["Discord"], 1.35)
        ctrl.set_app_gain(k["Spotify"], 0.45)
        ctrl.set_master(1.0)
        shots.settle(700)

    def main_window(ctrl: Controller, page: int = 0) -> MainWindow:
        win = MainWindow(ctrl, build_pages(ctrl, ctrl.settings, lambda: None, lambda: None))
        win.show_page(page)
        return win

    def full_page(page: QWidget, name: str, height: int) -> None:
        holder = Backdrop()
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(page)
        shots.window(holder, name, (948, height), wait=700)

    size = (1180, 760)

    # -- mixer ----------------------------------------------------------------------------------
    ctrl, audio = controller()
    boost(ctrl)
    win = main_window(ctrl)
    shots.window(win, "hero-mixer", (1280, 800), wait=1500)
    win.resize(*size)
    shots.settle(500)
    shots.save(win.grab(), "mixer")
    mixer = win.stack.widget(0)
    shots.part(mixer.master, "part-master")
    shots.part(mixer.scroll.parentWidget(), "part-apps")

    ctrl, audio = controller()
    boost(ctrl)
    ctrl.set_master(1.5)
    shots.window(main_window(ctrl), "mixer-master-boost", size, wait=1200)

    ctrl, audio = controller()
    k = keys(ctrl)
    ctrl.set_app_gain(k["Google Chrome"], 2.2)
    ctrl.set_app_gain(k["Spotify"], 1.5)  # Spotify ignores live re-routing: "Restart app to boost"
    ctrl.set_app_muted(k["Discord"], True)
    shots.window(main_window(ctrl), "mixer-states", size, wait=2200)

    ctrl, _ = controller(bus=False)
    shots.window(main_window(ctrl), "mixer-setup-needed", size)

    ctrl, audio = controller()
    audio.set_default("fake-bus")
    shots.window(main_window(ctrl), "mixer-fix-default", size, wait=1200)

    ctrl, audio = controller()
    boost(ctrl)
    ctrl.set_boost_enabled(False)
    shots.window(main_window(ctrl), "mixer-paused", size, wait=1200)

    # -- other pages ----------------------------------------------------------------------------
    ctrl, audio = controller()
    boost(ctrl)
    ctrl.add_rule("zoom", "Zoom", keys(ctrl)["Spotify"], "Spotify", 0.3)
    ctrl.add_rule(keys(ctrl)["VALORANT"], "VALORANT", keys(ctrl)["Discord"], "Discord", 1.5)
    shots.window(main_window(ctrl, 1), "devices", size)
    shots.window(main_window(ctrl, 2), "automations", size)
    shots.window(main_window(ctrl, 3), "settings", size)
    shots.window(main_window(ctrl, 4), "about", size)
    full_page(SettingsPage(ctrl, ctrl.settings), "settings-full", 1520)
    full_page(AboutPage(), "about-full", 1080)
    dialog = RuleDialog(ctrl)
    shots.window(dialog, "rule-dialog", (560, dialog.sizeHint().height()))

    # -- tray -----------------------------------------------------------------------------------
    flyout = Flyout(ctrl)
    shots.hidden(flyout, "flyout", wait=900)
    menu, _pause = make_tray_menu(*(lambda *a: None,) * 5)
    shots.hidden(menu, "tray-menu")
    for state in ("normal", "boost", "muted"):
        for light in (False, True):
            shots.save(tray_icon(state, light).pixmap(QSize(32, 32)).scaled(
                64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation), f"tray-{state}-{'light' if light else 'dark'}")

    osd = OsdWindow()
    osd.show_value("Google Chrome", CHROME, 1.8, 3.0)
    shots.hidden(osd, "osd")
    osd = OsdWindow()
    osd.show_value("Master volume", "", 1.4, 3.0)
    shots.hidden(osd, "osd-master")

    # -- first run --------------------------------------------------------------------------------
    ctrl_nobus, _ = controller(bus=False)
    for step, name in ((0, "setup-welcome"), (1, "setup-unlock"), (2, "setup-finish")):
        shots.window(OnboardingDialog(ctrl_nobus, ctrl_nobus.settings, start_step=step), name, (740, 620))
    for state, message, name in (
        ("installing", "Installing - please approve the Windows prompt…", "setup-installing"),
        ("restart", "", "setup-restart"),
    ):
        dialog = OnboardingDialog(ctrl_nobus, ctrl_nobus.settings, start_step=1)
        dialog._cable_state, dialog._cable_message = state, message
        dialog._refresh_cable()
        shots.window(dialog, name, (740, 620))
    ctrl_bus, _ = controller()
    shots.window(OnboardingDialog(ctrl_bus, ctrl_bus.settings, start_step=1), "setup-ready", (740, 620))
    shots.window(SafetyNotice(), "safety-notice")

    # -- social preview (1200x630) --------------------------------------------------------------
    hero = QPixmap(str(out / "hero-mixer.png"))
    card = QPixmap(1200, 630)
    card.fill(QColor("#110D0B"))
    p = QPainter(card)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    target = QRectF(90, 60, 1020, 1020 * hero.height() / hero.width())
    p.drawPixmap(target, hero, QRectF(hero.rect()))
    p.end()
    shots.save(card, "og-image")

    for ctrl in controllers:
        ctrl.shutdown()
    print(f"{len(shots.saved)} images in {out}")


if __name__ == "__main__":
    main()

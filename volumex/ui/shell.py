"""Everything around the windows: tray icon, single instance, hotkeys, notices, clean shutdown."""
from __future__ import annotations

import getpass
import logging
import os

from PyQt5.QtCore import QObject, QRect, QRectF, Qt, QTimer
from PyQt5.QtGui import QCursor, QFont, QPainter
from PyQt5.QtNetwork import QLocalServer, QLocalSocket
from PyQt5.QtWidgets import QAction, QApplication, QDialog, QHBoxLayout, QMenu, QSystemTrayIcon, QVBoxLayout

from volumex import APP_NAME
from volumex.core.controller import Controller, MasterView
from volumex.safety.journal import Journal
from volumex.storage.settings import Settings

from . import theme as T
from .background import paint_backdrop
from .fmt import pct
from .theme import theme
from .widgets.common import GradientButton, label
from .widgets.logo import app_icon, taskbar_is_light, tray_icon
from .win_effects import style_window

log = logging.getLogger(__name__)

DEMO_FOREGROUND = (4120, r"C:\Program Files\Google\Chrome\Application\chrome.exe")


class SafetyNotice(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        from .onboarding import _Tile

        self.setWindowTitle("A quick note about loud audio")
        self.setWindowIcon(app_icon())
        self.setFixedWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 26, 28, 22)
        lay.setSpacing(12)
        lay.addWidget(_Tile("ear", 44))
        lay.addWidget(label("You're boosting above 100%", 15, QFont.DemiBold, display=True))
        lay.addWidget(label("Boosted audio can get very loud, especially on headphones. Raise it slowly and keep it "
                            "at a comfortable level - long exposure to loud sound can harm your hearing.\n\n"
                            "The Distortion Guard keeps boosted sound clean, but it can't make it quieter.",
                            9.5, color=T.TEXT_2, wrap=True))
        row = QHBoxLayout()
        row.addStretch(1)
        ok = GradientButton("Got it")
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        lay.addLayout(row)
        self.setFixedHeight(lay.totalHeightForWidth(460))  # wrapped text needs its full height

    def showEvent(self, e) -> None:
        super().showEvent(e)
        style_window(self)

    def paintEvent(self, _e) -> None:
        paint_backdrop(QPainter(self), QRectF(self.rect()), 0.8)


def make_tray_menu(on_open, on_pause, on_reset, on_settings, on_quit) -> tuple[QMenu, QAction]:
    """The tray icon's right-click menu. Returns the menu and its checkable "Pause boost" action."""
    menu = QMenu()
    menu.setAttribute(Qt.WA_TranslucentBackground)
    menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
    menu.addAction(f"Open {APP_NAME}").triggered.connect(on_open)
    pause = menu.addAction("Pause boost")
    pause.setCheckable(True)
    pause.triggered.connect(on_pause)
    menu.addAction("Reset audio").triggered.connect(on_reset)
    menu.addSeparator()
    menu.addAction("Settings").triggered.connect(on_settings)
    menu.addSeparator()
    menu.addAction(f"Quit {APP_NAME}").triggered.connect(on_quit)
    return menu, pause


class AppShell(QObject):
    def __init__(self, app: QApplication, demo: bool = False, dry_run: bool = False,
                 start_minimized: bool = False) -> None:
        super().__init__()
        self.app = app
        self.demo = demo
        self.dry_run = dry_run
        self.start_minimized = start_minimized
        self._server: QLocalServer | None = None
        self._quitting = False
        self._told_about_tray = False

    # -- single instance -----------------------------------------------------------------------
    def _server_name(self) -> str:
        return f"{APP_NAME}-{getpass.getuser()}" + ("-demo" if self.demo else "")

    def acquire_single_instance(self) -> bool:
        name = self._server_name()
        probe = QLocalSocket()
        probe.connectToServer(name)
        if probe.waitForConnected(300):
            probe.write(b"show\n")
            probe.flush()
            probe.waitForBytesWritten(300)
            probe.disconnectFromServer()
            log.info("another instance is running; asked it to show itself")
            return False
        QLocalServer.removeServer(name)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_instance_message)
        self._server.listen(name)
        return True

    def _on_instance_message(self) -> None:
        sock = self._server.nextPendingConnection() if self._server else None
        if sock is not None:
            sock.readyRead.connect(lambda: self.window.bring_to_front())
            QTimer.singleShot(0, self.window.bring_to_front)

    # -- startup -------------------------------------------------------------------------------
    def start(self) -> None:
        from volumex.app import build_pages

        from .flyout import Flyout
        from .main_window import MainWindow
        from .osd import OsdWindow

        self.settings = Settings.load()
        theme.set_accent(self.settings.ui("accent"))
        self.controller = self._make_controller()

        pages = build_pages(self.controller, self.settings, self.open_setup, self._on_boost_committed)
        self.settings_page = pages[3]
        self.settings_page.hotkeysChanged.connect(self._register_hotkeys)
        self.window = MainWindow(self.controller, pages)
        self.window.closeRequested.connect(self._on_close_requested)
        if self.demo or self.dry_run:
            self.window.setWindowTitle(f"{APP_NAME} - {'demo mode' if self.demo else 'dry run (read-only)'}")
        self.flyout = Flyout(self.controller)
        self.flyout.openMain.connect(self.show_main)
        self.flyout.boostCommitted.connect(self._on_boost_committed)
        self.flyout.lockedHit.connect(lambda: self.open_setup(1))
        self.osd = OsdWindow()

        self._build_tray()
        self._register_hotkeys()

        self.controller.osdRequested.connect(self._on_osd)
        self.controller.notify.connect(self._notify)
        self.controller.backendFailed.connect(lambda msg: self._notify("Can't read Windows audio", msg))
        self.controller.masterChanged.connect(self._update_tray)
        self.controller.appsChanged.connect(lambda _v: self._update_tray(self.controller.master_view()))
        self.app.aboutToQuit.connect(self._shutdown)
        self.app.commitDataRequest.connect(lambda _m: self._shutdown())  # Windows sign-out / shutdown
        self.controller.start()

        if not (self.start_minimized or self.settings.ui("start_minimized")):
            self.window.show()
        if not self.settings.ui("onboarded"):
            QTimer.singleShot(600, lambda: self.open_setup(0))

    def _make_controller(self) -> Controller:
        journal = Journal()
        if self.demo:
            from volumex.platform.fake import FakeAudioSystem

            audio = FakeAudioSystem()
            return Controller(self.settings, journal, lambda: audio, real_windows=False, engine_fake_io=True,
                              foreground=lambda: DEMO_FOREGROUND)
        from volumex.platform.foreground import foreground_process
        from volumex.platform.windows_audio import WindowsAudioSystem

        dry = self.dry_run
        return Controller(self.settings, journal, lambda: WindowsAudioSystem(dry_run=dry), real_windows=True,
                          foreground=foreground_process)

    # -- tray ----------------------------------------------------------------------------------
    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(tray_icon("normal", taskbar_is_light()), self)
        self.tray.setToolTip(APP_NAME)
        menu, self.pause_action = make_tray_menu(
            on_open=self.show_main,
            on_pause=lambda on: self.controller.set_boost_enabled(not on),
            on_reset=self.controller.reset_audio,
            on_settings=lambda: (self.show_main(), self.window.show_page(3)),
            on_quit=self.quit,
        )
        self._menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()
        self._tray_state: tuple = ()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            if self.flyout.isVisible():
                self.flyout.hide()
            else:
                geo = self.tray.geometry()
                if not geo.isValid() or geo.isNull():
                    pos = QCursor.pos()
                    geo = QRect(pos.x() - 8, pos.y() - 8, 16, 16)
                self.flyout.popup_near(geo)
        elif reason == QSystemTrayIcon.DoubleClick:
            self.flyout.hide()
            self.show_main()

    def _update_tray(self, view: MasterView) -> None:
        boosting = any(v.status == "boosted" for v in self.controller.app_views()) or (
            view.value > 1.0 + 1e-3 and view.boost_ready and view.boost_enabled)
        state = ("muted" if view.muted else ("boost" if boosting else "normal"), taskbar_is_light())
        if state != self._tray_state:
            self._tray_state = state
            self.tray.setIcon(tray_icon(*state))
        tip = f"{APP_NAME} · Master {pct(view.value)}"
        if not view.boost_ready:
            tip += " · boost setup needed"
        elif not view.boost_enabled:
            tip += " · boost paused"
        self.tray.setToolTip(tip)
        self.pause_action.setChecked(not view.boost_enabled)

    def _notify(self, title: str, message: str) -> None:
        if self.tray.isVisible():
            self.tray.showMessage(title, message, app_icon(), 4000)

    # -- hotkeys -------------------------------------------------------------------------------
    def _register_hotkeys(self) -> None:
        from volumex.platform.hotkeys import GlobalHotkeys

        if not hasattr(self, "hotkeys"):
            self.hotkeys = GlobalHotkeys(self)
            self.hotkeys.activated.connect(self._on_hotkey)
        self.hotkeys.unregister_all()
        conflicts = set()
        if os.environ.get("VOLUMEX_NO_HOTKEYS") == "1":
            return
        for name, combo in self.settings["hotkeys"].items():
            if combo and not self.hotkeys.register(name, combo):
                conflicts.add(name)
        if conflicts:
            log.warning("hotkeys already taken: %s", conflicts)
        self.settings_page.set_hotkey_conflicts(conflicts)

    def _on_hotkey(self, name: str) -> None:
        c = self.controller
        actions = {
            "focused_up": lambda: c.nudge_focused(0.10),
            "focused_down": lambda: c.nudge_focused(-0.10),
            "focused_reset": c.reset_focused,
            "master_up": lambda: c.nudge_master(0.10),
            "master_down": lambda: c.nudge_master(-0.10),
            "toggle_boost": c.toggle_boost,
        }
        action = actions.get(name)
        if action:
            action()

    def _on_osd(self, title: str, exe: str, value: float, maximum: float) -> None:
        if self.settings.ui("show_osd"):
            self.osd.show_value(title, exe, value, maximum)

    # -- windows ------------------------------------------------------------------------------
    def show_main(self) -> None:
        self.window.bring_to_front()

    def open_setup(self, step: int = 1) -> None:
        from .onboarding import OnboardingDialog

        if getattr(self, "_onboarding", None) and self._onboarding.isVisible():
            self._onboarding.raise_()
            return
        self._onboarding = OnboardingDialog(self.controller, self.settings, start_step=step,
                                            parent=self.window if self.window.isVisible() else None)
        self._onboarding.show()

    def _on_boost_committed(self) -> None:
        if self.settings.ui("safety_notice_shown"):
            return
        self.settings.set_ui("safety_notice_shown", True)
        self.settings.save()
        SafetyNotice(self.window if self.window.isVisible() else None).exec_()

    def _on_close_requested(self) -> None:
        if self.settings.ui("close_to_tray"):
            self.window.hide()
            if not self._told_about_tray:
                self._told_about_tray = True
                self._notify(f"{APP_NAME} is still running", "It keeps your levels in the tray. "
                                                             "Right-click the icon to quit.")
        else:
            self.quit()

    def quit(self) -> None:
        self._shutdown()
        self.app.quit()

    def _shutdown(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        log.info("shutting down")
        if hasattr(self, "hotkeys"):
            self.hotkeys.unregister_all()
        self.flyout.hide()
        self.controller.shutdown()
        self.tray.hide()
        if self._server:
            self._server.close()


"""First-run setup: welcome, unlock boost (VB-CABLE), hearing safety + start with Windows."""
from __future__ import annotations

import math
import subprocess
import time

from PyQt5.QtCore import QRectF, Qt, QTimer, QUrl
from PyQt5.QtGui import QColor, QDesktopServices, QFont, QPainter, QPainterPath
from PyQt5.QtWidgets import QDialog, QHBoxLayout, QMessageBox, QStackedWidget, QVBoxLayout, QWidget

from volumex import APP_NAME
from volumex.core.bus import BUS_PRODUCT_NAME
from volumex.core.controller import AppView, Controller
from volumex.platform import autostart, vbcable
from volumex.storage.settings import Settings

from . import theme as T
from .background import paint_backdrop
from .icons import paint_icon
from .theme import theme
from .widgets.app_row import AppRow
from .vbcable_task import VbCableInstall
from .widgets.common import BusyBar, Card, GhostButton, GradientButton, Pill, ToggleSwitch, label
from .widgets.logo import LogoMark, app_icon
from .win_effects import style_window


class _Tile(QWidget):
    def __init__(self, icon: str, size: int = 40, boost: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon, self._boost = icon, boost
        self.setFixedSize(size, size)
        theme.changed.connect(self.update)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, r.width() * 0.3, r.width() * 0.3)
        grad = (theme.boost_gradient if self._boost else theme.gradient)(r.left(), r.top(), r.right(), r.bottom(),
                                                                         alpha=60)
        p.fillPath(path, grad)
        inset = r.width() * 0.27
        color = theme.boost_color(0.2) if self._boost else theme.accent_color(0.2)
        paint_icon(p, self._icon, r.adjusted(inset, inset, -inset, -inset), color, 2.0)


class _Feature(Card):
    def __init__(self, icon: str, title: str, body: str, boost: bool = False) -> None:
        super().__init__(radius=16, fill=T.rgba(255, 255, 255, 9))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)
        lay.addWidget(_Tile(icon, 38, boost))
        lay.addWidget(label(title, 10, QFont.DemiBold))
        lay.addWidget(label(body, 9, color=T.TEXT_2, wrap=True))
        lay.addStretch(1)


class _Dots(QWidget):
    def __init__(self, count: int) -> None:
        super().__init__()
        self._count, self._index = count, 0
        self.setFixedSize(count * 22, 10)
        theme.changed.connect(self.update)

    def set_index(self, index: int) -> None:
        self._index = index
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        x = 0.0
        for i in range(self._count):
            w = 18.0 if i == self._index else 8.0
            r = QRectF(x, 1, w, 8)
            if i == self._index:
                p.setPen(Qt.NoPen)
                p.setBrush(theme.gradient(r.left(), 0, r.right(), 0))
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 255, 50))
            p.drawRoundedRect(r, 4, 4)
            x += w + 6


class OnboardingDialog(QDialog):
    def __init__(self, controller: Controller, settings: Settings, start_step: int = 0,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.settings = settings
        self.setWindowTitle(f"Welcome to {APP_NAME}")
        self.setWindowIcon(app_icon())
        self.setFixedSize(740, 620)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 32, 36, 26)
        outer.setSpacing(18)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._welcome())
        self.stack.addWidget(self._unlock())
        self.stack.addWidget(self._finish())
        outer.addWidget(self.stack, 1)

        nav = QHBoxLayout()
        self.dots = _Dots(3)
        nav.addWidget(self.dots)
        nav.addStretch(1)
        self.back = GhostButton("Back")
        self.back.clicked.connect(lambda: self._go(self.stack.currentIndex() - 1))
        self.next = GradientButton("Get started", "arrow-right")
        self.next.clicked.connect(self._next)
        nav.addWidget(self.back)
        nav.addWidget(self.next)
        outer.addLayout(nav)

        self._poll = QTimer(self)
        self._poll.timeout.connect(self._refresh_cable)
        self._poll.start(1500)
        controller.masterChanged.connect(lambda _v: self._refresh_cable())
        self._go(start_step)

    # -- pages ---------------------------------------------------------------------------------
    def _welcome(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(LogoMark(64))
        lay.addSpacing(6)
        lay.addWidget(label(f"Welcome to {APP_NAME}", 22, QFont.DemiBold, display=True))
        lay.addWidget(label("Make any app louder than 100% - without distortion. Or turn one down while "
                            "the others keep playing.", 10.5, color=T.TEXT_2, wrap=True))
        lay.addSpacing(12)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(_Feature("zap", "Boost one app or all", "Push a quiet video to 250% while music "
                                                               "stays where it is.", boost=True))
        row.addWidget(_Feature("bookmark", "Remembers every app", "Windows forgets your levels. VolumeX puts them "
                                                                  "back every time an app starts."))
        row.addWidget(_Feature("shield", "Clean, not crunchy", "The Distortion Guard catches peaks before they "
                                                               "clip, so loud stays clear."))
        lay.addLayout(row)
        lay.addSpacing(10)
        lay.addWidget(label("TRY IT - DRAG PAST 100%", 8, QFont.Bold, T.TEXT_3))
        preview = Card(radius=16, fill=T.rgba(255, 255, 255, 9))
        p_lay = QVBoxLayout(preview)
        p_lay.setContentsMargins(4, 4, 4, 4)
        demo = AppView(key="demo", name="A quiet video", exe="", gain=1.8, muted=False, remember=False, active=True,
                       status="boosted", effective=1.8, is_system=False)
        self._demo_row = AppRow(demo)
        self._demo_row.pin_btn.hide()
        self._demo_row.mute_btn.hide()
        self._demo_row.gainChanged.connect(self._on_demo)
        self._demo_row.gainCommitted.connect(self._on_demo)
        p_lay.addWidget(self._demo_row)
        lay.addWidget(preview)
        self._demo_timer = QTimer(self)
        self._demo_timer.timeout.connect(self._animate_demo)
        self._demo_timer.start(40)
        lay.addStretch(1)
        return page

    def _on_demo(self, _key: str, value: float) -> None:
        view = self._demo_row._view
        status = "boosted" if value > 1.0 else "normal"
        self._demo_row.update_view(AppView(view.key, view.name, view.exe, value, False, False, True, status, value,
                                           False), 3.0, True)

    def _animate_demo(self) -> None:
        t = time.monotonic()
        self._demo_row.set_level(0.45 + 0.25 * abs(math.sin(t * 2.3)) + 0.15 * abs(math.sin(t * 5.1)))

    def _unlock(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(_Tile("zap", 48, boost=True))
        lay.addSpacing(4)
        lay.addWidget(label("Unlock boost above 100%", 19, QFont.DemiBold, display=True))
        lay.addWidget(label(f"VolumeX uses {BUS_PRODUCT_NAME}, a free virtual audio device made by VB-Audio. Apps you "
                            "boost play through it so VolumeX can make them louder. Apps you don't boost are never "
                            "touched. One click installs it.", 10, color=T.TEXT_2, wrap=True))
        lay.addSpacing(6)

        card = Card(radius=16, glow=True, fill=T.rgba(255, 255, 255, 10))
        c = QVBoxLayout(card)
        c.setContentsMargins(18, 16, 18, 16)
        c.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(_Tile("package", 40))
        names = QVBoxLayout()
        names.setSpacing(1)
        names.addWidget(label("VB-CABLE Virtual Audio Device", 10.5, QFont.DemiBold))
        names.addWidget(label("Free · made by VB-Audio · donationware", 9, color=T.TEXT_2))
        head.addLayout(names, 1)
        self.cable_pill = Pill("CHECKING…", T.TEXT_2)
        head.addWidget(self.cable_pill)
        c.addLayout(head)
        self.busy = BusyBar()
        self.busy.hide()
        c.addWidget(self.busy)
        self.cable_status = label("", 9.5, color=T.TEXT_2, wrap=True)
        c.addWidget(self.cable_status)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.install_btn = GradientButton("Install VB-CABLE", "download", boost=True)
        self.install_btn.clicked.connect(lambda: self._install_cable(silent=True))
        self.manual_btn = GhostButton("Open VB-CABLE setup", "external")
        self.manual_btn.clicked.connect(lambda: self._install_cable(silent=False))
        self.restart_btn = GradientButton("Restart now", "refresh")
        self.restart_btn.clicked.connect(self._restart_pc)
        for w in (self.install_btn, self.manual_btn, self.restart_btn):
            actions.addWidget(w)
        actions.addStretch(1)
        support = GhostButton("Support VB-Audio", "heart")
        support.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(vbcable.DONATE_URL)))
        actions.addWidget(support)
        c.addLayout(actions)
        lay.addWidget(card)

        link = theme.accent_color(0.2).name()
        fine = label(f"VB-Audio's license lets apps like VolumeX install VB-CABLE for you; by installing it you accept "
                     f"<a href='{vbcable.LICENSE_URL}' style='color:{link}'>VB-Audio's terms</a>. "
                     "Windows asks for permission once.", 8.5, color=T.TEXT_3, wrap=True)
        fine.setTextFormat(Qt.RichText)
        fine.setOpenExternalLinks(True)
        lay.addWidget(fine)
        lay.addStretch(1)
        self._cable_state = "idle"
        self._cable_message = ""
        self._wait_until = 0.0
        return page

    def _install_cable(self, silent: bool) -> None:
        if getattr(self, "_task", None) and self._task.isRunning():
            return
        self._cable_state = "installing"
        self._cable_message = "Getting VB-CABLE ready…"
        self._task = VbCableInstall(silent=silent, parent=self)
        self._task.progress.connect(self._on_install_progress)
        self._task.done.connect(self._on_install_done)
        self._task.start()
        self._refresh_cable()

    def _on_install_progress(self, text: str) -> None:
        self._cable_message = text
        self._refresh_cable()

    def _on_install_done(self, ok: bool, cancelled: bool, message: str) -> None:
        if ok:
            self._cable_state = "waiting"
            self._wait_until = time.monotonic() + 20.0
            self._cable_message = "Installed - switching it on…"
        elif cancelled:
            self._cable_state = "cancelled"
            self._cable_message = "The Windows permission prompt was declined. Click Try again when you're ready."
        else:
            self._cable_state = "failed"
            self._cable_message = f"Couldn't install automatically: {message} You can open VB-Audio's setup instead."
        self._refresh_cable()

    def _restart_pc(self) -> None:
        answer = QMessageBox.question(self, "Restart now?", "Save your work in other apps first. Restart now to "
                                      "finish installing VB-CABLE?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            subprocess.Popen(["shutdown", "/r", "/t", "5", "/c", "Restarting to finish installing VB-CABLE (VolumeX)"],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def _finish(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(_Tile("ear", 48))
        lay.addSpacing(4)
        lay.addWidget(label("One last thing: your ears", 19, QFont.DemiBold, display=True))
        lay.addWidget(label("Boosting makes things much louder. Start low, raise it slowly, and keep headphones at a "
                            "level that's comfortable. Sounds that feel loud for a long time can harm your hearing.",
                            10, color=T.TEXT_2, wrap=True))
        lay.addSpacing(10)
        card = Card(radius=14, fill=T.rgba(255, 255, 255, 9))
        c = QHBoxLayout(card)
        c.setContentsMargins(16, 14, 16, 14)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(label("Start with Windows", 10.5, QFont.DemiBold))
        text.addWidget(label("Keeps your levels applied from the moment you sign in. Runs quietly in the tray.", 9,
                             color=T.TEXT_2, wrap=True))
        c.addLayout(text, 1)
        self.autostart = ToggleSwitch(True)
        c.addWidget(self.autostart)
        lay.addWidget(card)
        tip = Card(radius=14, fill=T.rgba(255, 255, 255, 6))
        t = QHBoxLayout(tip)
        t.setContentsMargins(16, 12, 16, 12)
        t.addWidget(label("Tip: click the VolumeX icon in the tray for a quick mixer, and press Ctrl+Alt+↑ to boost "
                          "whatever app you're using.", 9, color=T.TEXT_2, wrap=True), 1)
        lay.addWidget(tip)
        lay.addStretch(1)
        return page

    # -- flow ----------------------------------------------------------------------------------
    def _go(self, index: int) -> None:
        index = max(0, min(self.stack.count() - 1, index))
        self.stack.setCurrentIndex(index)
        self.dots.set_index(index)
        self.back.setVisible(index > 0)
        self.next.setText(["Get started", "Continue", f"Start using {APP_NAME}"][index])
        self._refresh_cable()

    def _next(self) -> None:
        index = self.stack.currentIndex()
        if index < self.stack.count() - 1:
            self._go(index + 1)
            return
        try:
            if self.autostart.isChecked():
                autostart.enable(autostart.default_command(minimized=True))
            else:
                autostart.disable()
        except OSError:
            pass
        self.settings.set_ui("onboarded", True)
        self.settings.set_ui("safety_notice_shown", True)
        self.settings.save()
        self.accept()

    def _refresh_cable(self) -> None:
        state = self._cable_state
        if self.controller.bus_present:
            state = self._cable_state = "ready"
        elif state == "idle" and vbcable.is_installed():
            state = "restart"  # installed (e.g. by the VolumeX installer) but Windows needs a restart first
        elif state == "waiting" and time.monotonic() > self._wait_until:
            state = self._cable_state = "restart"
        pill, color, text = {
            "ready": ("INSTALLED ✓", T.SUCCESS, "Boost is unlocked. If VB-CABLE is useful to you, consider "
                                                "supporting VB-Audio."),
            "idle": ("NOT INSTALLED", T.WARNING, "Takes about 20 seconds - nothing to download or unzip yourself."),
            "installing": ("INSTALLING", T.WARNING, self._cable_message),
            "waiting": ("FINISHING", T.WARNING, self._cable_message),
            "restart": ("RESTART NEEDED", T.WARNING, "VB-CABLE is installed. Restart your PC to switch it on - "
                                                     "VolumeX detects it automatically afterwards."),
            "cancelled": ("NOT INSTALLED", T.WARNING, self._cable_message),
            "failed": ("NOT INSTALLED", T.DANGER, self._cable_message),
        }[state]
        self.cable_pill.set(pill, color)
        self.cable_status.setText(text)
        self.busy.setVisible(state in ("installing", "waiting"))
        self.install_btn.setVisible(state in ("idle", "cancelled", "failed"))
        self.install_btn.setText("Try again" if state in ("cancelled", "failed") else "Install VB-CABLE")
        self.install_btn.updateGeometry()
        self.manual_btn.setVisible(state == "failed")
        self.restart_btn.setVisible(state == "restart")
        if self.stack.currentIndex() == 1:
            self.next.setText("Continue" if state == "ready" else "I'll do it later")
            self.next.updateGeometry()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        style_window(self)

    def paintEvent(self, _event) -> None:
        paint_backdrop(QPainter(self), QRectF(self.rect()), 1.2)

"""Settings: startup, boost limits, appearance, hotkeys and troubleshooting."""
from __future__ import annotations

from PyQt5.QtCore import QRectF, QSize, Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QColor, QDesktopServices, QFont, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QAbstractButton, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from volumex import about_info
from volumex.core.controller import Controller, MasterView
from volumex.platform import autostart
from volumex.platform.hotkeys import format_combo
from volumex.storage.paths import log_dir
from volumex.storage.settings import DEFAULT_HOTKEYS, Settings

from .. import theme as T
from ..theme import ACCENTS, theme
from ..widgets.common import GhostButton, SegmentedControl, ToggleSwitch, label
from .base import Page, Section, SettingRow

HOTKEY_LABELS = {
    "focused_up": ("Boost the app you're using", "Raises the foreground app by 10%"),
    "focused_down": ("Turn down the app you're using", "Lowers the foreground app by 10%"),
    "focused_reset": ("Reset the app you're using", "Back to 100%"),
    "master_up": ("Master up", "Raises the master by 10%"),
    "master_down": ("Master down", "Lowers the master by 10%"),
    "toggle_boost": ("Pause / resume boost", "Everything back to at most 100%, and back again"),
}

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x1, 0x2, 0x4, 0x8


class AccentSwatch(QAbstractButton):
    def __init__(self, key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(ACCENTS[key].label)
        self.setFixedSize(QSize(64, 70))

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        d = 40.0
        r = QRectF((self.width() - d) / 2, 4, d, d)
        stops = ACCENTS[self.key].stops
        p.setPen(Qt.NoPen)
        p.setBrush(theme.gradient(r.left(), r.top(), r.right(), r.bottom(), stops))
        p.drawEllipse(r)
        if self.isChecked():
            p.setPen(QPen(QColor(T.TEXT), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(r.adjusted(-4, -4, 4, 4))
        elif self.underMouse():
            p.setPen(QPen(QColor(255, 255, 255, 70), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(r.adjusted(-4, -4, 4, 4))
        p.setPen(QColor(T.TEXT if self.isChecked() else T.TEXT_2))
        p.setFont(theme.font(8.5, QFont.DemiBold))
        p.drawText(QRectF(0, r.bottom() + 6, self.width(), 16), Qt.AlignCenter, ACCENTS[self.key].label)

    def enterEvent(self, e) -> None:
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self.update()
        super().leaveEvent(e)


class HotkeyEdit(QAbstractButton):
    """Click, then press a shortcut. Esc cancels, Backspace clears."""

    changed = pyqtSignal(str)

    def __init__(self, combo: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._combo = combo
        self._capturing = False
        self._conflict = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedSize(190, 36)
        self.setFont(theme.font(9.5, QFont.DemiBold))
        self.clicked.connect(self._start)

    def set_combo(self, combo: str, conflict: bool = False) -> None:
        self._combo = combo
        self._conflict = conflict
        self.setToolTip("Another program already uses this shortcut." if conflict else "")
        self.update()

    def _start(self) -> None:
        self._capturing = True
        self.setFocus()
        self.update()

    def focusOutEvent(self, e) -> None:
        self._capturing = False
        self.update()
        super().focusOutEvent(e)

    def keyPressEvent(self, e) -> None:
        if not self._capturing:
            return super().keyPressEvent(e)
        key = e.key()
        if key in (Qt.Key_Control, Qt.Key_Alt, Qt.Key_Shift, Qt.Key_Meta, Qt.Key_AltGr):
            return
        if key == Qt.Key_Escape:
            self._capturing = False
        elif key in (Qt.Key_Backspace, Qt.Key_Delete) and not e.modifiers():
            self._capturing = False
            self._combo = ""
            self.changed.emit("")
        else:
            mods = 0
            m = e.modifiers()
            if m & Qt.ControlModifier:
                mods |= MOD_CONTROL
            if m & Qt.AltModifier:
                mods |= MOD_ALT
            if m & Qt.ShiftModifier:
                mods |= MOD_SHIFT
            if m & Qt.MetaModifier:
                mods |= MOD_WIN
            if not mods & (MOD_CONTROL | MOD_ALT | MOD_WIN):
                return  # needs Ctrl, Alt or Win so normal typing is never hijacked
            vk = e.nativeVirtualKey()
            if not vk:
                return
            self._capturing = False
            self._combo = format_combo(mods, vk)
            self.changed.emit(self._combo)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        p.fillPath(path, T.SURFACE_2)
        if self._capturing:
            p.setPen(QPen(theme.gradient(r.left(), 0, r.right(), 0), 1.6))
        elif self._conflict:
            p.setPen(QPen(QColor(T.WARNING), 1.2))
        else:
            p.setPen(QPen(T.BORDER_STRONG if self.underMouse() else T.BORDER, 1))
        p.drawPath(path)
        p.setFont(self.font())
        if self._capturing:
            p.setPen(theme.accent_color(0.3))
            p.drawText(r, Qt.AlignCenter, "Press a shortcut…")
        elif self._combo:
            p.setPen(QColor(T.WARNING if self._conflict else T.TEXT))
            p.drawText(r, Qt.AlignCenter, self._combo.replace("+", "  +  "))
        else:
            p.setPen(QColor(T.TEXT_3))
            p.drawText(r, Qt.AlignCenter, "Not set")


class SettingsPage(Page):
    setupRequested = pyqtSignal()
    hotkeysChanged = pyqtSignal()

    def __init__(self, controller: Controller, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__("Settings", "Make VolumeX yours.", scroll=True, parent=parent)
        self.controller = controller
        self.settings = settings

        # -- general --
        general = Section("General")
        self.autostart = ToggleSwitch(autostart.is_enabled())
        self.autostart.toggled.connect(self._on_autostart)
        general.content.addWidget(SettingRow("Start with Windows", "VolumeX starts quietly in the tray when you sign in, "
                                             "so your levels are always applied.", self.autostart))
        self.minimized = self._ui_toggle("start_minimized")
        general.content.addWidget(SettingRow("Start minimized", "Open to the tray instead of this window.", self.minimized))
        self.to_tray = self._ui_toggle("close_to_tray")
        general.content.addWidget(SettingRow("Keep running when closed",
                                             "Closing the window keeps boosting from the tray.", self.to_tray))
        self.osd = self._ui_toggle("show_osd")
        general.content.addWidget(SettingRow("On-screen volume display", "Show a small overlay when you use hotkeys.",
                                             self.osd))
        self.body.addWidget(general)

        # -- boost --
        boost = Section("Boost")
        self.max_gain = SegmentedControl([("200%", 2.0), ("300%", 3.0), ("400%", 4.0), ("500%", 5.0)],
                                         float(settings["max_gain"]))
        self.max_gain.setFixedWidth(320)
        self.max_gain.selected.connect(lambda v: controller.set_max_gain(float(v)))
        boost.content.addWidget(SettingRow("Maximum boost", "The highest level any slider can reach. Very high "
                                           "boosts on small speakers can sound harsh.", self.max_gain))
        self.guard = ToggleSwitch(bool(settings["guard"]["enabled"]))
        self.guard.toggled.connect(controller.set_guard)
        boost.content.addWidget(SettingRow("Distortion Guard", "A look-ahead limiter that catches peaks before they "
                                           "clip. Leave it on unless you know why.", self.guard))
        self.body.addWidget(boost)

        # -- appearance --
        look = Section("Appearance", "Pick the glow. Boosted levels always show in warm colours.")
        row = QHBoxLayout()
        row.setSpacing(6)
        self.swatches: list[AccentSwatch] = []
        for key in ACCENTS:
            sw = AccentSwatch(key)
            sw.setChecked(key == theme.accent.key)
            sw.clicked.connect(lambda _=False, k=key: self._pick_accent(k))
            self.swatches.append(sw)
            row.addWidget(sw)
        row.addStretch(1)
        look.content.addLayout(row)
        self.body.addWidget(look)

        # -- hotkeys --
        keys = Section("Hotkeys", "Work anywhere in Windows. Click a shortcut to change it; Backspace clears it.")
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        self.hotkey_edits: dict[str, HotkeyEdit] = {}
        for i, (name, (title, desc)) in enumerate(HOTKEY_LABELS.items()):
            text = QVBoxLayout()
            text.setSpacing(1)
            text.addWidget(label(title, 10, QFont.DemiBold))
            text.addWidget(label(desc, 8.5, color=T.TEXT_3))
            grid.addLayout(text, i, 0)
            edit = HotkeyEdit(settings["hotkeys"].get(name, DEFAULT_HOTKEYS.get(name, "")))
            edit.changed.connect(lambda combo, n=name: self._on_hotkey(n, combo))
            self.hotkey_edits[name] = edit
            grid.addWidget(edit, i, 1, Qt.AlignRight)
        grid.setColumnStretch(0, 1)
        keys.content.addLayout(grid)
        self.body.addWidget(keys)

        # -- troubleshooting --
        trouble = Section("Troubleshooting")
        manual = GhostButton("Open manual", "book-open")
        manual.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(about_info.MANUAL_URL)))
        trouble.content.addWidget(SettingRow("User manual", "Step-by-step help for every screen, plus answers to common "
                                             "problems.", manual))
        reset = GhostButton("Reset audio", "refresh", danger=True)
        reset.clicked.connect(controller.reset_audio)
        trouble.content.addWidget(SettingRow("Reset audio", "Every app back to 100% and boost off. Use it if anything "
                                             "sounds wrong.", reset))
        setup = GhostButton("Run setup", "zap")
        setup.clicked.connect(self.setupRequested)
        trouble.content.addWidget(SettingRow("Boost setup", "Walk through installing VB-CABLE again.", setup))
        logs = GhostButton("Open folder", "folder")
        logs.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir()))))
        trouble.content.addWidget(SettingRow("Log files", "Useful when reporting a problem.", logs))
        self.body.addWidget(trouble)

        self.body.addStretch(1)

        controller.masterChanged.connect(self._on_master)

    def _ui_toggle(self, key: str) -> ToggleSwitch:
        toggle = ToggleSwitch(bool(self.settings.ui(key)))
        toggle.toggled.connect(lambda on: (self.settings.set_ui(key, on), self.settings.save()))
        return toggle

    def _on_autostart(self, on: bool) -> None:
        try:
            if on:
                autostart.enable(autostart.default_command(minimized=True))
            else:
                autostart.disable()
        except OSError:
            self.autostart.set_checked_silent(autostart.is_enabled())

    def _pick_accent(self, key: str) -> None:
        for sw in self.swatches:
            sw.setChecked(sw.key == key)
        theme.set_accent(key)
        self.settings.set_ui("accent", key)
        self.settings.save()

    def _on_hotkey(self, name: str, combo: str) -> None:
        self.settings["hotkeys"][name] = combo
        self.settings.save()
        self.hotkeysChanged.emit()

    def set_hotkey_conflicts(self, conflicts: set[str]) -> None:
        for name, edit in self.hotkey_edits.items():
            edit.set_combo(self.settings["hotkeys"].get(name, ""), name in conflicts)

    def _on_master(self, view: MasterView) -> None:
        self.max_gain.set_value(view.max_gain)
        self.guard.set_checked_silent(view.guard_enabled)


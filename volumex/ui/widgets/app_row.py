"""One app in the mixer.

    [icon]  Google Chrome  [BOOSTED]                    220%  (mute) (remember)
            ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━●━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

A full-width slider on its own line keeps fine control easy even in narrow windows.
"""
from __future__ import annotations

from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath
from PyQt5.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QWidget

from volumex.core.controller import AppView

from .. import theme as T
from ..fmt import pct
from ..theme import theme
from .avatar import AppAvatar
from .boost_slider import BoostSlider
from .common import IconButton, Pill, label
from .meters import EqBars

STATUS_TEXT = {
    "pending": ("Ready to boost", T.TEXT_3),
    "needs_restart": ("Restart app to boost", T.WARNING),
    "locked": ("Setup needed", T.WARNING),
    "paused": ("Boost paused", T.TEXT_3),
}

STATUS_TIPS = {
    "needs_restart": "This app didn't switch to the boost path while it was running.\n"
    "Close and reopen it - it will be boosted from then on.\n"
    "(If the app has its own output-device setting, set it to 'Default'.)",
    "locked": "Install the free VB-CABLE driver to boost apps above 100%.",
    "pending": "VolumeX will boost this app as soon as it plays sound.",
}


class ValueLabel(QLabel):
    """Percentage readout; painted with the boost gradient above 100%."""

    def __init__(self, parent: QWidget | None = None, size: float = 12.5) -> None:
        super().__init__(parent)
        self._value = 1.0
        self.setFont(theme.font(size, QFont.DemiBold, display=True))
        self.setFixedWidth(60)
        theme.changed.connect(self.update)

    def set_value(self, value: float) -> None:
        self._value = value
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(self.font())
        fm = p.fontMetrics()
        text = pct(self._value)
        x = self.width() - fm.horizontalAdvance(text) - 2
        y = (self.height() + fm.ascent() - fm.descent()) / 2
        path = QPainterPath()
        path.addText(x, y, self.font(), text)
        if self._value > 1.0 + 1e-3:
            r = path.boundingRect()
            p.fillPath(path, theme.boost_gradient(r.left(), 0, r.right(), 0))
        else:
            p.fillPath(path, QColor(T.TEXT if self.isEnabled() else T.TEXT_3))


class AppRow(QWidget):
    gainChanged = pyqtSignal(str, float)
    gainCommitted = pyqtSignal(str, float)
    muteToggled = pyqtSignal(str, bool)
    rememberToggled = pyqtSignal(str, bool)
    lockedHit = pyqtSignal()

    def __init__(self, view: AppView, compact: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = view.key
        self._compact = compact
        self._view: AppView | None = None
        self.setAttribute(Qt.WA_Hover)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        grid = QGridLayout(self)
        grid.setContentsMargins(10, 8, 8, 8) if compact else grid.setContentsMargins(14, 10, 12, 10)
        grid.setHorizontalSpacing(10 if compact else 14)
        grid.setVerticalSpacing(0 if compact else 2)

        self.avatar = AppAvatar(view.name, view.exe, view.is_system, size=32 if compact else 42)
        grid.addWidget(self.avatar, 0, 0, 2, 1, Qt.AlignVCenter)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.name = label(view.name, 9.5 if compact else 10.5, QFont.DemiBold)
        self.name.setMinimumWidth(40)
        self.name.setMaximumWidth(150 if compact else 280)
        top.addWidget(self.name)
        self.eq = EqBars()
        self.boost_pill = Pill("BOOSTED", filled=True, boost=True)
        self.status = label("", 8.5, color=T.TEXT_3)
        if not compact:
            top.addSpacing(2)
            top.addWidget(self.eq)
            top.addWidget(self.boost_pill)
            top.addWidget(self.status)
        else:
            for w in (self.eq, self.boost_pill, self.status):
                w.hide()
        top.addStretch(1)
        top.addSpacing(6)
        self.value_label = ValueLabel(size=10.5 if compact else 12)
        top.addWidget(self.value_label)
        self.mute_btn = IconButton("volume", "Mute", checked_icon="volume-x", danger_when_checked=True,
                                   size=26 if compact else 30)
        self.mute_btn.setCheckable(True)
        top.addWidget(self.mute_btn)
        self.pin_btn = IconButton("bookmark", "Remember this app's level", size=30)
        self.pin_btn.setCheckable(True)
        if not compact:
            top.addWidget(self.pin_btn)
        else:
            self.pin_btn.hide()
        grid.addLayout(top, 0, 1)

        self.slider = BoostSlider(compact=compact)
        grid.addWidget(self.slider, 1, 1)
        grid.setColumnStretch(1, 1)

        self.slider.valueChanged.connect(self._on_slider)
        self.slider.valueCommitted.connect(lambda v: self.gainCommitted.emit(self.key, v))
        self.slider.lockedHit.connect(self.lockedHit)
        self.mute_btn.toggled.connect(lambda on: self.muteToggled.emit(self.key, on))
        self.pin_btn.toggled.connect(lambda on: self.rememberToggled.emit(self.key, on))
        self.update_view(view, max_gain=3.0, boost_ready=True)

    def _on_slider(self, v: float) -> None:
        self.value_label.set_value(v)
        self.gainChanged.emit(self.key, v)

    def update_view(self, view: AppView, max_gain: float, boost_ready: bool) -> None:
        old = self._view
        self._view = view
        if old is None or (old.name, old.exe) != (view.name, view.exe):
            self.avatar.set_app(view.name, view.exe, view.is_system)
            self.name.setText(view.name)
            self.name.setToolTip(view.exe or view.name)
        self.slider.set_maximum(1.0 if view.is_system else max_gain)
        self.slider.set_boost_available(boost_ready and not view.is_system)
        self.slider.set_value(view.gain)
        self.slider.set_muted(view.muted)
        if not self.slider._dragging:
            self.value_label.set_value(view.gain)
        for btn, state in ((self.mute_btn, view.muted), (self.pin_btn, view.remember)):
            btn.blockSignals(True)
            btn.setChecked(state)
            btn.blockSignals(False)
            btn.update()
        self.mute_btn.setToolTip("Unmute" if view.muted else "Mute")
        self.pin_btn.setToolTip("Forget this app's level" if view.remember else "Remember this app's level")
        if self._compact:
            return
        self.boost_pill.setVisible(view.status == "boosted" and not view.muted)
        text, color = STATUS_TEXT.get(view.status, ("Playing" if view.active else "Idle", T.TEXT_3))
        if view.muted:
            text, color = "Muted", T.DANGER
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color}; background: transparent;")
        self.status.setToolTip(STATUS_TIPS.get(view.status, ""))
        self.status.setVisible(view.status != "boosted" or view.muted)

    def set_level(self, level: float) -> None:
        self.slider.set_level(level)
        if not self._compact:
            self.eq.set_level(level)

    def paintEvent(self, _event) -> None:
        if not self.underMouse():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 14, 14)
        p.fillPath(path, T.rgba(255, 255, 255, 10))

    def enterEvent(self, e) -> None:
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self.update()
        super().leaveEvent(e)

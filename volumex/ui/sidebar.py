"""Left navigation rail: logo, page buttons and a live boost-engine status card."""
from __future__ import annotations

import time

from PyQt5.QtCore import QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath
from PyQt5.QtWidgets import QAbstractButton, QButtonGroup, QHBoxLayout, QVBoxLayout, QWidget

from volumex import __version__
from volumex.core.controller import EngineView

from . import theme as T
from .icons import paint_icon
from .theme import theme
from .widgets.common import Card, label
from .widgets.logo import BrandLogo

PAGES = [("mixer", "Mixer"), ("speaker", "Devices"), ("zap", "Automations"), ("settings", "Settings"),
         ("info", "About")]


class NavButton(QAbstractButton):
    def __init__(self, icon: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon = icon
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(44)
        self.setFont(theme.font(10, QFont.DemiBold))
        theme.changed.connect(self.update)

    def sizeHint(self) -> QSize:
        return QSize(180, 44)

    def enterEvent(self, e) -> None:
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0, 2, 0, -2)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        if self.isChecked():
            p.fillPath(path, theme.gradient(r.left(), 0, r.right(), 0, alpha=34))
            p.setPen(Qt.NoPen)
            p.setBrush(theme.gradient(0, r.top(), 0, r.bottom()))
            p.drawRoundedRect(QRectF(r.left(), r.top() + 10, 3.5, r.height() - 20), 1.75, 1.75)
        elif self.underMouse():
            p.fillPath(path, T.SURFACE)
        icon_color = theme.accent_color(0.25) if self.isChecked() else QColor(T.TEXT_2)
        paint_icon(p, self._icon, QRectF(r.left() + 16, r.center().y() - 9, 18, 18), icon_color, 2.0)
        p.setPen(QColor(T.TEXT if self.isChecked() else T.TEXT_2))
        p.setFont(self.font())
        p.drawText(r.adjusted(48, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, self.text())


class StatusDot(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(T.TEXT_3)
        self._pulse = False
        self.setFixedSize(12, 12)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)

    def set_state(self, color: str, pulse: bool) -> None:
        self._color = QColor(color)
        self._pulse = pulse
        if pulse:
            self._timer.start(50)
        else:
            self._timer.stop()
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self.rect().center()
        if self._pulse:
            phase = (time.monotonic() % 1.6) / 1.6
            p.setPen(Qt.NoPen)
            p.setBrush(T.with_alpha(self._color, int(110 * (1 - phase))))
            p.drawEllipse(QRectF(c.x() - 2 - 4 * phase, c.y() - 2 - 4 * phase, 4 + 8 * phase, 4 + 8 * phase))
        p.setPen(Qt.NoPen)
        p.setBrush(self._color)
        p.drawEllipse(QRectF(c.x() - 3.5, c.y() - 3.5, 7, 7))


STATUS_STYLE = {
    "streaming": ("Boosting", T.SUCCESS, True),
    "idle": ("Ready", T.SUCCESS, False),
    "starting": ("Starting…", T.WARNING, True),
    "no_bus": ("Setup needed", T.WARNING, False),
    "error": ("Problem", T.DANGER, False),
    "failed": ("Paused", T.DANGER, False),
}


class EngineStatusCard(Card):
    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, radius=14)
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.dot = StatusDot()
        top.addWidget(self.dot)
        top.addWidget(label("Boost engine", 9, QFont.DemiBold, T.TEXT_2))
        top.addStretch(1)
        lay.addLayout(top)
        self.state = label("Starting…", 10.5, QFont.DemiBold)
        self.detail = label("", 8.5, color=T.TEXT_3, wrap=True)
        lay.addWidget(self.state)
        lay.addWidget(self.detail)

    def set_view(self, view: EngineView) -> None:
        text, color, pulse = STATUS_STYLE.get(view.status, ("…", T.TEXT_3, False))
        self.dot.set_state(color, pulse)
        self.state.setText(text)
        if view.status == "streaming" and view.latency_ms:
            detail = f"{view.latency_ms:.0f} ms added delay"
        elif view.status == "no_bus":
            detail = "Install VB-CABLE to boost above 100%"
        elif view.status == "idle":
            detail = "Starts when you boost an app"
        else:
            detail = view.message
        self.detail.setText(detail)
        self.setToolTip(view.message)

    def mousePressEvent(self, _e) -> None:
        self.clicked.emit()


class Sidebar(QWidget):
    pageSelected = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(232)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 22, 18, 18)
        lay.setSpacing(4)

        brand = QHBoxLayout()
        brand.setContentsMargins(4, 0, 0, 0)
        brand.addWidget(BrandLogo(34))
        brand.addStretch(1)
        lay.addLayout(brand)
        lay.addSpacing(28)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: list[NavButton] = []
        for i, (icon, text) in enumerate(PAGES):
            btn = NavButton(icon, text)
            self.group.addButton(btn, i)
            self.buttons.append(btn)
            lay.addWidget(btn)
        self.buttons[0].setChecked(True)
        self.group.buttonClicked[int].connect(self.pageSelected)

        lay.addStretch(1)
        self.status = EngineStatusCard()
        self.status.clicked.connect(lambda: self.select(1))
        lay.addWidget(self.status)
        lay.addSpacing(10)
        lay.addWidget(label(f"v{__version__} · open source (GPL-3.0)", 8, color=T.TEXT_3))

    def select(self, index: int) -> None:
        self.buttons[index].setChecked(True)
        self.pageSelected.emit(index)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(255, 255, 255, 5))
        p.fillRect(QRectF(self.width() - 1, 0, 1, self.height()), QColor(255, 255, 255, 16))

"""On-screen display: a glowing pill near the bottom of the screen when hotkeys change a volume."""
from __future__ import annotations

from PyQt5.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QApplication, QWidget

from . import theme as T
from .fmt import pct
from .theme import theme
from .widgets.avatar import paint_avatar
from .widgets.logo import paint_logo


class OsdWindow(QWidget):
    def __init__(self) -> None:
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowTransparentForInput | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(380, 96)
        self._title = ""
        self._exe = ""
        self._value = 0.0
        self._max = 3.0
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.finished.connect(self._on_faded)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)

    def show_value(self, title: str, exe: str, value: float, max_value: float) -> None:
        self._title, self._exe, self._value, self._max = title, exe, value, max_value
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - self.width() // 2, screen.bottom() - self.height() - int(screen.height() * 0.08))
        self._fade.stop()
        self.setWindowOpacity(1.0)
        self.show()
        self.update()
        self._hide_timer.start(1400)

    def _fade_out(self) -> None:
        self._fade.stop()
        self._fade.setDuration(350)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _on_faded(self) -> None:
        if self.windowOpacity() < 0.05:
            self.hide()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        card = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        path = QPainterPath()
        path.addRoundedRect(card, card.height() / 2, card.height() / 2)
        p.fillPath(path, QColor(16, 19, 38, 236))
        p.setPen(QPen(theme.gradient(card.left(), 0, card.right(), 0, alpha=160), 1.2))
        p.drawPath(path)

        icon = QRectF(card.left() + 16, card.center().y() - 20, 40, 40)
        if self._exe:
            paint_avatar(p, icon, self._title, self._exe)
        else:
            paint_logo(p, icon)
        x = icon.right() + 14
        right = card.right() - 22
        p.setFont(theme.font(10.5, QFont.DemiBold))
        p.setPen(QColor(T.TEXT))
        title = p.fontMetrics().elidedText(self._title, Qt.ElideRight, int(right - x - 70))
        p.drawText(QRectF(x, card.top() + 14, right - x - 64, 22), Qt.AlignLeft | Qt.AlignVCenter, title)
        if self._value < 0:
            return  # message only (e.g. "X isn't playing audio")
        p.setFont(theme.font(12, QFont.DemiBold, display=True))
        value_text = pct(self._value)
        text_path = QPainterPath()
        fm = p.fontMetrics()
        text_path.addText(right - fm.horizontalAdvance(value_text), card.top() + 32, p.font(), value_text)
        r = text_path.boundingRect()
        p.fillPath(text_path, theme.boost_gradient(r.left(), 0, r.right(), 0) if self._value > 1 else QColor(T.TEXT))

        bar = QRectF(x, card.bottom() - 30, right - x, 6)
        track = QPainterPath()
        track.addRoundedRect(bar, 3, 3)
        p.fillPath(track, T.TRACK)
        frac = max(0.0, min(1.0, self._value / max(self._max, 0.01)))
        fill = QPainterPath()
        fill.addRoundedRect(QRectF(bar.left(), bar.top(), max(6.0, bar.width() * frac), bar.height()), 3, 3)
        split = bar.left() + bar.width() / max(self._max, 1.0)
        p.save()
        p.setClipPath(fill)
        p.fillRect(QRectF(bar.left(), bar.top(), split - bar.left(), bar.height()),
                   theme.gradient(bar.left(), 0, split, 0))
        p.fillRect(QRectF(split, bar.top(), bar.right() - split, bar.height()),
                   theme.boost_gradient(split, 0, bar.right(), 0))
        p.restore()
        p.setPen(QPen(QColor(255, 255, 255, 120), 2))
        p.drawLine(int(split), int(bar.top() - 3), int(split), int(bar.bottom() + 3))

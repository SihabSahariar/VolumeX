"""Level meters: a stereo bar meter with peak hold, and tiny "now playing" equaliser bars."""
from __future__ import annotations

import math
import time

from PyQt5.QtCore import QRectF, QSize, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath
from PyQt5.QtWidgets import QSizePolicy, QWidget

from .. import theme as T
from ..theme import theme


class StereoMeter(QWidget):
    """Two slim horizontal bars (L/R) with peak-hold ticks."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._levels = [0.0, 0.0]
        self._peaks = [0.0, 0.0]
        self._peak_time = [0.0, 0.0]
        self.setFixedHeight(26)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFont(theme.font(7, QFont.Bold))
        theme.changed.connect(self.update)

    def sizeHint(self) -> QSize:
        return QSize(200, 26)

    def set_levels(self, left: float, right: float) -> None:
        now = time.monotonic()
        for i, level in enumerate((left, right)):
            level = max(0.0, min(1.0, level))
            cur = self._levels[i]
            self._levels[i] = level if level > cur else cur * 0.8 + level * 0.2
            if level >= self._peaks[i] or now - self._peak_time[i] > 1.2:
                self._peaks[i] = level if level >= self._peaks[i] else self._peaks[i] * 0.9
                self._peak_time[i] = now if level >= self._peaks[i] else self._peak_time[i]
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(self.font())
        label_w = 12
        bar_h = 6.0
        gap = 6.0
        top = (self.height() - (2 * bar_h + gap)) / 2
        x0 = label_w + 4
        width = self.width() - x0 - 2
        for i, name in enumerate(("L", "R")):
            y = top + i * (bar_h + gap)
            p.setPen(QColor(T.TEXT_3))
            p.drawText(QRectF(0, y - 4, label_w, bar_h + 8), Qt.AlignCenter, name)
            bar = QRectF(x0, y, width, bar_h)
            path = QPainterPath()
            path.addRoundedRect(bar, bar_h / 2, bar_h / 2)
            p.fillPath(path, T.TRACK)
            level = self._levels[i]
            if level > 0.003:
                p.save()
                p.setClipPath(path)
                grad = theme.gradient(x0, 0, x0 + width, 0)
                grad.setColorAt(0.82, theme.accent_color(1.0))
                grad.setColorAt(0.9, theme.boost_color(0.2))
                grad.setColorAt(1.0, QColor(T.DANGER))
                p.fillRect(QRectF(x0, y, width * level, bar_h), grad)
                p.restore()
            peak = self._peaks[i]
            if peak > 0.01:
                px = x0 + width * peak
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 255, 200))
                p.drawRoundedRect(QRectF(px - 1.5, y - 1, 3, bar_h + 2), 1.5, 1.5)


class EqBars(QWidget):
    """Three bouncing bars that show an app is making sound; flat dots when silent."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._level = 0.0
        self.setFixedSize(14, 12)
        theme.changed.connect(self.update)

    def set_level(self, level: float) -> None:
        level = max(0.0, min(1.0, level))
        self._level = level if level > self._level else self._level * 0.8 + level * 0.2
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = time.monotonic()
        w, h = 3.0, float(self.height())
        for i in range(3):
            if self._level < 0.02:
                bar_h = 3.0
                color = QColor(T.TEXT_3)
            else:
                wobble = 0.55 + 0.45 * abs(math.sin(t * (5.0 + i * 1.7) + i * 1.3))
                bar_h = max(3.0, h * min(1.0, self._level * 1.4) * wobble)
                color = theme.accent_color(0.2 + i * 0.35)
            x = i * (w + 2.5)
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(x, h - bar_h, w, bar_h), 1.5, 1.5)

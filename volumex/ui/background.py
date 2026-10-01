"""Window backdrop: deep navy gradient with two soft accent "aurora" glows."""
from __future__ import annotations

from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QColor, QLinearGradient, QPainter, QRadialGradient
from PyQt5.QtWidgets import QWidget

from . import theme as T
from .theme import theme


def paint_backdrop(p: QPainter, rect: QRectF, intensity: float = 1.0) -> None:
    base = QLinearGradient(rect.topLeft(), rect.bottomRight())
    base.setColorAt(0.0, QColor(T.BG_TOP))
    base.setColorAt(1.0, QColor(T.BG_BOTTOM))
    p.fillRect(rect, base)
    for center, radius, t, alpha in (
        (QPointF(rect.right() - rect.width() * 0.12, rect.top() + rect.height() * 0.05), rect.width() * 0.55, 0.9, 38),
        (QPointF(rect.left() + rect.width() * 0.28, rect.bottom() + rect.height() * 0.1), rect.width() * 0.6, 0.1, 30),
    ):
        glow = QRadialGradient(center, radius)
        glow.setColorAt(0.0, T.with_alpha(theme.accent_color(t), int(alpha * intensity)))
        glow.setColorAt(1.0, T.with_alpha(theme.accent_color(t), 0))
        p.fillRect(rect, glow)


class Backdrop(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        theme.changed.connect(self.update)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        paint_backdrop(p, QRectF(self.rect()))

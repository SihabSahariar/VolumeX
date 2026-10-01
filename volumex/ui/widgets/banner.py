"""Call-out banner with a glowing gradient border."""
from __future__ import annotations

from PyQt5.QtCore import QRectF, Qt, QVariantAnimation
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath
from PyQt5.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from .. import theme as T
from ..icons import paint_icon
from ..theme import theme
from .common import Card, label


class _IconTile(QWidget):
    def __init__(self, icon: str, boost: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon = icon
        self._boost = boost
        self.setFixedSize(44, 44)
        theme.changed.connect(self.update)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 13, 13)
        grad = (theme.boost_gradient if self._boost else theme.gradient)(r.left(), r.top(), r.right(), r.bottom())
        p.fillPath(path, grad)
        paint_icon(p, self._icon, r.adjusted(12, 12, -12, -12), QColor("#0B0D1A"), 2.4)


class Banner(Card):
    def __init__(self, icon: str, title: str, body: str, actions: list[QWidget] | None = None,
                 boost: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent, radius=16, glow=True, fill=T.rgba(255, 255, 255, 14))
        self._pulse = 0.0
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(14)
        lay.addWidget(_IconTile(icon, boost), 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(3)
        self.title = label(title, 10.5, QFont.DemiBold)
        self.body = label(body, 9, color=T.TEXT_2, wrap=True)
        text.addWidget(self.title)
        text.addWidget(self.body)
        lay.addLayout(text, 1)
        for action in actions or []:
            lay.addWidget(action, 0, Qt.AlignVCenter)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(900)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.valueChanged.connect(self._on_pulse)

    def pulse(self) -> None:
        """Draw attention (e.g. the user hit the locked boost zone)."""
        self._anim.stop()
        self._anim.start()

    def _on_pulse(self, v) -> None:
        self._pulse = float(v)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._pulse > 0.01:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
            path = QPainterPath()
            path.addRoundedRect(r, 16, 16)
            p.fillPath(path, theme.boost_gradient(r.left(), 0, r.right(), 0, alpha=int(60 * self._pulse)))

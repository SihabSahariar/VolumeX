"""App avatars: the program's own icon on a soft tile, or a gradient monogram."""
from __future__ import annotations

import os
from functools import lru_cache

from PyQt5.QtCore import QFileInfo, QRectF, QSize, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PyQt5.QtWidgets import QFileIconProvider, QWidget

from .. import theme as T
from ..icons import paint_icon
from ..theme import theme

_MONO_PALETTES = [
    ("#22D3EE", "#6366F1"),
    ("#F472B6", "#8B5CF6"),
    ("#34D399", "#0EA5E9"),
    ("#FBBF24", "#F43F5E"),
    ("#A78BFA", "#EC4899"),
    ("#2DD4BF", "#84CC16"),
]


@lru_cache(maxsize=256)
def exe_icon(exe: str, size: int = 64) -> QPixmap | None:
    if not exe or not os.path.exists(exe):
        return None
    icon = QFileIconProvider().icon(QFileInfo(exe))
    if icon.isNull():
        return None
    px = icon.pixmap(QSize(size, size))
    return None if px.isNull() else px


def paint_avatar(p: QPainter, rect: QRectF, name: str, exe: str, is_system: bool = False) -> None:
    radius = rect.width() * 0.28
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    if is_system:
        p.fillPath(path, T.SURFACE_2)
        s = rect.width() * 0.52
        paint_icon(p, "volume", QRectF(rect.center().x() - s / 2, rect.center().y() - s / 2, s, s), T.TEXT_2, 2.0)
        return
    px = exe_icon(exe)
    if px is not None:
        p.fillPath(path, T.SURFACE_2)
        s = rect.width() * 0.68
        target = QRectF(rect.center().x() - s / 2, rect.center().y() - s / 2, s, s)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawPixmap(target, px, QRectF(px.rect()))
        return
    c1, c2 = _MONO_PALETTES[sum(map(ord, name)) % len(_MONO_PALETTES)]
    p.fillPath(path, theme.gradient(rect.left(), rect.top(), rect.right(), rect.bottom(), (c1, c2)))
    p.setPen(QColor("#FFFFFF"))
    p.setFont(theme.font(rect.width() * 0.3, QFont.Bold, display=True))
    initial = next((ch for ch in name if ch.isalnum()), "?").upper()
    p.drawText(rect, Qt.AlignCenter, initial)


class AppAvatar(QWidget):
    def __init__(self, name: str = "", exe: str = "", is_system: bool = False, size: int = 38,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name, self._exe, self._system = name, exe, is_system
        self.setFixedSize(size, size)

    def set_app(self, name: str, exe: str, is_system: bool = False) -> None:
        self._name, self._exe, self._system = name, exe, is_system
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        paint_avatar(p, QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), self._name, self._exe, self._system)

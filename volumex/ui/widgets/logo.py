"""VolumeX brand marks, from the official brand kit in volumex/resources/brand.

  app icon    VolumeX-icon.svg (vector) / VolumeX.ico (15 pixel-tuned sizes) - windows, dialogs, installer
  logo        VolumeX-logo-reversed.svg - icon + wordmark for dark backgrounds (sidebar, flyout, About)
  tray        VolumeX-tray-{dark,light}-taskbar.ico - white or dark glyph to match the Windows taskbar
"""
from __future__ import annotations

import winreg
from functools import lru_cache

from PyQt5.QtCore import QRectF, QSize, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import QSizePolicy, QWidget

from volumex.resources import resource

SIGNAL_ORANGE = "#FF5A1F"  # brand kit colours
INK = "#16110E"
BONE = "#F4EFE7"
TRAY_SIZES = (16, 20, 24, 32, 40, 48)


def _brand(name: str) -> str:
    return str(resource("brand") / name)


@lru_cache(maxsize=4)
def _renderer(name: str) -> QSvgRenderer:
    return QSvgRenderer(_brand(name))


def paint_logo(p: QPainter, rect: QRectF) -> None:
    """The app icon, drawn crisp at any size."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    _renderer("VolumeX-icon.svg").render(p, rect)
    p.restore()


@lru_cache(maxsize=1)
def app_icon() -> QIcon:
    return QIcon(_brand("VolumeX.ico"))


def taskbar_is_light() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "SystemUsesLightTheme")[0] == 1
    except OSError:
        return False


@lru_cache(maxsize=8)
def tray_icon(state: str = "normal", light_taskbar: bool = False) -> QIcon:
    """Tray glyph for the taskbar theme. Boosting turns it Signal Orange; muted dims it."""
    base = QIcon(_brand("VolumeX-tray-light-taskbar.ico" if light_taskbar else "VolumeX-tray-dark-taskbar.ico"))
    if state == "normal":
        return base
    icon = QIcon()
    for size in TRAY_SIZES:
        src = base.pixmap(QSize(size, size))
        px = QPixmap(src.size())
        px.fill(Qt.transparent)
        p = QPainter(px)
        if state == "muted":
            p.setOpacity(0.4)
            p.drawPixmap(0, 0, src)
        else:  # boost
            p.drawPixmap(0, 0, src)
            p.setCompositionMode(QPainter.CompositionMode_SourceIn)
            p.fillRect(px.rect(), QColor(SIGNAL_ORANGE))
        p.end()
        icon.addPixmap(px)
    return icon


class LogoMark(QWidget):
    """The app icon on its own."""

    def __init__(self, size: int = 34, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(QSize(size, size))

    def paintEvent(self, _event) -> None:
        paint_logo(QPainter(self), QRectF(self.rect()))


class BrandLogo(QWidget):
    """Icon + "VolumeX" wordmark (reversed version, for dark backgrounds) at a fixed height."""

    def __init__(self, height: int = 32, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._renderer = _renderer("VolumeX-logo-reversed.svg")
        box = self._renderer.viewBoxF()
        self.setFixedSize(QSize(round(height * box.width() / box.height()), height))
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setToolTip("VolumeX")

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._renderer.render(p, QRectF(self.rect()))

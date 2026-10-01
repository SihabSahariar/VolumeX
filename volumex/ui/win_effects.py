"""Native Windows 11 window touches: dark title bar tinted to the app background, rounded corners."""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QWidget

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
DWMWCP_ROUND = 2


def _colorref(color: QColor) -> ctypes.c_uint:
    return ctypes.c_uint(color.red() | (color.green() << 8) | (color.blue() << 16))


def style_window(widget: QWidget, caption: str = "#0B0D1A", text: str = "#EEF0F8", border: str = "#1E2240") -> None:
    if sys.platform != "win32":
        return
    try:
        dwm = ctypes.windll.dwmapi
        hwnd = wintypes.HWND(int(widget.winId()))

        def set_attr(attr: int, value: ctypes._SimpleCData) -> None:
            dwm.DwmSetWindowAttribute(hwnd, ctypes.c_uint(attr), ctypes.byref(value), ctypes.sizeof(value))

        set_attr(DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.c_int(1))
        set_attr(DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.c_int(DWMWCP_ROUND))
        set_attr(DWMWA_CAPTION_COLOR, _colorref(QColor(caption)))
        set_attr(DWMWA_TEXT_COLOR, _colorref(QColor(text)))
        set_attr(DWMWA_BORDER_COLOR, _colorref(QColor(border)))
    except (OSError, AttributeError):
        pass  # older Windows: keep the default frame

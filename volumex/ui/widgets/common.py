"""Small painted building blocks: cards, buttons, toggles, pills, segmented controls."""
from __future__ import annotations

from PyQt5.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt5.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QAbstractButton, QFrame, QHBoxLayout, QLabel, QSizePolicy, QWidget

from .. import theme as T
from ..icons import paint_icon
from ..theme import theme


def label(text: str = "", size: float = 10.0, weight: int = QFont.Normal, color: str = T.TEXT,
          display: bool = False, wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setFont(theme.font(size, weight, display))
    lab.setStyleSheet(f"color: {color}; background: transparent;")
    lab.setWordWrap(wrap)
    return lab


class Card(QFrame):
    """Rounded translucent surface. ``glow=True`` draws an accent-gradient border."""

    def __init__(self, parent: QWidget | None = None, radius: float = 18.0, glow: bool = False,
                 fill: QColor | None = None) -> None:
        super().__init__(parent)
        self._radius = radius
        self._glow = glow
        self._fill = fill
        self.setAttribute(Qt.WA_StyledBackground, False)
        theme.changed.connect(self.update)

    def set_glow(self, glow: bool) -> None:
        self._glow = glow
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self._radius, self._radius)
        p.fillPath(path, self._fill or T.SURFACE)
        # soft top highlight for depth
        hl = QLinearGradient(0, r.top(), 0, r.top() + 90)
        hl.setColorAt(0.0, QColor(255, 255, 255, 10))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillPath(path, hl)
        if self._glow:
            pen = QPen(theme.gradient(r.left(), r.top(), r.right(), r.bottom(), alpha=150), 1.2)
        else:
            pen = QPen(T.BORDER, 1.0)
        p.setPen(pen)
        p.drawPath(path)


class GradientButton(QAbstractButton):
    """Primary call-to-action: accent gradient, rounded, optional leading icon."""

    def __init__(self, text: str, icon: str | None = None, parent: QWidget | None = None, boost: bool = False,
                 stops: tuple[str, ...] | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self._icon = icon
        self._boost = boost
        self._stops = stops  # fixed colours instead of the accent (e.g. another product's brand)
        self.setCursor(Qt.PointingHandCursor)
        self.setFont(theme.font(10, QFont.DemiBold))
        self.setMinimumHeight(40)
        theme.changed.connect(self.update)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        w = fm.horizontalAdvance(self.text()) + 40 + (26 if self._icon else 0)
        return QSize(w, 40)

    def enterEvent(self, e) -> None:
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, 11, 11)
        if self.isEnabled():
            if self._stops:
                grad = theme.gradient(r.left(), 0, r.right(), 0, self._stops)
            else:
                grad = (theme.boost_gradient if self._boost else theme.gradient)(r.left(), 0, r.right(), 0)
            p.fillPath(path, grad)
            if self.isDown():
                p.fillPath(path, QColor(0, 0, 0, 50))
            elif self.underMouse():
                p.fillPath(path, QColor(255, 255, 255, 28))
            text_color = QColor("#0B0D1A")
        else:
            p.fillPath(path, T.SURFACE_2)
            text_color = QColor(T.TEXT_3)
        p.setFont(self.font())
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(self.text())
        total = text_w + (24 if self._icon else 0)
        x = r.center().x() - total / 2
        if self._icon:
            paint_icon(p, self._icon, QRectF(x, r.center().y() - 8, 16, 16), text_color, 2.4)
            x += 24
        p.setPen(text_color)
        p.drawText(QRectF(x, r.top(), text_w + 2, r.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text())


class GhostButton(QAbstractButton):
    """Secondary button: translucent fill, subtle border, optional icon."""

    def __init__(self, text: str, icon: str | None = None, parent: QWidget | None = None,
                 danger: bool = False) -> None:
        super().__init__(parent)
        self.setText(text)
        self._icon = icon
        self._danger = danger
        self.setCursor(Qt.PointingHandCursor)
        self.setFont(theme.font(9.5, QFont.DemiBold))
        self.setMinimumHeight(36)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        w = fm.horizontalAdvance(self.text()) + 32 + (24 if self._icon else 0)
        return QSize(w, 36)

    def enterEvent(self, e) -> None:
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        fill = T.SURFACE_HOVER if self.underMouse() else T.SURFACE_2
        if self.isDown():
            fill = T.rgba(255, 255, 255, 10)
        p.fillPath(path, fill)
        p.setPen(QPen(T.BORDER_STRONG if self.underMouse() else T.BORDER, 1))
        p.drawPath(path)
        color = QColor(T.DANGER if self._danger else (T.TEXT if self.isEnabled() else T.TEXT_3))
        p.setFont(self.font())
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(self.text())
        total = text_w + (22 if self._icon else 0)
        x = r.center().x() - total / 2
        if self._icon:
            paint_icon(p, self._icon, QRectF(x, r.center().y() - 7.5, 15, 15), color, 2.2)
            x += 22
        p.setPen(color)
        p.drawText(QRectF(x, r.top(), text_w + 2, r.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text())


class IconButton(QAbstractButton):
    """Round icon-only button. Checkable variants tint the icon with the accent when on."""

    def __init__(self, icon: str, tooltip: str = "", parent: QWidget | None = None, size: int = 32,
                 checked_icon: str | None = None, danger_when_checked: bool = False) -> None:
        super().__init__(parent)
        self._icon = icon
        self._checked_icon = checked_icon
        self._danger = danger_when_checked
        self.setToolTip(tooltip)
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        theme.changed.connect(self.update)

    def set_icon(self, icon: str) -> None:
        self._icon = icon
        self.update()

    def enterEvent(self, e) -> None:
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.underMouse() or self.isDown():
            p.setPen(Qt.NoPen)
            p.setBrush(T.SURFACE_HOVER if not self.isDown() else T.SURFACE_2)
            p.drawEllipse(r)
        on = self.isCheckable() and self.isChecked()
        name = self._checked_icon if (on and self._checked_icon) else self._icon
        if on:
            color = QColor(T.DANGER) if self._danger else theme.accent_color(0.3)
        else:
            color = QColor(T.TEXT if self.underMouse() else T.TEXT_2)
        s = min(r.width(), r.height()) * 0.5
        paint_icon(p, name, QRectF(r.center().x() - s / 2, r.center().y() - s / 2, s, s), color, 2.0)


class ToggleSwitch(QAbstractButton):
    """iOS-style switch with an animated knob and an accent-gradient track."""

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(44, 24)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)
        theme.changed.connect(self.update)

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def set_checked_silent(self, checked: bool) -> None:
        self.blockSignals(True)
        self.setChecked(checked)
        self.blockSignals(False)
        self._pos = 1.0 if checked else 0.0
        self.update()

    def get_knob(self) -> float:
        return self._pos

    def set_knob(self, value: float) -> None:
        self._pos = value
        self.update()

    knob = pyqtProperty(float, get_knob, set_knob)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        track = QPainterPath()
        track.addRoundedRect(r, r.height() / 2, r.height() / 2)
        p.fillPath(track, T.rgba(255, 255, 255, 34))
        if self._pos > 0:
            p.setOpacity(self._pos if self.isEnabled() else self._pos * 0.4)
            p.fillPath(track, theme.gradient(r.left(), 0, r.right(), 0))
            p.setOpacity(1.0)
        d = r.height() - 6
        x = r.left() + 3 + (r.width() - d - 6) * self._pos
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawEllipse(QRectF(x, r.top() + 4, d, d))
        p.setBrush(QColor("#FFFFFF") if self.isEnabled() else QColor(T.TEXT_3))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))


class Pill(QWidget):
    """Tiny status chip: coloured dot + text, optional gradient fill."""

    def __init__(self, text: str = "", color: str = T.TEXT_2, parent: QWidget | None = None,
                 filled: bool = False, boost: bool = False) -> None:
        super().__init__(parent)
        self._text = text
        self._color = color
        self._filled = filled
        self._boost = boost
        self.setFont(theme.font(8, QFont.Bold))
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        theme.changed.connect(self.update)

    def set(self, text: str, color: str | None = None, filled: bool | None = None, boost: bool | None = None) -> None:
        self._text = text
        if color is not None:
            self._color = color
        if filled is not None:
            self._filled = filled
        if boost is not None:
            self._boost = boost
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(self.fontMetrics().horizontalAdvance(self._text) + (22 if not self._filled else 16), 20)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, r.height() / 2, r.height() / 2)
        if self._filled:
            grad = (theme.boost_gradient if self._boost else theme.gradient)(r.left(), 0, r.right(), 0)
            p.fillPath(path, grad)
            p.setPen(QColor("#0B0D1A"))
            p.setFont(self.font())
            p.drawText(r, Qt.AlignCenter, self._text)
            return
        c = QColor(self._color)
        p.fillPath(path, T.with_alpha(c, 30))
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawEllipse(QPointF(r.left() + 9, r.center().y()), 3, 3)
        p.setPen(c)
        p.setFont(self.font())
        p.drawText(r.adjusted(15, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft, self._text)


class SegmentedControl(QWidget):
    """Row of mutually exclusive options; the selected one gets the accent gradient."""

    selected = pyqtSignal(object)

    def __init__(self, options: list[tuple[str, object]], value: object = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._options = options
        self._value = value if value is not None else options[0][1]
        self._hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFont(theme.font(9.5, QFont.DemiBold))
        self.setFixedHeight(36)
        theme.changed.connect(self.update)

    def value(self) -> object:
        return self._value

    def set_value(self, value: object) -> None:
        self._value = value
        self.update()

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        return QSize(sum(fm.horizontalAdvance(t) + 32 for t, _ in self._options) + 8, 36)

    def _segment_rects(self) -> list[QRectF]:
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        w = r.width() / len(self._options)
        return [QRectF(r.left() + i * w, r.top(), w, r.height()) for i in range(len(self._options))]

    def mouseMoveEvent(self, e) -> None:
        self._hover = next((i for i, r in enumerate(self._segment_rects()) if r.contains(e.pos())), -1)
        self.update()

    def leaveEvent(self, _e) -> None:
        self._hover = -1
        self.update()

    def mousePressEvent(self, e) -> None:
        for (text, value), r in zip(self._options, self._segment_rects()):
            if r.contains(e.pos()) and value != self._value:
                self._value = value
                self.update()
                self.selected.emit(value)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        outer = QPainterPath()
        outer.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 11, 11)
        p.fillPath(outer, T.SURFACE_2)
        p.setPen(QPen(T.BORDER, 1))
        p.drawPath(outer)
        p.setFont(self.font())
        for i, ((text, value), r) in enumerate(zip(self._options, self._segment_rects())):
            seg = QPainterPath()
            seg.addRoundedRect(r, 8, 8)
            if value == self._value:
                p.fillPath(seg, theme.gradient(r.left(), 0, r.right(), 0))
                p.setPen(QColor("#0B0D1A"))
            else:
                if i == self._hover:
                    p.fillPath(seg, T.SURFACE_HOVER)
                p.setPen(QColor(T.TEXT_2))
            p.drawText(r, Qt.AlignCenter, text)


class Divider(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setStyleSheet("background: rgba(255,255,255,18);")


class BusyBar(QWidget):
    """Slim indeterminate progress bar: an accent glow sweeping left to right."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(4)
        self._t = 0.0
        self._anim = QPropertyAnimation(self, b"phase", self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(1300)
        self._anim.setLoopCount(-1)
        theme.changed.connect(self.update)

    def get_phase(self) -> float:
        return self._t

    def set_phase(self, value: float) -> None:
        self._t = value
        self.update()

    phase = pyqtProperty(float, get_phase, set_phase)

    def showEvent(self, e) -> None:
        self._anim.start()
        super().showEvent(e)

    def hideEvent(self, e) -> None:
        self._anim.stop()
        super().hideEvent(e)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        track = QPainterPath()
        track.addRoundedRect(r, r.height() / 2, r.height() / 2)
        p.fillPath(track, T.TRACK)
        w = r.width() * 0.35
        x = -w + (r.width() + w) * self._t
        seg = QPainterPath()
        seg.addRoundedRect(QRectF(x, 0, w, r.height()), r.height() / 2, r.height() / 2)
        p.save()
        p.setClipPath(track)
        p.fillPath(seg, theme.gradient(x, 0, x + w, 0))
        p.restore()


def hbox(*widgets, spacing: int = 8, margins: tuple[int, int, int, int] = (0, 0, 0, 0)) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, int):
            lay.addSpacing(w)
        elif isinstance(w, QWidget):
            lay.addWidget(w)
        else:
            lay.addLayout(w)
    return lay

"""The VolumeX slider: 0-100% in the accent gradient, a "boost zone" beyond a 100% notch,
and a live level meter that lights up the track as the app plays."""
from __future__ import annotations

from PyQt5.QtCore import QEasingCurve, QPoint, QPointF, QRectF, QSize, Qt, QVariantAnimation, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt5.QtWidgets import QSizePolicy, QToolTip, QWidget

from .. import theme as T
from ..fmt import gain_label
from ..theme import theme

SNAP_PX = 7  # magnetic snap to 100% while dragging


class BoostSlider(QWidget):
    valueChanged = pyqtSignal(float)  # while dragging
    valueCommitted = pyqtSignal(float)  # released / wheel / keys
    lockedHit = pyqtSignal()  # user tried to enter the boost zone while boost is unavailable

    def __init__(self, parent: QWidget | None = None, compact: bool = False) -> None:
        super().__init__(parent)
        self._value = 1.0
        self._display = 1.0
        self._max = 3.0
        self._level = 0.0
        self._boost_available = True
        self._muted = False
        self._dragging = False
        self._hover = False
        self._locked_signalled = False
        self._compact = compact
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(26 if compact else 34)
        self.setMinimumWidth(110)
        theme.changed.connect(self.update)

    # -- public API ------------------------------------------------------------------------
    def value(self) -> float:
        return self._value

    def set_value(self, value: float, animate: bool = True) -> None:
        if self._dragging:
            return  # never fight the user's hand
        value = max(0.0, min(self._max, value))
        if abs(value - self._value) < 1e-4:
            return
        self._value = value
        if animate and self.isVisible():
            self._anim.stop()
            self._anim.setStartValue(float(self._display))
            self._anim.setEndValue(float(value))
            self._anim.start()
        else:
            self._display = value
            self.update()

    def set_maximum(self, maximum: float) -> None:
        self._max = max(1.0, maximum)
        self._value = min(self._value, self._max)
        self._display = min(self._display, self._max)
        self.update()

    def set_level(self, level: float) -> None:
        level = max(0.0, min(1.0, level))
        # fast attack, smooth release - reads like a real meter
        self._level = level if level > self._level else self._level * 0.82 + level * 0.18
        self.update()

    def set_boost_available(self, available: bool) -> None:
        self._boost_available = available
        self.update()

    def set_muted(self, muted: bool) -> None:
        self._muted = muted
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(260, self.height())

    # -- geometry ----------------------------------------------------------------------------
    @property
    def _pad(self) -> float:
        return 11.0 if not self._compact else 9.0

    def _x(self, v: float) -> float:
        return self._pad + (self.width() - 2 * self._pad) * v / self._max

    def _v(self, x: float) -> float:
        return (x - self._pad) / max(1.0, self.width() - 2 * self._pad) * self._max

    def _on_anim(self, v) -> None:
        self._display = float(v)
        self.update()

    # -- interaction ---------------------------------------------------------------------------
    def _set(self, v: float, commit: bool) -> None:
        v = round(max(0.0, min(self._max, v)) * 100) / 100
        if not self._boost_available and v > 1.0:
            v = 1.0
            if not self._locked_signalled:
                self._locked_signalled = True
                self.lockedHit.emit()
        changed = abs(v - self._value) > 1e-4
        self._anim.stop()
        self._value = v
        self._display = v
        self.update()
        if changed:
            self.valueChanged.emit(v)
        if commit:
            self.valueCommitted.emit(v)

    def _set_from_x(self, x: float) -> None:
        v = self._v(x)
        if abs(x - self._x(1.0)) < SNAP_PX:
            v = 1.0
        self._set(v, commit=False)
        QToolTip.showText(self.mapToGlobal(QPoint(int(self._x(self._value)), -6)), gain_label(self._value), self)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._dragging = True
            self._locked_signalled = False
            self._set_from_x(e.x())

    def mouseMoveEvent(self, e) -> None:
        if self._dragging:
            self._set_from_x(e.x())
            return
        near = abs(e.x() - self._x(self._display)) < 14
        if near != self._hover:
            self._hover = near
            self.update()
        if near:
            QToolTip.showText(self.mapToGlobal(QPoint(int(self._x(self._value)), -6)), gain_label(self._value), self)

    def mouseReleaseEvent(self, e) -> None:
        if self._dragging and e.button() == Qt.LeftButton:
            self._dragging = False
            self._locked_signalled = False
            self.valueCommitted.emit(self._value)
            self.update()

    def mouseDoubleClickEvent(self, _e) -> None:
        self._dragging = False
        self._set(1.0, commit=True)

    def wheelEvent(self, e) -> None:
        steps = e.angleDelta().y() / 120.0
        step = 0.10 if e.modifiers() & Qt.ControlModifier else 0.02
        self._locked_signalled = False
        self._set(self._value + steps * step, commit=True)
        e.accept()

    def keyPressEvent(self, e) -> None:
        key = e.key()
        self._locked_signalled = False
        moves = {Qt.Key_Left: -0.01, Qt.Key_Down: -0.01, Qt.Key_Right: 0.01, Qt.Key_Up: 0.01,
                 Qt.Key_PageUp: 0.10, Qt.Key_PageDown: -0.10}
        if key in moves:
            self._set(self._value + moves[key], commit=True)
        elif key == Qt.Key_Home:
            self._set(0.0, commit=True)
        elif key == Qt.Key_End:
            self._set(self._max if self._boost_available else 1.0, commit=True)
        else:
            super().keyPressEvent(e)

    def enterEvent(self, e) -> None:
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(e)

    # -- painting ------------------------------------------------------------------------------
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._muted or not self.isEnabled():
            p.setOpacity(0.42)
        h = self.height()
        cy = h / 2
        th = 5.0 if self._compact else 6.0
        x0 = self._pad
        x100 = self._x(1.0)
        xmax = self._x(self._max)
        xv = self._x(self._display)
        track = QRectF(x0 - th / 2, cy - th / 2, xmax - x0 + th, th)
        track_path = QPainterPath()
        track_path.addRoundedRect(track, th / 2, th / 2)

        # base track and boost zone
        p.fillPath(track_path, T.TRACK)
        zone = QRectF(x100, track.top(), track.right() - x100, th)
        p.save()
        p.setClipPath(track_path)
        if self._boost_available:
            p.fillRect(zone, T.with_alpha(theme.boost_color(0.35), 30))
        else:
            p.fillRect(zone, QBrush(QColor(255, 255, 255, 30), Qt.BDiagPattern))
        p.restore()

        # fill up to the set value, then the lit (meter) part on top
        fill = QPainterPath()
        fill.addRoundedRect(QRectF(track.left(), track.top(), max(th, xv - track.left() + th / 2), th), th / 2, th / 2)
        lit_end = x0 + (xv - x0) * (0.0 if self._muted else self._level)
        in_boost = self._display > 1.0 + 1e-3
        glow_color = theme.boost_color(min(1.0, (self._display - 1) / max(0.01, self._max - 1))) if in_boost \
            else theme.accent_color(min(1.0, self._display))
        if lit_end > x0 + 1:
            p.setPen(QPen(T.with_alpha(glow_color, 46), th + 7, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(x0, cy), QPointF(lit_end, cy))
        for alpha, end in ((105, xv + th / 2), (255, lit_end)):
            if end <= track.left() + 0.5:
                continue
            p.save()
            p.setClipPath(fill)
            p.setClipRect(QRectF(track.left(), 0, end - track.left(), h), Qt.IntersectClip)
            p.fillRect(QRectF(track.left(), track.top(), x100 - track.left(), th),
                       theme.gradient(x0, 0, x100, 0, alpha=alpha))
            if xv > x100:
                p.fillRect(QRectF(x100, track.top(), track.right() - x100, th),
                           theme.boost_gradient(x100, 0, xmax, 0, alpha=alpha))
            p.restore()

        # 100% notch
        p.setPen(QPen(QColor(255, 255, 255, 110), 2, Qt.SolidLine, Qt.RoundCap))
        notch = 5 if self._compact else 6
        p.drawLine(QPointF(x100, cy - th / 2 - notch), QPointF(x100, cy + th / 2 + notch))

        # handle
        r = (6.5 if self._compact else 8.0) + (1.5 if self._dragging else (1.0 if self._hover else 0.0))
        halo = QRadialGradient(QPointF(xv, cy), r * 2.6)
        halo.setColorAt(0.0, T.with_alpha(glow_color, 120 if self._dragging else 80))
        halo.setColorAt(1.0, T.with_alpha(glow_color, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QPointF(xv, cy), r * 2.6, r * 2.6)
        p.setBrush(QColor("#F8F9FF"))
        p.drawEllipse(QPointF(xv, cy), r, r)
        p.setPen(QPen(glow_color, 2.4))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(xv, cy), r - 1.2, r - 1.2)
        p.setPen(Qt.NoPen)
        p.setBrush(glow_color)
        p.drawEllipse(QPointF(xv, cy), 2.4, 2.4)
        if self.hasFocus():
            p.setPen(QPen(T.with_alpha(glow_color, 90), 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(xv, cy), r + 3.5, r + 3.5)

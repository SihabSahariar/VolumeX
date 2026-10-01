"""Big circular master control: a 270° gradient arc that turns "hot" past 100%,
with a live output-level ring inside and the value in the middle."""
from __future__ import annotations

import math

from PyQt5.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt5.QtWidgets import QSizePolicy, QToolTip, QWidget

from .. import theme as T
from ..fmt import db, gain_label
from ..theme import theme

START = 225.0  # degrees, Qt convention (counter-clockwise from 3 o'clock)
SPAN = 270.0


class MasterDial(QWidget):
    valueChanged = pyqtSignal(float)
    valueCommitted = pyqtSignal(float)
    lockedHit = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = 1.0
        self._display = 1.0
        self._max = 3.0
        self._level = 0.0
        self._boost_available = True
        self._muted = False
        self._dragging = False
        self._locked_signalled = False
        self._caption = "MASTER"
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        theme.changed.connect(self.update)

    def sizeHint(self) -> QSize:
        return QSize(250, 250)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        return w

    # -- public API ----------------------------------------------------------------------------
    def value(self) -> float:
        return self._value

    def set_value(self, value: float, animate: bool = True) -> None:
        if self._dragging:
            return
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
        self._level = level if level > self._level else self._level * 0.85 + level * 0.15
        self.update()

    def set_boost_available(self, available: bool) -> None:
        self._boost_available = available
        self.update()

    def set_muted(self, muted: bool) -> None:
        self._muted = muted
        self.update()

    def _on_anim(self, v) -> None:
        self._display = float(v)
        self.update()

    # -- geometry ------------------------------------------------------------------------------
    def _geometry(self) -> tuple[QPointF, float, float]:
        side = min(self.width(), self.height())
        center = QPointF(self.width() / 2, self.height() / 2 + side * 0.02)
        ring = max(10.0, side * 0.058)
        radius = side / 2 - ring - 10
        return center, radius, ring

    def _angle(self, v: float) -> float:
        return START - SPAN * v / self._max

    def _point(self, center: QPointF, radius: float, angle: float) -> QPointF:
        rad = math.radians(angle)
        return QPointF(center.x() + radius * math.cos(rad), center.y() - radius * math.sin(rad))

    def _value_at(self, pos: QPointF) -> float:
        center, _, _ = self._geometry()
        angle = math.degrees(math.atan2(center.y() - pos.y(), pos.x() - center.x()))
        t = (START - angle) % 360.0
        if t > SPAN:  # in the gap at the bottom: pick the nearer end
            t = SPAN if t < SPAN + (360 - SPAN) / 2 else 0.0
        return t / SPAN * self._max

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
        self._value = self._display = v
        self.update()
        if changed:
            self.valueChanged.emit(v)
        if commit:
            self.valueCommitted.emit(v)

    def _drag_to(self, pos: QPointF) -> None:
        v = self._value_at(pos)
        if self._dragging and abs(v - self._value) > self._max * 0.5:
            return  # don't jump across the gap
        if abs(v - 1.0) < self._max * 0.018:
            v = 1.0
        self._set(v, commit=False)
        QToolTip.showText(self.mapToGlobal(pos.toPoint()), gain_label(self._value), self)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._locked_signalled = False
            self._dragging = False
            self._drag_to(QPointF(e.pos()))
            self._dragging = True

    def mouseMoveEvent(self, e) -> None:
        if self._dragging:
            self._drag_to(QPointF(e.pos()))

    def mouseReleaseEvent(self, e) -> None:
        if self._dragging:
            self._dragging = False
            self.valueCommitted.emit(self._value)
            self.update()

    def mouseDoubleClickEvent(self, _e) -> None:
        self._dragging = False
        self._set(1.0, commit=True)

    def wheelEvent(self, e) -> None:
        self._locked_signalled = False
        step = 0.10 if e.modifiers() & Qt.ControlModifier else 0.02
        self._set(self._value + e.angleDelta().y() / 120.0 * step, commit=True)
        e.accept()

    def keyPressEvent(self, e) -> None:
        moves = {Qt.Key_Left: -0.01, Qt.Key_Down: -0.01, Qt.Key_Right: 0.01, Qt.Key_Up: 0.01,
                 Qt.Key_PageUp: 0.10, Qt.Key_PageDown: -0.10}
        self._locked_signalled = False
        if e.key() in moves:
            self._set(self._value + moves[e.key()], commit=True)
        else:
            super().keyPressEvent(e)

    # -- painting ------------------------------------------------------------------------------
    def _color_at(self, v: float) -> QColor:
        if v <= 1.0:
            return theme.accent_color(v)
        return theme.boost_color((v - 1.0) / max(0.01, self._max - 1.0))

    def _arc(self, p: QPainter, center: QPointF, radius: float, v0: float, v1: float) -> None:
        rect = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
        a0 = self._angle(v0)
        span = -(SPAN * (v1 - v0) / self._max)
        p.drawArc(rect, round(a0 * 16), round(span * 16))

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        center, R, ring = self._geometry()
        side = min(self.width(), self.height())
        dim = self._muted or not self.isEnabled()

        # inner disc with depth
        inner_r = R - ring * 0.9
        disc = QRadialGradient(center - QPointF(0, inner_r * 0.4), inner_r * 1.4)
        disc.setColorAt(0.0, QColor("#1C2140"))
        disc.setColorAt(1.0, QColor("#0C0F1F"))
        p.setPen(QPen(QColor(255, 255, 255, 20), 1))
        p.setBrush(disc)
        p.drawEllipse(center, inner_r, inner_r)

        # scale dots every 25%
        steps = int(round(self._max / 0.25))
        for i in range(steps + 1):
            v = i * 0.25
            pt = self._point(center, R + ring * 0.95, self._angle(v))
            major = abs(v - round(v)) < 1e-6
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 110 if major else 45))
            p.drawEllipse(pt, 1.9 if major else 1.2, 1.9 if major else 1.2)

        # track + boost zone underlay
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(T.TRACK, ring, Qt.SolidLine, Qt.RoundCap))
        self._arc(p, center, R, 0.0, self._max)
        if self._boost_available:
            p.setPen(QPen(T.with_alpha(theme.boost_color(0.4), 34), ring, Qt.SolidLine, Qt.FlatCap))
        else:
            p.setPen(QPen(QColor(255, 255, 255, 40), 1.4, Qt.DashLine))
        self._arc(p, center, R, 1.0, self._max)

        # value arc: soft glow, then gradient segments
        v = self._display
        if dim:
            p.setOpacity(0.45)
        if v > 0.005:
            end_color = self._color_at(v)
            p.setPen(QPen(T.with_alpha(end_color, 34), ring * 2.3, Qt.SolidLine, Qt.RoundCap))
            self._arc(p, center, R, 0.0, v)
            segments = max(2, int(120 * v / self._max))
            for i in range(segments):
                s0 = v * i / segments
                s1 = v * (i + 1) / segments + (0.004 if i < segments - 1 else 0.0)
                p.setPen(QPen(self._color_at((s0 + s1) / 2), ring, Qt.SolidLine, Qt.FlatCap))
                self._arc(p, center, R, s0, s1)
            p.setPen(Qt.NoPen)
            p.setBrush(self._color_at(0.0))
            p.drawEllipse(self._point(center, R, self._angle(0.0)), ring / 2, ring / 2)

        # live level ring
        level_r = R - ring * 1.35
        p.setPen(QPen(QColor(255, 255, 255, 12), 3, Qt.SolidLine, Qt.RoundCap))
        rect = QRectF(center.x() - level_r, center.y() - level_r, level_r * 2, level_r * 2)
        p.drawArc(rect, round(START * 16), round(-SPAN * 16))
        if self._level > 0.01 and not self._muted:
            p.setPen(QPen(T.with_alpha(theme.accent_color(0.2 + 0.8 * self._level), 190), 3, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(rect, round(START * 16), round(-SPAN * self._level * 16))

        # 100% marker
        p.setOpacity(1.0)
        a100 = self._angle(1.0)
        p.setPen(QPen(QColor(255, 255, 255, 150), 2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(self._point(center, R - ring / 2 - 3, a100), self._point(center, R + ring / 2 + 3, a100))
        p.setFont(theme.font(max(6.5, side * 0.030), QFont.DemiBold))
        p.setPen(QColor(T.TEXT_3))
        lp = self._point(center, R + ring + 12, a100)
        p.drawText(QRectF(lp.x() - 24, lp.y() - 8, 48, 16), Qt.AlignCenter, "100%")

        # knob
        if dim:
            p.setOpacity(0.6)
        kp = self._point(center, R, self._angle(v))
        kc = self._color_at(v)
        halo = QRadialGradient(kp, ring * 1.6)
        halo.setColorAt(0.0, T.with_alpha(kc, 150))
        halo.setColorAt(1.0, T.with_alpha(kc, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(kp, ring * 1.6, ring * 1.6)
        p.setBrush(QColor("#F8F9FF"))
        p.drawEllipse(kp, ring * 0.62, ring * 0.62)
        p.setBrush(kc)
        p.drawEllipse(kp, ring * 0.26, ring * 0.26)
        p.setOpacity(1.0)

        # text
        p.setPen(QColor(T.TEXT_3))
        p.setFont(theme.font(max(6.5, side * 0.034), QFont.Bold))
        p.drawText(QRectF(center.x() - 80, center.y() - side * 0.25, 160, side * 0.07), Qt.AlignCenter, self._caption)

        number = f"{round(v * 100)}"
        big = theme.font(max(18.0, side * 0.145), QFont.DemiBold, display=True)
        small = theme.font(max(9.0, side * 0.06), QFont.DemiBold, display=True)
        p.setFont(big)
        fm_big = p.fontMetrics()
        p.setFont(small)
        fm_small = p.fontMetrics()
        total = fm_big.horizontalAdvance(number) + fm_small.horizontalAdvance("%") + 2
        x = center.x() - total / 2
        base = center.y() + fm_big.ascent() * 0.36
        path = QPainterPath()
        path.addText(QPointF(x, base), big, number)
        path.addText(QPointF(x + fm_big.horizontalAdvance(number) + 2, base), small, "%")
        rect = path.boundingRect()
        if v > 1.0 + 1e-3:
            p.fillPath(path, theme.boost_gradient(rect.left(), 0, rect.right(), 0))
        else:
            p.fillPath(path, QColor(T.TEXT))

        sub_y = base + side * 0.035
        p.setFont(theme.font(max(7.0, side * 0.04), QFont.DemiBold))
        if self._muted:
            p.setPen(QColor(T.DANGER))
            p.drawText(QRectF(center.x() - 80, sub_y, 160, side * 0.08), Qt.AlignCenter, "MUTED")
        elif v > 1.0 + 1e-3:
            label_text = f"BOOST  {db(v)}"
            fm = p.fontMetrics()
            w = fm.horizontalAdvance(label_text) + 20
            pill = QRectF(center.x() - w / 2, sub_y + 2, w, side * 0.075)
            pill_path = QPainterPath()
            pill_path.addRoundedRect(pill, pill.height() / 2, pill.height() / 2)
            p.fillPath(pill_path, theme.boost_gradient(pill.left(), 0, pill.right(), 0, alpha=60))
            p.setPen(QColor(T.TEXT))
            p.drawText(pill, Qt.AlignCenter, label_text)
        else:
            p.setPen(QColor(T.TEXT_2))
            p.drawText(QRectF(center.x() - 80, sub_y, 160, side * 0.08), Qt.AlignCenter, "Windows volume")

"""Mixer: the master dial and every app that is making sound, each with its own boost slider."""
from __future__ import annotations

from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath
from PyQt5.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from volumex.core.controller import AppView, Controller, EngineView, MasterView

from .. import theme as T
from ..fmt import pct
from ..icons import paint_icon
from ..theme import theme
from ..widgets.app_row import AppRow
from ..widgets.banner import Banner
from ..widgets.common import Card, GradientButton, Pill, ToggleSwitch, label
from ..widgets.master_dial import MasterDial
from ..widgets.meters import StereoMeter
from .base import Page


class DeviceChip(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = ""
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(38)
        self.setFont(theme.font(9.5, QFont.DemiBold))
        self.setToolTip("Output device (change it in Windows sound settings)")

    def set_text(self, text: str) -> None:
        self._text = text
        self.setFixedWidth(min(360, self.fontMetrics().horizontalAdvance(text) + 58))
        self.update()

    def mousePressEvent(self, _e) -> None:
        self.clicked.emit()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, r.height() / 2, r.height() / 2)
        p.fillPath(path, T.SURFACE_2)
        p.setPen(T.BORDER)
        p.drawPath(path)
        name = self._text.lower()
        icon = "headphones" if ("headphone" in name or "headset" in name) else "speaker"
        paint_icon(p, icon, QRectF(r.left() + 14, r.center().y() - 8, 16, 16), theme.accent_color(0.3), 2.0)
        p.setPen(QColor(T.TEXT))
        p.setFont(self.font())
        text = p.fontMetrics().elidedText(self._text, Qt.ElideRight, int(r.width() - 52))
        p.drawText(r.adjusted(40, 0, -14, 0), Qt.AlignVCenter | Qt.AlignLeft, text)


class EmptyState(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 40, 20, 40)
        lay.setSpacing(8)
        lay.addStretch(1)
        self._icon_box = QWidget()
        self._icon_box.setFixedSize(64, 64)
        self._icon_box.paintEvent = self._paint_icon  # type: ignore[assignment]
        lay.addWidget(self._icon_box, 0, Qt.AlignHCenter)
        lay.addSpacing(6)
        lay.addWidget(label("Nothing is playing yet", 12, QFont.DemiBold), 0, Qt.AlignHCenter)
        hint = label("Apps show up here as soon as they make a sound.\nPlay a video or a song to try boosting it.",
                     9.5, color=T.TEXT_2)
        hint.setAlignment(Qt.AlignCenter)
        lay.addWidget(hint, 0, Qt.AlignHCenter)
        lay.addStretch(1)

    def _paint_icon(self, _event) -> None:
        p = QPainter(self._icon_box)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self._icon_box.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, 20, 20)
        p.fillPath(path, theme.gradient(r.left(), r.top(), r.right(), r.bottom(), alpha=46))
        paint_icon(p, "music", r.adjusted(18, 18, -18, -18), theme.accent_color(0.4), 2.0)


class QuickChips(QWidget):
    """One-click master presets: 100% / 150% / 200% / max."""

    picked = pyqtSignal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._values: list[float] = [1.0, 1.5, 2.0, 3.0]
        self._current = 1.0
        self._hover = -1
        self._locked = False
        self.setFixedHeight(34)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFont(theme.font(9, QFont.DemiBold))
        theme.changed.connect(self.update)

    def set_state(self, current: float, max_gain: float, locked: bool) -> None:
        self._values = [v for v in (1.0, 1.5, 2.0) if v < max_gain] + [max_gain]
        self._current = current
        self._locked = locked
        self.update()

    def _rects(self) -> list[QRectF]:
        gap = 8.0
        w = (self.width() - gap * (len(self._values) - 1)) / len(self._values)
        return [QRectF(i * (w + gap), 0.5, w, self.height() - 1) for i in range(len(self._values))]

    def mouseMoveEvent(self, e) -> None:
        self._hover = next((i for i, r in enumerate(self._rects()) if r.contains(e.pos())), -1)
        self.update()

    def leaveEvent(self, _e) -> None:
        self._hover = -1
        self.update()

    def mousePressEvent(self, e) -> None:
        for value, r in zip(self._values, self._rects()):
            if r.contains(e.pos()):
                self.picked.emit(value)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(self.font())
        for i, (value, r) in enumerate(zip(self._values, self._rects())):
            path = QPainterPath()
            path.addRoundedRect(r, 10, 10)
            selected = abs(value - self._current) < 0.005
            boost = value > 1.0
            if selected:
                grad = (theme.boost_gradient if boost else theme.gradient)(r.left(), 0, r.right(), 0)
                p.fillPath(path, grad)
                p.setPen(QColor("#0B0D1A"))
            else:
                p.fillPath(path, T.SURFACE_HOVER if i == self._hover else T.SURFACE_2)
                p.setPen(T.BORDER)
                p.drawPath(path)
                p.setPen(QColor(T.TEXT_3 if (boost and self._locked) else T.TEXT_2))
            p.drawText(r, Qt.AlignCenter, pct(value))


class MasterCard(Card):
    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent, radius=20, glow=True)
        self.controller = controller
        self._boost_ok = True
        self.setFixedWidth(318)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(12)

        head = QHBoxLayout()
        head.addWidget(label("Master", 12, QFont.DemiBold))
        head.addStretch(1)
        self.state_pill = Pill("", T.TEXT_2)
        head.addWidget(self.state_pill)
        lay.addLayout(head)

        self.dial = MasterDial()
        self.dial.setMinimumSize(250, 250)
        lay.addWidget(self.dial, 1)
        self.chips = QuickChips()
        lay.addWidget(self.chips)
        lay.addSpacing(2)

        meter_head = QHBoxLayout()
        meter_head.addWidget(label("OUTPUT", 7.5, QFont.Bold, T.TEXT_3))
        meter_head.addStretch(1)
        self.guard_label = label("", 8, QFont.DemiBold, T.TEXT_3)
        meter_head.addWidget(self.guard_label)
        lay.addLayout(meter_head)
        self.meter = StereoMeter()
        lay.addWidget(self.meter)
        lay.addSpacing(4)

        self.guard = ToggleSwitch(True)
        self.boost = ToggleSwitch(True)
        lay.addLayout(self._toggle_row("shield", "Distortion Guard", "Keeps boosted sound clean", self.guard))
        lay.addLayout(self._toggle_row("zap", "Boost", "Allow volumes above 100%", self.boost))

        self.dial.valueChanged.connect(controller.set_master)
        self.dial.valueCommitted.connect(controller.set_master)
        self.chips.picked.connect(self._on_chip)
        self.guard.toggled.connect(controller.set_guard)
        self.boost.toggled.connect(controller.set_boost_enabled)

    def _toggle_row(self, icon: str, title: str, subtitle: str, toggle: ToggleSwitch) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        tile = QWidget()
        tile.setFixedSize(34, 34)

        def paint(_e, tile=tile, icon=icon) -> None:
            p = QPainter(tile)
            p.setRenderHint(QPainter.Antialiasing)
            r = QRectF(tile.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            path = QPainterPath()
            path.addRoundedRect(r, 10, 10)
            p.fillPath(path, T.SURFACE_2)
            paint_icon(p, icon, r.adjusted(9, 9, -9, -9), theme.accent_color(0.3), 2.0)

        tile.paintEvent = paint  # type: ignore[assignment]
        theme.changed.connect(tile.update)
        row.addWidget(tile)
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addWidget(label(title, 9.5, QFont.DemiBold))
        text.addWidget(label(subtitle, 8.5, color=T.TEXT_3))
        row.addLayout(text, 1)
        row.addWidget(toggle)
        return row

    def _on_chip(self, value: float) -> None:
        if value > 1.0 and not self._boost_ok:
            self.dial.lockedHit.emit()
            return
        self.controller.set_master(value)
        self.dial.valueCommitted.emit(value)

    def update_master(self, view: MasterView) -> None:
        self._boost_ok = view.boost_ready and view.boost_enabled
        self.chips.set_state(view.value, view.max_gain, not self._boost_ok)
        self.dial.set_maximum(view.max_gain)
        self.dial.set_boost_available(view.boost_ready and view.boost_enabled)
        self.dial.set_value(view.value)
        self.dial.set_muted(view.muted)
        self.guard.set_checked_silent(view.guard_enabled)
        self.boost.set_checked_silent(view.boost_enabled)
        if not view.boost_ready:
            self.state_pill.set("SETUP NEEDED", T.WARNING, filled=False)
        elif not view.boost_enabled:
            self.state_pill.set("BOOST PAUSED", T.TEXT_3, filled=False)
        elif view.value > 1.0 + 1e-3:
            self.state_pill.set(f"BOOST {pct(view.value)}", filled=True, boost=True)
        else:
            self.state_pill.set("NORMAL", T.SUCCESS, filled=False)

    def update_meters(self, msg: dict) -> None:
        peak = msg.get("peak") or [0.0, 0.0]
        self.meter.set_levels(float(peak[0]), float(peak[1]))
        gr = float(msg.get("gr_db", 0.0))
        if gr > 0.3:
            self.guard_label.setText(f"GUARD ACTIVE  −{gr:.1f} dB")
            self.guard_label.setStyleSheet(f"color: {theme.boost_color(0.3).name()}; background: transparent;")
        else:
            self.guard_label.setText("")


class MixerPage(Page):
    showDevices = pyqtSignal()
    setupRequested = pyqtSignal()
    boostCommitted = pyqtSignal()  # a value above 100% was chosen (safety notice hook)

    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__("Mixer", "Make any app louder than 100%, or turn it down - each one on its own.", parent=parent)
        self.controller = controller
        self._rows: dict[str, AppRow] = {}
        self._engine_streaming = False
        self._boost_ready = True
        self._max_gain = 3.0

        self.device_chip = DeviceChip()
        self.device_chip.clicked.connect(self.showDevices)
        self.header_right.addWidget(self.device_chip)

        body = QHBoxLayout()
        body.setSpacing(18)
        self.master = MasterCard(controller)
        body.addWidget(self.master)
        self.master.dial.valueCommitted.connect(lambda v: v > 1.0 and self.boostCommitted.emit())
        self.master.dial.lockedHit.connect(self._on_locked)

        apps = Card(radius=20)
        apps_lay = QVBoxLayout(apps)
        apps_lay.setContentsMargins(14, 18, 14, 14)
        apps_lay.setSpacing(12)
        head = QHBoxLayout()
        head.setContentsMargins(10, 0, 10, 0)
        head.addWidget(label("Apps", 12, QFont.DemiBold))
        self.count = Pill("0 playing", T.TEXT_2)
        head.addWidget(self.count)
        head.addStretch(1)
        head.addWidget(label("Drag, scroll or use arrow keys  ·  double-click = 100%", 8.5, color=T.TEXT_3))
        apps_lay.addLayout(head)

        setup_btn = GradientButton("Unlock boost", "zap", boost=True)
        setup_btn.clicked.connect(self.setupRequested)
        self.banner = Banner(
            "zap",
            "Unlock boost above 100%",
            "One click installs VB-CABLE, a free virtual audio device by VB-Audio. It only carries the apps you "
            "boost - everything else plays exactly as before.",
            [setup_btn],
        )
        fix_btn = GradientButton("Fix it", "check", boost=True)
        fix_btn.clicked.connect(controller.fix_default_device)
        self.default_banner = Banner(
            "alert",
            "All sound is going into VB-CABLE",
            "Windows made the virtual cable your default output, so you may hear nothing. "
            "VolumeX can switch it back to your speakers or headphones.",
            [fix_btn],
        )
        wrap = QVBoxLayout()
        wrap.setContentsMargins(6, 0, 6, 0)
        wrap.setSpacing(10)
        wrap.addWidget(self.default_banner)
        wrap.addWidget(self.banner)
        apps_lay.addLayout(wrap)
        self.banner.hide()
        self.default_banner.hide()

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        self.list = QVBoxLayout(holder)
        self.list.setContentsMargins(0, 0, 4, 0)
        self.list.setSpacing(2)
        self.list.addStretch(1)
        self.scroll.setWidget(holder)
        apps_lay.addWidget(self.scroll, 1)
        self.empty = EmptyState()
        apps_lay.addWidget(self.empty, 1)
        body.addWidget(apps, 1)
        self.body.addLayout(body, 1)

        controller.appsChanged.connect(self.set_apps)
        controller.peaksChanged.connect(self.set_peaks)
        controller.masterChanged.connect(self.set_master)
        controller.engineChanged.connect(self.set_engine)
        controller.engineMeters.connect(self._on_engine_meters)
        self.set_master(controller.master_view())
        self.set_engine(controller.engine_view())
        self.set_apps(controller.app_views())

    # -- updates from the controller ---------------------------------------------------------
    def set_master(self, view: MasterView) -> None:
        self._boost_ready = view.boost_ready and view.boost_enabled
        self._max_gain = view.max_gain
        self.master.update_master(view)
        self.device_chip.set_text(view.device_name)
        self.banner.setVisible(not view.boost_ready)
        self.default_banner.setVisible(view.default_is_bus)
        self.subtitle.setText(
            f"Make any app louder - up to {pct(view.max_gain)} - or turn it down, each one on its own."
        )
        for row in self._rows.values():
            if row._view:
                row.update_view(row._view, self._max_gain, self._boost_ready)

    def set_engine(self, view: EngineView) -> None:
        self._engine_streaming = view.status == "streaming"

    def set_apps(self, views: list[AppView]) -> None:
        keys = [v.key for v in views]
        for key in list(self._rows):
            if key not in keys:
                row = self._rows.pop(key)
                self.list.removeWidget(row)
                row.deleteLater()
        for index, view in enumerate(views):
            row = self._rows.get(view.key)
            if row is None:
                row = AppRow(view)
                row.gainChanged.connect(self.controller.set_app_gain)
                row.gainCommitted.connect(self._on_gain_committed)
                row.muteToggled.connect(self.controller.set_app_muted)
                row.rememberToggled.connect(self.controller.set_app_remember)
                row.lockedHit.connect(self._on_locked)
                self._rows[view.key] = row
            self.list.insertWidget(index, row)
            row.update_view(view, self._max_gain, self._boost_ready)
        playing = sum(1 for v in views if v.active)
        self.count.set(f"{playing} playing" if playing else f"{len(views)} apps", T.SUCCESS if playing else T.TEXT_2)
        self.empty.setVisible(not views)
        self.scroll.setVisible(bool(views))

    def set_peaks(self, levels: dict[str, float]) -> None:
        for key, row in self._rows.items():
            row.set_level(levels.get(key, 0.0))
        loudest = max(levels.values(), default=0.0)
        self.master.dial.set_level(loudest)
        if not self._engine_streaming:
            self.master.meter.set_levels(loudest, loudest * 0.96)

    def _on_engine_meters(self, msg: dict) -> None:
        if self._engine_streaming:
            self.master.update_meters(msg)

    def _on_gain_committed(self, key: str, value: float) -> None:
        self.controller.set_app_gain(key, value)
        if value > 1.0:
            self.boostCommitted.emit()

    def _on_locked(self) -> None:
        self.banner.pulse()

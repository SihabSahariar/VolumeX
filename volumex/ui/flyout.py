"""Tray flyout: a compact mixer that pops up above the tray icon."""
from __future__ import annotations

from PyQt5.QtCore import QPoint, QRect, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QFont, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from volumex.core.controller import AppView, Controller, MasterView

from . import theme as T
from .background import paint_backdrop
from .fmt import pct
from .theme import theme
from .widgets.app_row import AppRow, ValueLabel
from .widgets.boost_slider import BoostSlider
from .widgets.common import IconButton, Pill, ToggleSwitch, label
from .widgets.logo import BrandLogo

MARGIN = 14  # room for the drop shadow


class Flyout(QWidget):
    openMain = pyqtSignal()
    boostCommitted = pyqtSignal()
    lockedHit = pyqtSignal()

    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.controller = controller
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(392)
        self._rows: dict[str, AppRow] = {}
        self._max_gain = 3.0
        self._boost_ready = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(MARGIN + 18, MARGIN + 16, MARGIN + 18, MARGIN + 16)
        outer.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        titles.addWidget(BrandLogo(22))
        self.device = label("", 8.5, color=T.TEXT_3)
        titles.addWidget(self.device)
        head.addLayout(titles, 1)
        open_btn = IconButton("maximize", "Open VolumeX")
        open_btn.clicked.connect(self._open_main)
        head.addWidget(open_btn)
        outer.addLayout(head)

        master_row = QHBoxLayout()
        master_row.setSpacing(10)
        master_row.addWidget(label("MASTER", 8, QFont.Bold, T.TEXT_3))
        self.state = Pill("")
        master_row.addWidget(self.state)
        master_row.addStretch(1)
        self.master_value = ValueLabel(size=13)
        master_row.addWidget(self.master_value)
        outer.addLayout(master_row)
        self.master = BoostSlider()
        self.master.valueChanged.connect(self._on_master_drag)
        self.master.valueCommitted.connect(self._on_master_commit)
        self.master.lockedHit.connect(self.lockedHit)
        outer.addWidget(self.master)

        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: rgba(255,255,255,20);")
        outer.addWidget(sep)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        self.list = QVBoxLayout(holder)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(0)
        self.list.addStretch(1)
        self.scroll.setWidget(holder)
        outer.addWidget(self.scroll, 1)
        self.empty = label("Nothing is playing right now.", 9.5, color=T.TEXT_3)
        self.empty.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.empty)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        foot.addWidget(label("Boost", 9.5, QFont.DemiBold, T.TEXT_2))
        self.boost_toggle = ToggleSwitch(True)
        self.boost_toggle.toggled.connect(controller.set_boost_enabled)
        foot.addWidget(self.boost_toggle)
        foot.addSpacing(10)
        foot.addWidget(label("Guard", 9.5, QFont.DemiBold, T.TEXT_2))
        self.guard_toggle = ToggleSwitch(True)
        self.guard_toggle.toggled.connect(controller.set_guard)
        foot.addWidget(self.guard_toggle)
        foot.addStretch(1)
        settings_btn = IconButton("settings", "Settings")
        settings_btn.clicked.connect(self._open_main)
        foot.addWidget(settings_btn)
        outer.addLayout(foot)

        controller.appsChanged.connect(self.set_apps)
        controller.peaksChanged.connect(self.set_peaks)
        controller.masterChanged.connect(self.set_master)
        self.set_master(controller.master_view())
        self.set_apps(controller.app_views())

    # -- data ---------------------------------------------------------------------------------
    def set_master(self, view: MasterView) -> None:
        self._max_gain = view.max_gain
        self._boost_ready = view.boost_ready and view.boost_enabled
        self.device.setText(view.device_name)
        self.master.set_maximum(view.max_gain)
        self.master.set_boost_available(self._boost_ready)
        self.master.set_value(view.value)
        self.master.set_muted(view.muted)
        if not self.master._dragging:
            self.master_value.set_value(view.value)
        self.boost_toggle.set_checked_silent(view.boost_enabled)
        self.guard_toggle.set_checked_silent(view.guard_enabled)
        if not view.boost_ready:
            self.state.set("SETUP NEEDED", T.WARNING, filled=False)
        elif not view.boost_enabled:
            self.state.set("PAUSED", T.TEXT_3, filled=False)
        elif view.value > 1.0 + 1e-3:
            self.state.set(f"BOOST {pct(view.value)}", filled=True, boost=True)
        else:
            self.state.set("NORMAL", T.SUCCESS, filled=False)
        for row in self._rows.values():
            if row._view:
                row.update_view(row._view, self._max_gain, self._boost_ready)

    def set_apps(self, views: list[AppView]) -> None:
        views = [v for v in views if not v.is_system]
        keys = [v.key for v in views]
        for key in list(self._rows):
            if key not in keys:
                row = self._rows.pop(key)
                self.list.removeWidget(row)
                row.deleteLater()
        for index, view in enumerate(views):
            row = self._rows.get(view.key)
            if row is None:
                row = AppRow(view, compact=True)
                row.gainChanged.connect(self.controller.set_app_gain)
                row.gainCommitted.connect(self._on_gain_committed)
                row.muteToggled.connect(self.controller.set_app_muted)
                row.lockedHit.connect(self.lockedHit)
                self._rows[view.key] = row
            self.list.insertWidget(index, row)
            row.update_view(view, self._max_gain, self._boost_ready)
        self.empty.setVisible(not views)
        self.scroll.setVisible(bool(views))
        rows_height = min(len(views), 5) * 66
        self.scroll.setFixedHeight(max(66, rows_height))
        self.adjustSize()

    def set_peaks(self, levels: dict[str, float]) -> None:
        if not self.isVisible():
            return
        for key, row in self._rows.items():
            row.set_level(levels.get(key, 0.0))
        self.master.set_level(max(levels.values(), default=0.0))

    def _on_master_drag(self, value: float) -> None:
        self.master_value.set_value(value)
        self.controller.set_master(value)

    def _on_master_commit(self, value: float) -> None:
        self.controller.set_master(value)
        if value > 1.0:
            self.boostCommitted.emit()

    def _on_gain_committed(self, key: str, value: float) -> None:
        self.controller.set_app_gain(key, value)
        if value > 1.0:
            self.boostCommitted.emit()

    def _open_main(self) -> None:
        self.hide()
        self.openMain.emit()

    # -- placement ------------------------------------------------------------------------------
    def popup_near(self, anchor: QRect) -> None:
        """Show above (or next to) the tray icon, inside the screen's work area."""
        self.adjustSize()
        screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        w, h = self.width(), self.height()
        if anchor.isNull() or not anchor.isValid():
            x, y = area.right() - w, area.bottom() - h
        else:
            x = min(max(anchor.center().x() - w // 2, area.left()), area.right() - w)
            y = anchor.top() - h if anchor.top() - h >= area.top() else anchor.bottom()
            y = min(max(y, area.top()), area.bottom() - h)
            if anchor.left() > area.right() or anchor.right() < area.left():
                x = area.right() - w
        self.move(QPoint(x, y))
        self.show()
        self.raise_()
        self.activateWindow()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        card = QRectF(self.rect()).adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)
        for i in range(MARGIN, 0, -2):  # soft shadow
            shadow = QPainterPath()
            shadow.addRoundedRect(card.adjusted(-i, -i + 4, i, i + 4), 20 + i, 20 + i)
            p.fillPath(shadow, T.rgba(0, 0, 0, int(34 * (1 - i / MARGIN) ** 2)))
        path = QPainterPath()
        path.addRoundedRect(card, 20, 20)
        p.save()
        p.setClipPath(path)
        paint_backdrop(p, card, 1.4)
        p.restore()
        p.setPen(QPen(theme.gradient(card.left(), card.top(), card.right(), card.bottom(), alpha=140), 1.2))
        p.drawPath(path)

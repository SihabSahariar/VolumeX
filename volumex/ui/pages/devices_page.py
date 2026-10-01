"""Devices: output devices with their remembered boost, and the boost engine's health."""
from __future__ import annotations

from PyQt5.QtCore import QRectF, Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices, QFont, QPainter, QPainterPath
from PyQt5.QtWidgets import QComboBox, QHBoxLayout, QVBoxLayout, QWidget

from volumex.platform import vbcable
from volumex.core.controller import Controller, DeviceView, EngineView, MasterView

from .. import theme as T
from ..fmt import pct
from ..icons import paint_icon
from ..theme import theme
from ..widgets.common import Card, GhostButton, GradientButton, Pill, label
from .base import Page, Section, SettingRow


def device_icon(name: str) -> str:
    n = name.lower()
    if any(w in n for w in ("headphone", "headset", "earbud", "airpods", "buds")):
        return "headphones"
    if any(w in n for w in ("hdmi", "display", "monitor", "tv", "nvidia", "amd high definition")):
        return "monitor"
    if "bluetooth" in n or "hands-free" in n:
        return "bluetooth"
    return "speaker"


class IconTile(QWidget):
    def __init__(self, icon: str, size: int = 40, active: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon = icon
        self._active = active
        self.setFixedSize(size, size)
        theme.changed.connect(self.update)

    def set_icon(self, icon: str, active: bool) -> None:
        self._icon, self._active = icon, active
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, r.width() * 0.3, r.width() * 0.3)
        if self._active:
            p.fillPath(path, theme.gradient(r.left(), r.top(), r.right(), r.bottom()))
            color = T.BG_TOP
        else:
            p.fillPath(path, T.SURFACE_2)
            color = theme.accent_color(0.3).name()
        inset = r.width() * 0.28
        paint_icon(p, self._icon, r.adjusted(inset, inset, -inset, -inset), color, 2.0)


class DeviceRow(Card):
    def __init__(self, view: DeviceView, parent: QWidget | None = None) -> None:
        super().__init__(parent, radius=14, fill=T.rgba(255, 255, 255, 8))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 16, 12)
        lay.setSpacing(14)
        lay.addWidget(IconTile(device_icon(view.name), 40, view.is_default))
        text = QVBoxLayout()
        text.setSpacing(2)
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_row.addWidget(label(view.name, 10.5, QFont.DemiBold))
        if view.is_default:
            name_row.addWidget(Pill("IN USE", T.SUCCESS))
        name_row.addStretch(1)
        text.addLayout(name_row)
        detail = "Windows default output" if view.is_default else "Switch to it in Windows and VolumeX follows"
        text.addWidget(label(detail, 9, color=T.TEXT_3))
        lay.addLayout(text, 1)
        boost = label("Master boost", 8.5, color=T.TEXT_3)
        boost.setAlignment(Qt.AlignRight)
        value = label(pct(view.boost) if view.boost > 1.0 else "None", 11, QFont.DemiBold,
                      theme.boost_color(0.3).name() if view.boost > 1.0 else T.TEXT_2)
        value.setAlignment(Qt.AlignRight)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(boost)
        col.addWidget(value)
        lay.addLayout(col)


class HealthRow(QWidget):
    def __init__(self, icon: str, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(14)
        self.tile = IconTile(icon, 36)
        lay.addWidget(self.tile)
        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(label(title, 10, QFont.DemiBold))
        self.detail = label("", 9, color=T.TEXT_2, wrap=True)
        text.addWidget(self.detail)
        lay.addLayout(text, 1)
        self.pill = Pill("")
        lay.addWidget(self.pill)
        self.action_box = QHBoxLayout()
        lay.addLayout(self.action_box)

    def set(self, detail: str, pill: str, color: str) -> None:
        self.detail.setText(detail)
        self.pill.set(pill, color)


class StepCard(Card):
    def __init__(self, number: int, title: str, body: str, parent: QWidget | None = None) -> None:
        super().__init__(parent, radius=14, fill=T.rgba(255, 255, 255, 8))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 16)
        lay.setSpacing(6)
        badge = Pill(str(number), filled=True)
        badge.setFixedWidth(26)
        lay.addWidget(badge)
        lay.addWidget(label(title, 10, QFont.DemiBold))
        lay.addWidget(label(body, 9, color=T.TEXT_2, wrap=True))
        lay.addStretch(1)


class DevicesPage(Page):
    setupRequested = pyqtSignal()

    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__("Devices", "Where your sound goes - and how VolumeX boosts it.", scroll=True, parent=parent)
        self.controller = controller

        self.devices = Section("Output devices",
                               "VolumeX remembers a master boost for each device and re-applies it when you switch.")
        self.device_list = QVBoxLayout()
        self.device_list.setSpacing(8)
        self.devices.content.addLayout(self.device_list)
        self.body.addWidget(self.devices)

        engine = Section("Boost engine", "The part of VolumeX that makes boosted apps louder.")
        self.cable = HealthRow("activity", "VB-CABLE by VB-Audio")
        self.get_cable = GradientButton("Install", "download", boost=True)
        self.get_cable.clicked.connect(self.setupRequested)
        self.support_cable = GhostButton("Support VB-Audio", "heart")
        self.support_cable.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(vbcable.DONATE_URL)))
        self.cable.action_box.addWidget(self.get_cable)
        self.cable.action_box.addWidget(self.support_cable)
        self.engine_row = HealthRow("cpu", "Engine")
        self.delay_row = HealthRow("clock", "Added delay for boosted apps")
        engine.content.addWidget(self.cable)
        engine.content.addWidget(self.engine_row)
        engine.content.addWidget(self.delay_row)
        self.output = QComboBox()
        self.output.setMinimumWidth(280)
        self.output.activated.connect(self._on_output_picked)
        engine.content.addWidget(SettingRow("Boosted audio plays on",
                                            "Normally the device Windows is using. Pick one to pin it.", self.output))
        self.body.addWidget(engine)

        how = Section("How boosting works", "Plain and simple - and nothing changes for apps you don't boost.")
        steps = QHBoxLayout()
        steps.setSpacing(12)
        steps.addWidget(StepCard(1, "You boost an app", "Drag its slider past 100%. Apps at 100% or below stay "
                                                        "exactly as Windows plays them."))
        steps.addWidget(StepCard(2, "It takes the boost path", "That app is sent through the VB-CABLE virtual "
                                                               "device, which nobody hears directly."))
        steps.addWidget(StepCard(3, "VolumeX makes it louder", "The engine raises the level, the Distortion Guard "
                                                              "catches peaks, and it plays on your speakers."))
        how.content.addLayout(steps)
        self.body.addWidget(how)
        self.body.addStretch(1)

        controller.devicesChanged.connect(self.set_devices)
        controller.engineChanged.connect(self.set_engine)
        controller.masterChanged.connect(self._on_master)
        self.set_devices(controller.device_views())
        self.set_engine(controller.engine_view())
        self._on_master(controller.master_view())

    def set_devices(self, views: list[DeviceView]) -> None:
        while self.device_list.count():
            item = self.device_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for view in sorted(views, key=lambda v: (not v.is_default, v.name.lower())):
            self.device_list.addWidget(DeviceRow(view))
        if not views:
            self.device_list.addWidget(label("No active output devices found.", 9.5, color=T.TEXT_2))
        current = self.controller.settings["engine"].get("output")
        self.output.blockSignals(True)
        self.output.clear()
        self.output.addItem("Follow Windows default", None)
        for view in views:
            self.output.addItem(view.name, view.id)
        index = self.output.findData(current)
        self.output.setCurrentIndex(max(0, index))
        self.output.blockSignals(False)

    def _on_output_picked(self, index: int) -> None:
        self.controller.set_output_device(self.output.itemData(index))

    def _on_master(self, view: MasterView) -> None:
        if view.boost_ready or self.controller.bus_present:
            self.cable.set("Installed - boosted apps are routed through it automatically. "
                           "It's donationware by VB-Audio.", "INSTALLED", T.SUCCESS)
            self.get_cable.hide()
            self.support_cable.show()
        else:
            self.cable.set("Not installed yet. It's free, and VolumeX installs it for you in one click.",
                           "MISSING", T.WARNING)
            self.get_cable.show()
            self.support_cable.hide()
        self.set_devices(self.controller.device_views())

    def set_engine(self, view: EngineView) -> None:
        text = {
            "streaming": ("Boosting now" + (f" on {view.output}" if view.output else ""), "RUNNING", T.SUCCESS),
            "idle": ("Waiting - starts by itself when you boost an app.", "READY", T.SUCCESS),
            "starting": (view.message or "Starting…", "STARTING", T.WARNING),
            "no_bus": ("Needs VB-CABLE before it can run.", "OFF", T.TEXT_3),
            "error": (view.message, "PROBLEM", T.DANGER),
            "failed": (view.message + " Boost is paused; apps play normally.", "PAUSED", T.DANGER),
        }.get(view.status, (view.message, view.status.upper(), T.TEXT_2))
        self.engine_row.set(*text)
        if view.status == "streaming" and view.latency_ms:
            quality = "great" if view.latency_ms < 35 else ("fine for music and video" if view.latency_ms < 60 else "high")
            drop = f" · {view.underruns} dropouts" if view.underruns else ""
            self.delay_row.set(f"About {view.latency_ms:.0f} ms - {quality}{drop}.", f"{view.latency_ms:.0f} MS",
                               T.SUCCESS if view.latency_ms < 60 else T.WARNING)
        else:
            self.delay_row.set("Only boosted apps get a small delay; everything else plays directly.", "—", T.TEXT_3)

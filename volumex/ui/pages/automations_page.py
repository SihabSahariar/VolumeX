"""Automations: remembered app levels and "when X starts, set Y" rules."""
from __future__ import annotations

from PyQt5.QtCore import QRectF
from PyQt5.QtGui import QFont, QPainter
from PyQt5.QtWidgets import QComboBox, QDialog, QHBoxLayout, QVBoxLayout, QWidget

from volumex.core.controller import Controller

from .. import theme as T
from ..background import paint_backdrop
from ..fmt import pct
from ..theme import theme
from ..widgets.app_row import ValueLabel
from ..widgets.avatar import AppAvatar
from ..widgets.boost_slider import BoostSlider
from ..widgets.common import Card, GhostButton, GradientButton, IconButton, ToggleSwitch, label
from ..win_effects import style_window
from .base import Page, Section


class RememberedRow(Card):
    def __init__(self, key: str, name: str, exe: str, gain: float, muted: bool, controller: Controller,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent, radius=14, fill=T.rgba(255, 255, 255, 8))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(12)
        lay.addWidget(AppAvatar(name, exe, size=34))
        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(label(name, 10, QFont.DemiBold))
        text.addWidget(label("Muted" if muted else "Applied every time it starts", 8.5,
                             color=T.DANGER if muted else T.TEXT_3))
        lay.addLayout(text, 1)
        value = ValueLabel(size=11.5)
        value.set_value(gain)
        lay.addWidget(value)
        forget = GhostButton("Forget", "x")
        forget.clicked.connect(lambda: controller.set_app_remember(key, False))
        lay.addWidget(forget)


class RuleRow(Card):
    def __init__(self, rule: dict, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent, radius=14, fill=T.rgba(255, 255, 255, 8))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 12, 10)
        lay.setSpacing(10)
        lay.addWidget(label("When", 10, color=T.TEXT_2))
        lay.addWidget(label(rule.get("trigger_name", "?"), 10, QFont.DemiBold))
        lay.addWidget(label("starts, set", 10, color=T.TEXT_2))
        lay.addWidget(label(rule.get("target_name", "?"), 10, QFont.DemiBold))
        lay.addWidget(label("to", 10, color=T.TEXT_2))
        gain = float(rule.get("gain", 1.0))
        lay.addWidget(label(pct(gain), 10.5, QFont.DemiBold,
                            theme.boost_color(0.3).name() if gain > 1 else theme.accent_color(0.3).name()))
        lay.addStretch(1)
        toggle = ToggleSwitch(bool(rule.get("enabled", True)))
        toggle.toggled.connect(lambda on, rid=rule["id"]: controller.set_rule_enabled(rid, on))
        lay.addWidget(toggle)
        delete = IconButton("trash", "Delete rule")
        delete.clicked.connect(lambda _=False, rid=rule["id"]: controller.remove_rule(rid))
        lay.addWidget(delete)


class RuleDialog(QDialog):
    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("New rule")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 24, 26, 22)
        lay.setSpacing(14)
        lay.addWidget(label("New rule", 15, QFont.DemiBold, display=True))
        lay.addWidget(label("Change one app's volume automatically whenever another app starts.", 9.5,
                            color=T.TEXT_2, wrap=True))
        apps = controller.known_apps()
        self.trigger = QComboBox()
        self.target = QComboBox()
        for key, name, _exe in apps:
            self.trigger.addItem(name, (key, name))
            self.target.addItem(name, (key, name))
        if self.target.count() > 1:
            self.target.setCurrentIndex(1)
        lay.addWidget(label("When this app starts", 9, QFont.DemiBold, T.TEXT_2))
        lay.addWidget(self.trigger)
        lay.addWidget(label("set this app", 9, QFont.DemiBold, T.TEXT_2))
        lay.addWidget(self.target)
        lay.addWidget(label("to this level", 9, QFont.DemiBold, T.TEXT_2))
        row = QHBoxLayout()
        self.slider = BoostSlider()
        self.slider.set_maximum(controller.max_gain)
        self.slider.set_boost_available(controller.boost_ready)
        self.slider.set_value(0.3, animate=False)
        self.value = ValueLabel()
        self.value.set_value(0.3)
        self.slider.valueChanged.connect(self.value.set_value)
        self.slider.valueCommitted.connect(self.value.set_value)
        row.addWidget(self.slider, 1)
        row.addWidget(self.value)
        lay.addLayout(row)
        lay.addSpacing(6)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = GhostButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.ok = GradientButton("Add rule", "check")
        self.ok.clicked.connect(self._accept)
        self.ok.setEnabled(self.trigger.count() > 0)
        buttons.addWidget(cancel)
        buttons.addWidget(self.ok)
        lay.addLayout(buttons)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        style_window(self)

    def paintEvent(self, _event) -> None:
        paint_backdrop(QPainter(self), QRectF(self.rect()), 0.7)

    def _accept(self) -> None:
        trigger = self.trigger.currentData()
        target = self.target.currentData()
        if not trigger or not target:
            return
        self.controller.add_rule(trigger[0], trigger[1], target[0], target[1], self.slider.value())
        self.accept()


class AutomationsPage(Page):
    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__("Automations", "Let VolumeX set volumes for you.", scroll=True, parent=parent)
        self.controller = controller

        self.remembered = Section("Remembered apps",
                                  "Windows often forgets app volumes. VolumeX puts these levels back every time the "
                                  "app starts. Adjust any app in the Mixer to add it here.")
        self.remembered_list = QVBoxLayout()
        self.remembered_list.setSpacing(8)
        self.remembered.content.addLayout(self.remembered_list)
        self.body.addWidget(self.remembered)

        self.rules = Section("Rules", "Example: when Zoom starts, turn Spotify down to 30%.")
        add = GradientButton("Add rule", "plus")
        add.clicked.connect(self._add_rule)
        self.rules.head_right.addWidget(add)
        self.rules_list = QVBoxLayout()
        self.rules_list.setSpacing(8)
        self.rules.content.addLayout(self.rules_list)
        self.body.addWidget(self.rules)
        self.body.addStretch(1)

        controller.rulesChanged.connect(self.refresh)
        controller.appsChanged.connect(lambda _views: self._refresh_remembered())
        self.refresh()

    def refresh(self) -> None:
        self._refresh_remembered()
        self._clear(self.rules_list)
        rules = self.controller.rules()
        for rule in rules:
            self.rules_list.addWidget(RuleRow(rule, self.controller))
        if not rules:
            self.rules_list.addWidget(label("No rules yet.", 9.5, color=T.TEXT_3))

    def _refresh_remembered(self) -> None:
        entries = sorted(self.controller.settings["apps"].items(), key=lambda kv: kv[1].get("name", "").lower())
        signature = [(k, v.get("gain"), v.get("muted")) for k, v in entries]
        if getattr(self, "_remembered_sig", None) == signature:
            return
        self._remembered_sig = signature
        self._clear(self.remembered_list)
        for key, entry in entries:
            self.remembered_list.addWidget(RememberedRow(key, entry.get("name", key), entry.get("exe", ""),
                                                         float(entry.get("gain", 1.0)), bool(entry.get("muted")),
                                                         self.controller))
        if not entries:
            self.remembered_list.addWidget(label("Nothing remembered yet.", 9.5, color=T.TEXT_3))

    def _add_rule(self) -> None:
        RuleDialog(self.controller, self.window()).exec_()

    @staticmethod
    def _clear(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()


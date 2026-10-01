"""Shared page scaffolding: title + subtitle header and a scrollable body."""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from .. import theme as T
from ..widgets.common import Card, label


class Page(QWidget):
    def __init__(self, title: str, subtitle: str, scroll: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(34, 28, 34, 26)
        outer.setSpacing(20)

        header = QHBoxLayout()
        header.setSpacing(12)
        titles = QVBoxLayout()
        titles.setSpacing(3)
        titles.addWidget(label(title, 21, QFont.DemiBold, display=True))
        self.subtitle = label(subtitle, 10, color=T.TEXT_2)
        titles.addWidget(self.subtitle)
        header.addLayout(titles)
        header.addStretch(1)
        self.header_right = QHBoxLayout()
        self.header_right.setSpacing(10)
        header.addLayout(self.header_right)
        outer.addLayout(header)

        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QScrollArea.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            inner = QWidget()
            self.body = QVBoxLayout(inner)
            self.body.setContentsMargins(0, 0, 8, 0)
            self.body.setSpacing(16)
            area.setWidget(inner)
            outer.addWidget(area, 1)
        else:
            self.body = QVBoxLayout()
            self.body.setSpacing(16)
            outer.addLayout(self.body, 1)


class Section(Card):
    """Card with a title row and a vertical content layout."""

    def __init__(self, title: str, subtitle: str = "", icon_widget: QWidget | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 20)
        lay.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(10)
        if icon_widget:
            head.addWidget(icon_widget)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label(title, 11.5, QFont.DemiBold))
        if subtitle:
            titles.addWidget(label(subtitle, 9, color=T.TEXT_2, wrap=True))
        head.addLayout(titles, 1)
        self.head_right = QHBoxLayout()
        self.head_right.setSpacing(8)
        head.addLayout(self.head_right)
        lay.addLayout(head)
        self.content = QVBoxLayout()
        self.content.setSpacing(10)
        lay.addLayout(self.content)


class SettingRow(QWidget):
    """Label + description on the left, a control on the right."""

    def __init__(self, title: str, description: str, control: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(16)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(label(title, 10, QFont.DemiBold))
        if description:
            text.addWidget(label(description, 9, color=T.TEXT_2, wrap=True))
        lay.addLayout(text, 1)
        lay.addWidget(control, 0, Qt.AlignVCenter)

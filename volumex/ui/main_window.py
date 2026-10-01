"""Main window: sidebar navigation + stacked pages over the aurora backdrop."""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QStackedWidget, QWidget

from volumex import APP_NAME
from volumex.core.controller import Controller

from .background import Backdrop
from .sidebar import Sidebar
from .widgets.logo import app_icon
from .win_effects import style_window


class MainWindow(Backdrop):
    closeRequested = pyqtSignal()  # hide-to-tray is decided by the app

    def __init__(self, controller: Controller, pages: list[QWidget], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.setMinimumSize(980, 660)
        self.resize(1180, 760)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.sidebar = Sidebar()
        lay.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        for page in pages:
            self.stack.addWidget(page)
        lay.addWidget(self.stack, 1)
        self.sidebar.pageSelected.connect(self.stack.setCurrentIndex)
        controller.engineChanged.connect(self.sidebar.status.set_view)
        self.sidebar.status.set_view(controller.engine_view())
        self._styled = False

    def show_page(self, index: int) -> None:
        self.sidebar.select(index)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if not self._styled:
            self._styled = True
            style_window(self)

    def closeEvent(self, e) -> None:
        e.ignore()
        self.closeRequested.emit()

    def bring_to_front(self) -> None:
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

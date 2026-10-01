"""About: VolumeX itself, who made it (name and socials), a featured app to try, and credits."""
from __future__ import annotations

from PyQt5.QtCore import QRectF, Qt, QUrl
from PyQt5.QtGui import QColor, QDesktopServices, QFont, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from volumex import APP_NAME, __version__, about_info as info
from volumex.platform import vbcable
from volumex.resources import resource

from .. import theme as T
from ..icons import paint_icon
from ..theme import theme
from ..widgets.common import Card, GhostButton, GradientButton, Pill, label
from ..widgets.logo import BrandLogo
from .base import Page, Section

UMBRA_AMBER = ("#FFC15E", "#FFA83B", "#F28A1F")  # matches Umbra's crescent


def open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


class CheckLine(QWidget):
    """One highlight: an amber check mark and a line of text."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        mark = QWidget()
        mark.setFixedSize(16, 16)
        mark.paintEvent = lambda _e, m=mark: paint_icon(QPainter(m), "check", QRectF(m.rect()),  # type: ignore
                                                        QColor(UMBRA_AMBER[1]), 2.4)
        lay.addWidget(mark)
        lay.addWidget(label(text, 9.5, color=T.TEXT_2), 1)


class AppTile(QWidget):
    """A product icon image with rounded corners."""

    def __init__(self, image: str, size: int = 64, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap = QPixmap(image)
        self.setFixedSize(size, size)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        p.drawPixmap(QRectF(self.rect()), self._pixmap, QRectF(self._pixmap.rect()))


class FeaturedCard(Card):
    """A card with an amber glow border for the featured app."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.6, 0.6, -0.6, -0.6)
        path = QPainterPath()
        path.addRoundedRect(r, 20, 20)
        p.setPen(QPen(theme.gradient(r.left(), r.top(), r.right(), r.bottom(), UMBRA_AMBER, alpha=170), 1.3))
        p.drawPath(path)


class CreditRow(QWidget):
    def __init__(self, title: str, body: str, url: str, button: str, primary: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(14)
        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(label(title, 10, QFont.DemiBold))
        text.addWidget(label(body, 9, color=T.TEXT_2, wrap=True))
        lay.addLayout(text, 1)
        btn = GradientButton(button, "heart", boost=True) if primary else GhostButton(button, "external")
        btn.clicked.connect(lambda: open_url(url))
        lay.addWidget(btn, 0, Qt.AlignVCenter)


class AboutPage(Page):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("About", f"{APP_NAME} is free and open source.", scroll=True, parent=parent)

        # -- the product -------------------------------------------------------------------------
        product = Card(radius=22, glow=True)
        a = QVBoxLayout(product)
        a.setContentsMargins(28, 26, 28, 24)
        a.setSpacing(14)
        head = QHBoxLayout()
        head.addWidget(BrandLogo(46))
        head.addStretch(1)
        head.addWidget(Pill(f"VERSION {__version__}", T.TEXT_2), 0, Qt.AlignTop)
        a.addLayout(head)
        a.addWidget(label("Boost any app above 100% - or all of them - without distortion, and keep every app's "
                          "level exactly where you like it.", 11, color=T.TEXT_2, wrap=True))
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        manual = GradientButton("User manual", "book-open")
        manual.clicked.connect(lambda: open_url(info.MANUAL_URL))
        buttons.addWidget(manual)
        website = GhostButton("Website", "globe")
        website.clicked.connect(lambda: open_url(info.WEBSITE_URL))
        buttons.addWidget(website)
        if info.SOURCE_URL:
            source = GhostButton("Source code", "code")
            source.clicked.connect(lambda: open_url(info.SOURCE_URL))
            buttons.addWidget(source)
        feedback = GhostButton("Send feedback", "mail")
        feedback.clicked.connect(lambda: open_url(f"mailto:{info.FEEDBACK_EMAIL}?subject={APP_NAME}%20feedback"))
        buttons.addWidget(feedback)
        buttons.addStretch(1)
        buttons.addWidget(label("GPL-3.0 · Windows 10 & 11", 9, color=T.TEXT_3))
        a.addLayout(buttons)
        self.body.addWidget(product)

        row = QHBoxLayout()
        row.setSpacing(16)

        # -- developer: name + socials -----------------------------------------------------------
        dev = Card(radius=20)
        d = QVBoxLayout(dev)
        d.setContentsMargins(24, 22, 24, 22)
        d.setSpacing(4)
        d.addWidget(label("DEVELOPED BY", 7.5, QFont.Bold, T.TEXT_3))
        d.addWidget(label(info.DEVELOPER_NAME, 19, QFont.DemiBold, display=True))
        d.addSpacing(12)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        for i, link in enumerate(info.DEVELOPER_LINKS):
            btn = GhostButton(link.label, link.icon)
            btn.setToolTip(link.url.replace("mailto:", ""))
            btn.clicked.connect(lambda _=False, url=link.url: open_url(url))
            grid.addWidget(btn, i // 2, i % 2)
        d.addLayout(grid)
        d.addStretch(1)
        row.addWidget(dev, 1)

        # -- featured app: Umbra -----------------------------------------------------------------
        app = info.UMBRA
        featured = FeaturedCard(radius=20, fill=T.rgba(255, 193, 94, 10))
        f = QVBoxLayout(featured)
        f.setContentsMargins(24, 22, 24, 22)
        f.setSpacing(10)
        f.addWidget(label("TRY NEXT · FROM THE SAME DEVELOPER", 7.5, QFont.Bold, UMBRA_AMBER[1]))
        top = QHBoxLayout()
        top.setSpacing(14)
        top.addWidget(AppTile(str(resource(app.icon)), 58))
        names = QVBoxLayout()
        names.setSpacing(1)
        names.addWidget(label(app.name, 17, QFont.DemiBold, display=True))
        names.addWidget(label(app.tagline, 10, QFont.DemiBold, T.TEXT))
        top.addLayout(names, 1)
        f.addLayout(top)
        f.addWidget(label(app.description, 9.5, color=T.TEXT_2, wrap=True))
        for highlight in app.highlights:
            f.addWidget(CheckLine(highlight))
        f.addSpacing(4)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        download = GradientButton(f"Download {app.name} - free", "download", stops=UMBRA_AMBER)
        download.clicked.connect(lambda: open_url(app.download_url))
        more = GhostButton("Learn more", "external")
        more.clicked.connect(lambda: open_url(app.website_url))
        actions.addWidget(download)
        actions.addWidget(more)
        actions.addStretch(1)
        f.addLayout(actions)
        f.addWidget(label(app.requirements, 8.5, color=T.TEXT_3))
        row.addWidget(featured, 1)
        self.body.addLayout(row)

        # -- credits -----------------------------------------------------------------------------
        credits = Section("Credits", f"{APP_NAME} is built on the work of these projects - thank you.")
        for i, (title, body, url) in enumerate(info.CREDITS):
            if i == 0:  # VB-CABLE is donationware; VB-Audio asks that users can support them
                credits.content.addWidget(CreditRow(title, body, vbcable.DONATE_URL, "Support VB-Audio", primary=True))
            else:
                credits.content.addWidget(CreditRow(title, body, url, "Website"))
        self.body.addWidget(credits)
        self.body.addStretch(1)

"""The brand-kit files ship with the package and load."""
from __future__ import annotations

from PyQt5.QtSvg import QSvgRenderer

from volumex import about_info
from volumex.resources import resource
from volumex.ui.widgets.logo import BrandLogo, app_icon, tray_icon


def test_brand_files_load(qtbot):
    for name in ("VolumeX-icon.svg", "VolumeX-logo-reversed.svg"):
        assert QSvgRenderer(str(resource("brand") / name)).isValid(), name
    assert len(app_icon().availableSizes()) >= 10
    for state in ("normal", "boost", "muted"):
        for light in (False, True):
            assert not tray_icon(state, light).pixmap(32, 32).isNull()
    logo = BrandLogo(32)
    qtbot.addWidget(logo)
    assert logo.width() > 4 * logo.height()  # icon + wordmark


def test_about_resources_exist():
    assert resource(about_info.UMBRA.icon).exists()

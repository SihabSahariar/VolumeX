"""VolumeX visual design system: colours, accent gradients, fonts and the global stylesheet.

Custom widgets paint themselves from these tokens and repaint when the accent
changes (``theme.changed``), so switching accents recolours the whole app live.
"""
from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtCore import QObject, QPointF, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QGradient, QLinearGradient, QPalette
from PyQt5.QtWidgets import QApplication


@dataclass(frozen=True)
class Accent:
    key: str
    label: str
    stops: tuple[str, str, str]


ACCENTS: dict[str, Accent] = {
    a.key: a
    for a in (
        Accent("aurora", "Aurora", ("#22D3EE", "#818CF8", "#C084FC")),
        Accent("ocean", "Ocean", ("#2DD4BF", "#38BDF8", "#6366F1")),
        Accent("neon", "Neon", ("#A3E635", "#34D399", "#22D3EE")),
        Accent("sakura", "Sakura", ("#F9A8D4", "#C084FC", "#818CF8")),
        Accent("sunset", "Sunset", ("#FDE047", "#FB923C", "#F472B6")),
        Accent("ember", "Ember", ("#FB923C", "#F43F5E", "#BE185D")),
        Accent("signal", "Signal", ("#FFB185", "#FF7A45", "#FF5A1F")),  # VolumeX brand orange
    )
}

# The boost zone (above 100%) is always "hot", whatever the accent.
BOOST_STOPS = ("#FBBF24", "#FB7185", "#E879F9")

BG_TOP = "#0B0D1A"
BG_BOTTOM = "#0E1021"
BG_PANEL = "#12152A"
BG_POPUP = "#141830"
TEXT = "#EEF0F8"
TEXT_2 = "#A6ACC8"
TEXT_3 = "#6B7196"
SUCCESS = "#34D399"
WARNING = "#FBBF24"
DANGER = "#FB7185"


def rgba(r: int, g: int, b: int, a: int) -> QColor:
    return QColor(r, g, b, a)


SURFACE = rgba(255, 255, 255, 11)
SURFACE_2 = rgba(255, 255, 255, 17)
SURFACE_HOVER = rgba(255, 255, 255, 22)
BORDER = rgba(255, 255, 255, 20)
BORDER_STRONG = rgba(255, 255, 255, 44)
TRACK = rgba(255, 255, 255, 18)


def mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
        round(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


def with_alpha(color: QColor | str, alpha: int) -> QColor:
    c = QColor(color)
    c.setAlpha(alpha)
    return c


def sample(stops: tuple[str, ...], t: float) -> QColor:
    """Colour at position t (0..1) along evenly spaced gradient stops."""
    t = max(0.0, min(1.0, t))
    scaled = t * (len(stops) - 1)
    i = min(int(scaled), len(stops) - 2)
    return mix(QColor(stops[i]), QColor(stops[i + 1]), scaled - i)


class Theme(QObject):
    changed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self._accent = ACCENTS["aurora"]
        self._text_family = "Segoe UI"
        self._display_family = "Segoe UI"

    # -- accent --------------------------------------------------------------------------
    @property
    def accent(self) -> Accent:
        return self._accent

    def set_accent(self, key: str) -> None:
        accent = ACCENTS.get(key, ACCENTS["aurora"])
        if accent != self._accent:
            self._accent = accent
            apply_stylesheet()
            self.changed.emit()

    def accent_color(self, t: float = 0.5) -> QColor:
        return sample(self._accent.stops, t)

    def boost_color(self, t: float = 0.5) -> QColor:
        return sample(BOOST_STOPS, t)

    def gradient(self, x1: float, y1: float, x2: float, y2: float, stops: tuple[str, ...] | None = None,
                 alpha: int = 255) -> QLinearGradient:
        grad = QLinearGradient(QPointF(x1, y1), QPointF(x2, y2))
        stops = stops or self._accent.stops
        for i, color in enumerate(stops):
            grad.setColorAt(i / (len(stops) - 1), with_alpha(color, alpha))
        grad.setSpread(QGradient.PadSpread)
        return grad

    def boost_gradient(self, x1: float, y1: float, x2: float, y2: float, alpha: int = 255) -> QLinearGradient:
        return self.gradient(x1, y1, x2, y2, BOOST_STOPS, alpha)

    # -- fonts ---------------------------------------------------------------------------
    def init_fonts(self) -> None:
        families = set(QFontDatabase().families())
        for text, display in (("Segoe UI Variable Text", "Segoe UI Variable Display"),
                              ("Segoe UI Variable", "Segoe UI Variable")):
            if text in families and display in families:
                self._text_family, self._display_family = text, display
                break

    def font(self, size: float = 10.0, weight: int = QFont.Normal, display: bool = False) -> QFont:
        f = QFont(self._display_family if display else self._text_family)
        f.setPointSizeF(size)
        f.setWeight(weight)
        f.setHintingPreference(QFont.PreferNoHinting)
        return f


theme = Theme()


def apply_palette(app: QApplication) -> None:
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG_TOP))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(BG_PANEL))
    pal.setColor(QPalette.AlternateBase, QColor(BG_POPUP))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor(BG_PANEL))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.ToolTipBase, QColor(BG_POPUP))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    pal.setColor(QPalette.PlaceholderText, QColor(TEXT_3))
    pal.setColor(QPalette.Highlight, theme.accent_color(0.5))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.Link, theme.accent_color(0.2))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(TEXT_3))
    app.setPalette(pal)


def apply_stylesheet() -> None:
    app = QApplication.instance()
    if app is None:
        return
    apply_palette(app)
    from .icons import icon_file

    accent = theme.accent_color(0.5).name()
    chevron = icon_file("chevron-down", TEXT_2, 14).replace("\\", "/")
    app.setStyleSheet(
        f"""
        QWidget {{ color: {TEXT}; }}
        QToolTip {{ background: {BG_POPUP}; color: {TEXT}; border: 1px solid rgba(255,255,255,46);
                    border-radius: 8px; padding: 6px 9px; }}
        QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 6px 2px 6px 2px; }}
        QScrollBar::handle:vertical {{ background: rgba(255,255,255,34); border-radius: 3px; min-height: 36px; }}
        QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,70); }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        QMenu {{ background: {BG_POPUP}; border: 1px solid rgba(255,255,255,40); border-radius: 12px; padding: 6px; }}
        QMenu::item {{ padding: 8px 26px 8px 14px; border-radius: 7px; color: {TEXT}; }}
        QMenu::item:selected {{ background: rgba(255,255,255,22); }}
        QMenu::item:disabled {{ color: {TEXT_3}; }}
        QMenu::separator {{ height: 1px; background: rgba(255,255,255,26); margin: 6px 10px; }}
        QMenu::indicator {{ width: 0px; }}
        QComboBox {{ background: rgba(255,255,255,14); border: 1px solid rgba(255,255,255,30); border-radius: 9px;
                     padding: 7px 34px 7px 12px; min-height: 20px; }}
        QComboBox:hover {{ border-color: rgba(255,255,255,70); }}
        QComboBox:focus {{ border-color: {accent}; }}
        QComboBox::drop-down {{ border: none; width: 30px; }}
        QComboBox::down-arrow {{ image: url("{chevron}"); width: 14px; height: 14px; }}
        QComboBox QAbstractItemView {{ background: {BG_POPUP}; border: 1px solid rgba(255,255,255,40);
                     selection-background-color: rgba(255,255,255,26); outline: none; padding: 4px; }}
        QLineEdit, QDoubleSpinBox, QSpinBox {{ background: rgba(255,255,255,14); border: 1px solid rgba(255,255,255,30);
                     border-radius: 9px; padding: 7px 10px; selection-background-color: {accent}; }}
        QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus {{ border-color: {accent}; }}
        QDialog {{ background: {BG_TOP}; }}
        """
    )

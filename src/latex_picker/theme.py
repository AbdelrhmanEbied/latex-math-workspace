"""Colour themes, fonts and Qt stylesheet generation."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtGui import QColor, QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str
    surface: str
    surface_alt: str
    border: str
    border_strong: str
    text: str
    muted: str
    faint: str
    accent: str
    accent_soft: str
    selection: str
    math: str
    danger: str
    ui_family: str
    mono_family: str
    math_family: str
    scale: float = 1.0

    def color(self, value: str) -> QColor:
        return QColor(value)

    def ui_font(self, pixel_size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
        font = QFont(self.ui_family)
        font.setPixelSize(max(8, round(pixel_size * self.scale)))
        font.setWeight(weight)
        return font

    def mono_font(self, pixel_size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
        font = QFont(self.mono_family)
        font.setPixelSize(max(8, round(pixel_size * self.scale)))
        font.setWeight(weight)
        return font

    def math_font(self, pixel_size: int) -> QFont:
        font = QFont(self.math_family)
        font.setPixelSize(max(10, round(pixel_size * self.scale)))
        return font

    def stylesheet(self) -> str:
        s = self.scale
        return f"""
        QWidget {{
            color: {self.text};
            font-family: "{self.ui_family}";
            font-size: {round(13 * s)}px;
            outline: none;
        }}
        QLabel {{ background: transparent; }}
        QLabel#Muted {{ color: {self.muted}; }}
        QLabel#Faint {{ color: {self.faint}; }}
        QLabel#Source {{
            font-family: "{self.mono_family}";
            font-size: {round(12 * s)}px;
            color: {self.muted};
            background: transparent;
        }}
        QLabel#PreviewText {{
            font-family: "{self.math_family}";
            color: {self.math};
            background: transparent;
        }}
        QLabel#PaneTitle {{
            color: {self.faint};
            font-size: {round(10 * s)}px;
            font-weight: 700;
            letter-spacing: 1px;
        }}
        QLabel#PaneTitleText {{
            color: {self.text};
            font-size: {round(15 * s)}px;
            font-weight: 600;
        }}
        QLabel#Keycap {{
            background: {self.surface_alt};
            border: 1px solid {self.border};
            border-radius: {round(4 * s)}px;
            color: {self.muted};
            padding: {round(1 * s)}px {round(5 * s)}px;
            font-family: "{self.mono_family}";
            font-size: {round(9.5 * s)}px;
        }}
        QLineEdit {{
            background: transparent;
            border: none;
            padding: 0;
            color: {self.text};
            selection-background-color: {self.accent_soft};
            selection-color: {self.text};
            font-size: {round(16 * s)}px;
        }}
        QLineEdit::placeholder {{ color: {self.faint}; }}
        QWidget#SearchBox {{
            background: {self.surface_alt};
            border: 1px solid {self.border};
            border-radius: 12px;
        }}
        QWidget#SearchBox[focused="true"] {{
            border: 1px solid {self.accent};
            background: {self.surface};
        }}
        QToolButton#ClearButton {{
            background: transparent;
            border: none;
            color: {self.faint};
            font-size: {round(15 * s)}px;
            padding: 0;
            border-radius: 9px;
        }}
        QToolButton#ClearButton:hover {{
            color: {self.text};
            background: {self.border};
        }}
        QPushButton#CategoryChip {{
            background: {self.surface_alt};
            border: 1px solid transparent;
            border-radius: {round(14 * s)}px;
            color: {self.muted};
            padding: {round(4 * s)}px {round(11 * s)}px;
            font-size: {round(12 * s)}px;
            font-weight: 500;
        }}
        QPushButton#CategoryChip:hover {{
            color: {self.text};
            border-color: {self.border_strong};
        }}
        QPushButton#CategoryChip:checked {{
            background: {self.accent_soft};
            border-color: {self.accent};
            color: {self.accent};
        }}
        QToolButton#ChipNav {{
            background: transparent;
            border: none;
            color: {self.muted};
            border-radius: {round(7 * s)}px;
            font-size: {round(17 * s)}px;
            padding: 0;
        }}
        QToolButton#ChipNav:hover {{
            background: {self.surface_alt};
            color: {self.text};
        }}
        QFrame#PreviewPane {{
            background: {self.surface};
            border: 1px solid {self.border};
            border-radius: 12px;
        }}
        QFrame#Separator {{
            background: {self.border};
            max-height: 1px;
            border: none;
        }}
        QListView {{
            background: transparent;
            border: none;
            padding: 0;
        }}
        QScrollArea {{ background: transparent; border: none; }}
        QScrollBar:vertical {{
            background: transparent;
            width: {round(8 * s)}px;
            margin: 2px;
        }}
        QScrollBar::handle:vertical {{
            background: {self.border_strong};
            border-radius: {round(3 * s)}px;
            min-height: 24px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {self.faint}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        QScrollBar:horizontal {{ height: 0; }}
        QToolTip {{
            background: {self.surface_alt};
            color: {self.text};
            border: 1px solid {self.border_strong};
            padding: 5px 8px;
            border-radius: 5px;
        }}
        QLabel#Error {{ color: {self.danger}; }}
        QLabel#Success {{ color: {self.accent}; }}
        QLabel#SectionTitle {{
            color: {self.faint};
            font-size: {round(10.5 * s)}px;
            font-weight: 700;
            letter-spacing: 1px;
        }}
        QLabel#MathOut {{ color: {self.math}; background: transparent; }}
        QPushButton#ModeTab {{
            background: transparent;
            border: 1px solid transparent;
            border-radius: {round(9 * s)}px;
            color: {self.muted};
            padding: {round(5 * s)}px {round(13 * s)}px;
            font-size: {round(13 * s)}px;
            font-weight: 600;
        }}
        QPushButton#ModeTab:hover {{ color: {self.text}; background: {self.surface_alt}; }}
        QPushButton#ModeTab:checked {{
            background: {self.accent_soft};
            border-color: {self.accent};
            color: {self.accent};
        }}
        QPushButton, QToolButton#Tool {{
            background: {self.surface_alt};
            border: 1px solid {self.border};
            border-radius: {round(7 * s)}px;
            color: {self.text};
            padding: {round(4 * s)}px {round(10 * s)}px;
        }}
        QPushButton:hover, QToolButton#Tool:hover {{
            border-color: {self.border_strong};
            background: {self.surface};
        }}
        QPushButton:pressed, QToolButton#Tool:pressed {{ background: {self.selection}; }}
        QPushButton:disabled {{ color: {self.faint}; border-color: {self.border}; }}
        QPushButton:checked {{ background: {self.accent_soft}; border-color: {self.accent}; color: {self.accent}; }}
        QPushButton#Primary {{
            background: {self.accent};
            border-color: {self.accent};
            color: {self.bg};
            font-weight: 700;
        }}
        QPushButton#Primary:hover {{ background: {self.math}; }}
        QPushButton#Key {{
            font-family: "{self.math_family}";
            font-size: {round(15 * s)}px;
            padding: {round(3 * s)}px {round(4 * s)}px;
            min-width: {round(34 * s)}px;
            min-height: {round(28 * s)}px;
        }}
        QPushButton#KeyOp {{
            font-family: "{self.math_family}";
            font-size: {round(15 * s)}px;
            color: {self.accent};
            padding: {round(3 * s)}px {round(4 * s)}px;
            min-width: {round(34 * s)}px;
            min-height: {round(28 * s)}px;
        }}
        QPushButton#KeyAccent {{
            background: {self.accent_soft};
            border-color: {self.accent};
            color: {self.accent};
            font-weight: 700;
            min-height: {round(28 * s)}px;
        }}
        QFrame#Card {{
            background: {self.surface};
            border: 1px solid {self.border};
            border-radius: {round(10 * s)}px;
        }}
        QFrame#Card:hover {{ border-color: {self.border_strong}; }}
        QFrame#Panel {{
            background: {self.surface};
            border: 1px solid {self.border};
            border-radius: {round(12 * s)}px;
        }}
        QPlainTextEdit, QTextEdit, QTableWidget, QListWidget, QTreeWidget {{
            background: {self.surface_alt};
            border: 1px solid {self.border};
            border-radius: {round(8 * s)}px;
            color: {self.text};
            selection-background-color: {self.accent_soft};
            selection-color: {self.text};
            padding: {round(4 * s)}px;
        }}
        QPlainTextEdit:focus, QTextEdit:focus, QTableWidget:focus {{ border-color: {self.accent}; }}
        QPlainTextEdit#CodeEditor {{
            font-family: "{self.mono_family}";
            font-size: {round(14 * s)}px;
        }}
        QLineEdit#Field {{
            background: {self.surface_alt};
            border: 1px solid {self.border};
            border-radius: {round(7 * s)}px;
            padding: {round(5 * s)}px {round(8 * s)}px;
            font-size: {round(14 * s)}px;
        }}
        QLineEdit#Field:focus {{ border-color: {self.accent}; background: {self.surface}; }}
        QLineEdit#MonoField {{
            background: {self.surface_alt};
            border: 1px solid {self.border};
            border-radius: {round(7 * s)}px;
            padding: {round(5 * s)}px {round(8 * s)}px;
            font-family: "{self.mono_family}";
            font-size: {round(14 * s)}px;
        }}
        QLineEdit#MonoField:focus {{ border-color: {self.accent}; background: {self.surface}; }}
        QTableWidget {{ gridline-color: {self.border}; font-family: "{self.mono_family}"; }}
        QTableWidget::item:selected {{ background: {self.accent_soft}; color: {self.text}; }}
        QHeaderView::section {{
            background: {self.surface};
            color: {self.faint};
            border: none;
            border-right: 1px solid {self.border};
            border-bottom: 1px solid {self.border};
            padding: {round(3 * s)}px;
        }}
        QTableCornerButton::section {{ background: {self.surface}; border: none; }}
        QListWidget::item {{ padding: {round(4 * s)}px; border-radius: {round(5 * s)}px; }}
        QListWidget::item:selected {{ background: {self.accent_soft}; color: {self.text}; }}
        QListWidget::item:hover {{ background: {self.selection}; }}
        QSpinBox, QDoubleSpinBox, QComboBox {{
            background: {self.surface_alt};
            border: 1px solid {self.border};
            border-radius: {round(6 * s)}px;
            padding: {round(3 * s)}px {round(6 * s)}px;
            color: {self.text};
            min-height: {round(22 * s)}px;
        }}
        QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {self.accent}; }}
        QComboBox QAbstractItemView {{
            background: {self.surface};
            border: 1px solid {self.border_strong};
            selection-background-color: {self.accent_soft};
            color: {self.text};
        }}
        QCheckBox, QRadioButton {{ color: {self.text}; spacing: {round(6 * s)}px; }}
        QCheckBox::indicator, QRadioButton::indicator {{
            width: {round(14 * s)}px; height: {round(14 * s)}px;
            border: 1px solid {self.border_strong};
            background: {self.surface_alt};
            border-radius: {round(4 * s)}px;
        }}
        QRadioButton::indicator {{ border-radius: {round(7 * s)}px; }}
        QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
            background: {self.accent}; border-color: {self.accent};
        }}
        QSlider::groove:horizontal {{ height: 4px; background: {self.border}; border-radius: 2px; }}
        QSlider::handle:horizontal {{
            background: {self.accent}; width: {round(14 * s)}px;
            margin: -6px 0; border-radius: {round(7 * s)}px;
        }}
        QSlider::sub-page:horizontal {{ background: {self.accent_soft}; border-radius: 2px; }}
        QTabWidget::pane {{ border: none; background: transparent; }}
        QTabBar::tab {{
            background: transparent;
            color: {self.muted};
            padding: {round(5 * s)}px {round(11 * s)}px;
            border: none;
            border-bottom: 2px solid transparent;
            font-weight: 600;
        }}
        QTabBar::tab:hover {{ color: {self.text}; }}
        QTabBar::tab:selected {{ color: {self.accent}; border-bottom: 2px solid {self.accent}; }}
        QMenu {{
            background: {self.surface};
            border: 1px solid {self.border_strong};
            padding: 4px;
            border-radius: 6px;
        }}
        QMenu::item {{ padding: 5px 18px; border-radius: 4px; color: {self.text}; }}
        QMenu::item:selected {{ background: {self.accent_soft}; }}
        QMenu::separator {{ height: 1px; background: {self.border}; margin: 4px 6px; }}
        QSplitter::handle {{ background: transparent; }}
        QSplitter::handle:hover {{ background: {self.border}; }}
        QScrollBar:horizontal#Visible {{ height: {round(8 * s)}px; background: transparent; }}
        QWidget#Transparent {{ background: transparent; }}
        """


DARK = Theme(
    name="dark",
    bg="#15161b",
    surface="#1b1d24",
    surface_alt="#22242d",
    border="#2d303b",
    border_strong="#424654",
    text="#f2f2f7",
    muted="#a0a4b3",
    faint="#737887",
    accent="#c4b5fd",
    accent_soft="#312b47",
    selection="#282438",
    math="#f6f3ff",
    danger="#f38ba8",
    ui_family="Noto Sans",
    mono_family="JetBrainsMono Nerd Font",
    math_family="DejaVu Math TeX Gyre",
)

LIGHT = Theme(
    name="light",
    bg="#f7f6fb",
    surface="#ffffff",
    surface_alt="#efedf6",
    border="#e3e0eb",
    border_strong="#cfcbd9",
    text="#201f29",
    muted="#6d687c",
    faint="#948ea4",
    accent="#6d28d9",
    accent_soft="#ece6ff",
    selection="#ece7fc",
    math="#1e1b2b",
    danger="#c0264d",
    ui_family="Noto Sans",
    mono_family="JetBrainsMono Nerd Font",
    math_family="DejaVu Math TeX Gyre",
)


def _choose_family(preferred: list[str], fallback: str) -> str:
    installed = set(QFontDatabase.families())
    for family in preferred:
        if family in installed:
            return family
    return fallback


def resolve_theme(mode: str = "auto", scale: float = 1.0) -> Theme:
    chosen = mode
    if mode == "auto":
        chosen = "light"
        try:
            scheme = QApplication.styleHints().colorScheme()
            if scheme.name == "Dark":
                chosen = "dark"
            elif scheme.name == "Light":
                chosen = "light"
            else:
                palette = QApplication.palette()
                chosen = "dark" if palette.window().color().lightness() < 128 else "light"
        except Exception:  # noqa: BLE001 - palettes are best-effort
            palette = QApplication.palette()
            chosen = "dark" if palette.window().color().lightness() < 128 else "light"
    base = DARK if chosen == "dark" else LIGHT
    ui = _choose_family(
        ["Inter", "Noto Sans", "Adwaita Sans", "Cantarell", "DejaVu Sans"], base.ui_family
    )
    mono = _choose_family(
        ["JetBrainsMono Nerd Font", "JetBrains Mono", "Adwaita Mono", "DejaVu Sans Mono"],
        base.mono_family,
    )
    math = _choose_family(
        ["STIX Two Math", "Latin Modern Math", "DejaVu Math TeX Gyre", "DejaVu Serif"],
        base.math_family,
    )
    return Theme(
        **{**base.__dict__, "ui_family": ui, "mono_family": mono,
           "math_family": math, "scale": scale}
    )

"""Interactive function grapher tab."""

from __future__ import annotations

import io
import math
import warnings
from pathlib import Path

import numpy as np
import sympy as sp
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import Theme
from . import mathcore, plotting
from .plotting import PlotSpec, format_number
from .widgets import ToolTab, section_label

DARK_PALETTE = ["#8aa8ff", "#f38ba8", "#a6e3a1", "#fab387", "#cba6f7", "#89dceb",
                "#f9e2af", "#f5c2e7"]
LIGHT_PALETTE = ["#2563eb", "#dc2626", "#16a34a", "#ea580c", "#7c3aed", "#0891b2",
                 "#ca8a04", "#db2777"]
DEFAULT_VIEW = (-10.0, 10.0, -7.0, 7.0)


def _num(text: str) -> float:
    value = float(sp.N(mathcore.parse(text)))
    if not math.isfinite(value):
        raise ValueError("not a finite number")
    return value


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


# --------------------------------------------------------------------------
# Rows
# --------------------------------------------------------------------------

class ExpressionRow(QFrame):
    changed = pyqtSignal()
    toggled = pyqtSignal()
    removed = pyqtSignal(object)
    focused = pyqtSignal(object)
    submitted = pyqtSignal(object)

    def __init__(self, theme: Theme, palette: list[str], color: str, text: str = "",
                 visible: bool = True) -> None:
        super().__init__()
        self.theme = theme
        self.palette = palette
        self.color = color
        self.spec: PlotSpec = PlotSpec("empty", "")
        self.setObjectName("Card")
        s = theme.scale
        outer = QVBoxLayout(self)
        outer.setContentsMargins(round(7 * s), round(5 * s), round(5 * s), round(5 * s))
        outer.setSpacing(round(2 * s))
        line = QHBoxLayout()
        line.setSpacing(round(6 * s))

        self.swatch = QPushButton()
        self.swatch.setFixedSize(round(18 * s), round(18 * s))
        self.swatch.setToolTip("Change colour")
        self.swatch.setCursor(Qt.CursorShape.PointingHandCursor)
        self.swatch.clicked.connect(self._cycle_color)
        line.addWidget(self.swatch)

        self.check = QCheckBox()
        self.check.setChecked(visible)
        self.check.setToolTip("Show / hide")
        self.check.toggled.connect(lambda _v: self.toggled.emit())
        line.addWidget(self.check)

        self.edit = QLineEdit(text)
        self.edit.setObjectName("MonoField")
        self.edit.setPlaceholderText("y = sin(x),  r = θ,  x²+y²=9 …")
        self.edit.textChanged.connect(lambda _t: self.changed.emit())
        self.edit.returnPressed.connect(lambda: self.submitted.emit(self))
        self.edit.installEventFilter(self)
        line.addWidget(self.edit, 1)

        self.delete = QToolButton()
        self.delete.setText("✕")
        self.delete.setObjectName("ClearButton")
        self.delete.setToolTip("Remove")
        self.delete.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete.clicked.connect(lambda: self.removed.emit(self))
        line.addWidget(self.delete)
        outer.addLayout(line)

        self.info = QLabel("")
        self.info.setObjectName("Faint")
        self.info.setWordWrap(True)
        self.info.setContentsMargins(round(48 * s), 0, 0, 0)
        self.info.hide()
        outer.addWidget(self.info)
        self._paint_swatch()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.edit and event.type() == QEvent.Type.FocusIn:
            self.focused.emit(self)
        return super().eventFilter(obj, event)

    def text(self) -> str:
        return self.edit.text()

    def visible(self) -> bool:
        return self.check.isChecked()

    def _cycle_color(self) -> None:
        try:
            index = self.palette.index(self.color)
        except ValueError:
            index = -1
        self.color = self.palette[(index + 1) % len(self.palette)]
        self._paint_swatch()
        self.toggled.emit()

    def _paint_swatch(self) -> None:
        radius = self.swatch.width() // 2
        self.swatch.setStyleSheet(
            f"QPushButton {{ background: {self.color}; border: 2px solid {self.theme.surface};"
            f" border-radius: {radius}px; padding: 0; min-width: 0; }}"
            f"QPushButton:hover {{ border-color: {self.theme.border_strong}; }}"
        )

    def set_spec(self, spec: PlotSpec) -> None:
        self.spec = spec
        if spec.kind == "error":
            self.info.setObjectName("Error")
            self.info.setText(f"⚠ {spec.error}")
            self.info.show()
        elif spec.kind == "empty":
            self.info.hide()
        else:
            self.info.setObjectName("Faint")
            label = spec.label
            if spec.kind in {"parametric", "polar"}:
                var = "t" if spec.kind == "parametric" else "θ"
                a, b = spec.t_range
                label += f" · {var} ∈ [{format_number(a)}, {format_number(b)}]"
            if spec.params:
                label += " · sliders: " + ", ".join(spec.params)
            self.info.setText(label)
            self.info.show()
        _repolish(self.info)


class SliderRow(QFrame):
    value_changed = pyqtSignal(str, float)

    def __init__(self, theme: Theme, name: str, config: dict) -> None:
        super().__init__()
        self.theme = theme
        self.name = name
        self.config = config
        self.playing = False
        self.direction = 1.0
        self.setObjectName("Card")
        s = theme.scale
        layout = QVBoxLayout(self)
        layout.setContentsMargins(round(8 * s), round(5 * s), round(6 * s), round(5 * s))
        layout.setSpacing(round(3 * s))

        top = QHBoxLayout()
        top.setSpacing(round(6 * s))
        label = QLabel(f"{_greek(name)} =")
        label.setObjectName("PreviewText")
        label.setStyleSheet(f"font-size: {round(15 * s)}px;")
        top.addWidget(label)
        self.value_edit = self._field(format_number(config["value"]), 70)
        self.value_edit.editingFinished.connect(self._value_typed)
        top.addWidget(self.value_edit)
        top.addStretch(1)
        step_label = QLabel("step")
        step_label.setObjectName("Faint")
        top.addWidget(step_label)
        self.step_edit = self._field(format_number(config["step"]), 46)
        self.step_edit.editingFinished.connect(self._range_typed)
        top.addWidget(self.step_edit)
        self.play = QToolButton()
        self.play.setObjectName("Tool")
        self.play.setText("▶")
        self.play.setToolTip("Animate")
        self.play.clicked.connect(self.toggle_play)
        top.addWidget(self.play)
        layout.addLayout(top)

        bottom = QHBoxLayout()
        bottom.setSpacing(round(6 * s))
        self.min_edit = self._field(format_number(config["min"]), 46)
        self.min_edit.editingFinished.connect(self._range_typed)
        bottom.addWidget(self.min_edit)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.valueChanged.connect(self._slider_moved)
        bottom.addWidget(self.slider, 1)
        self.max_edit = self._field(format_number(config["max"]), 46)
        self.max_edit.editingFinished.connect(self._range_typed)
        bottom.addWidget(self.max_edit)
        layout.addLayout(bottom)
        self._sync_slider()

    def _field(self, text: str, width: int) -> QLineEdit:
        field = QLineEdit(text)
        field.setObjectName("MonoField")
        field.setFixedWidth(round(width * self.theme.scale))
        return field

    def _sync_slider(self) -> None:
        lo, hi = self.config["min"], self.config["max"]
        pos = 0 if hi <= lo else round((self.config["value"] - lo) / (hi - lo) * 1000)
        self.slider.blockSignals(True)
        self.slider.setValue(max(0, min(1000, pos)))
        self.slider.blockSignals(False)
        if not self.value_edit.hasFocus():
            self.value_edit.setText(format_number(self.config["value"]))

    def _snap(self, value: float) -> float:
        lo, step = self.config["min"], self.config["step"]
        if step > 0:
            value = lo + round((value - lo) / step) * step
            value = round(value, 10)
        return max(self.config["min"], min(self.config["max"], value))

    def _slider_moved(self, pos: int) -> None:
        lo, hi = self.config["min"], self.config["max"]
        self.set_value(self._snap(lo + (hi - lo) * pos / 1000), sync=False)

    def set_value(self, value: float, sync: bool = True) -> None:
        self.config["value"] = float(value)
        if sync:
            self._sync_slider()
        elif not self.value_edit.hasFocus():
            self.value_edit.setText(format_number(value))
        self.value_changed.emit(self.name, float(value))

    def _value_typed(self) -> None:
        try:
            value = _num(self.value_edit.text())
        except Exception:  # noqa: BLE001
            self.value_edit.setText(format_number(self.config["value"]))
            return
        if value < self.config["min"]:
            self.config["min"] = value
            self.min_edit.setText(format_number(value))
        if value > self.config["max"]:
            self.config["max"] = value
            self.max_edit.setText(format_number(value))
        self.set_value(value)

    def _range_typed(self) -> None:
        try:
            lo = _num(self.min_edit.text())
            hi = _num(self.max_edit.text())
            step = abs(_num(self.step_edit.text() or "0"))
        except Exception:  # noqa: BLE001
            lo, hi, step = self.config["min"], self.config["max"], self.config["step"]
        if hi <= lo:
            lo, hi = self.config["min"], self.config["max"]
        self.config.update(min=lo, max=hi, step=step)
        self.min_edit.setText(format_number(lo))
        self.max_edit.setText(format_number(hi))
        self.step_edit.setText(format_number(step))
        self.set_value(max(lo, min(hi, self.config["value"])))

    def toggle_play(self) -> None:
        self.playing = not self.playing
        self.play.setText("⏸" if self.playing else "▶")

    def advance(self) -> None:
        lo, hi = self.config["min"], self.config["max"]
        value = self.config["value"] + self.direction * (hi - lo) / 150
        if value >= hi:
            value, self.direction = hi, -1.0
        elif value <= lo:
            value, self.direction = lo, 1.0
        self.set_value(value)


_GREEK_CHARS = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
                "lamda": "λ", "mu": "μ", "omega": "ω", "phi": "φ", "sigma": "σ",
                "tau": "τ", "rho": "ρ", "psi": "ψ", "kappa": "κ", "nu": "ν", "xi": "ξ",
                "zeta": "ζ", "eta": "η", "chi": "χ", "Delta": "Δ", "Omega": "Ω"}


def _greek(name: str) -> str:
    return _GREEK_CHARS.get(name, name)


# --------------------------------------------------------------------------
# Tab
# --------------------------------------------------------------------------

class GraphTab(ToolTab):
    key = "graph"
    title = "Graph"
    hints = [("Scroll", "Zoom"), ("Drag", "Pan"), ("Dbl-click", "Reset")]

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent)
        self.palette = DARK_PALETTE if theme.name == "dark" else LIGHT_PALETTE
        self.rows: list[ExpressionRow] = []
        self.slider_rows: dict[str, SliderRow] = {}
        self.slider_state: dict[str, dict] = {}
        self.view = list(DEFAULT_VIEW)
        self.marks: list[tuple[float, float, str, str]] = []
        self.integral: tuple[ExpressionRow, float, float] | None = None
        self.tangent: tuple[ExpressionRow, float] | None = None
        self.active_row: ExpressionRow | None = None
        self._pan: tuple[float, float, list[float]] | None = None
        self._hover: tuple[float, float] | None = None
        self._crosshair: list = []

        self._parse_timer = QTimer(self, singleShot=True, interval=220)
        self._parse_timer.timeout.connect(self.reparse)
        self._redraw_timer = QTimer(self, singleShot=True, interval=110)
        self._redraw_timer.timeout.connect(self.redraw)
        self._hover_timer = QTimer(self, singleShot=True, interval=30)
        self._hover_timer.timeout.connect(self._update_hover)
        self._anim_timer = QTimer(self, interval=45)
        self._anim_timer.timeout.connect(self._animate)
        self._anim_timer.start()

        self._build()
        self.add_row("", reparse=False)
        self.reparse()

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        theme = self.theme
        s = theme.scale
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(round(12 * s))

        # Left panel -------------------------------------------------------
        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setFixedWidth(round(340 * s))
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(round(4 * s), round(4 * s), round(4 * s), round(4 * s))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("Transparent")
        self.left = QVBoxLayout(inner)
        self.left.setContentsMargins(round(8 * s), round(8 * s), round(8 * s), round(8 * s))
        self.left.setSpacing(round(6 * s))
        scroll.setWidget(inner)
        panel_layout.addWidget(scroll)

        self.left.addWidget(section_label("Expressions"))
        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(round(5 * s))
        self.left.addLayout(self.rows_box)
        add = QPushButton("＋  Add expression")
        add.clicked.connect(lambda: self.add_row("", focus=True))
        self.left.addWidget(add)

        self.params_title = section_label("Sliders")
        self.left.addSpacing(round(6 * s))
        self.left.addWidget(self.params_title)
        self.sliders_box = QVBoxLayout()
        self.sliders_box.setSpacing(round(5 * s))
        self.left.addLayout(self.sliders_box)

        self.left.addSpacing(round(6 * s))
        self.left.addWidget(section_label("Analysis"))
        self._build_analysis()
        self.left.addStretch(1)
        root.addWidget(panel)

        # Right side -------------------------------------------------------
        right = QVBoxLayout()
        right.setSpacing(round(8 * s))
        toolbar = QHBoxLayout()
        toolbar.setSpacing(round(6 * s))

        def tool(text: str, tip: str, slot, checkable: bool = False) -> QPushButton:
            button = QPushButton(text)
            button.setToolTip(tip)
            button.setCheckable(checkable)
            button.clicked.connect(slot)
            toolbar.addWidget(button)
            return button

        tool("⟲ Reset", "Reset the view (double-click the graph)", self.reset_view)
        self.equal_button = tool("1:1", "Equal axis scale", self._toggle_equal, True)
        self.grid_button = tool("Grid", "Show grid", self.redraw, True)
        self.grid_button.setChecked(True)
        self.fit_button = tool("Fit", "Fit the view to the visible curves", self.fit_view)
        toolbar.addStretch(1)
        tool("Save…", "Save the graph as PNG, SVG or PDF", self.save_figure)
        tool("Copy image", "Copy the graph to the clipboard as PNG", self.copy_figure)
        tool("pgfplots", "Copy TikZ/pgfplots code for LaTeX", self.copy_pgfplots)
        tool("Copy LaTeX", "Copy the selected expression as LaTeX", self.copy_latex)
        insert = tool("→ Editor", "Insert the selected expression into the editor",
                      self.insert_selected)
        insert.setObjectName("Primary")
        right.addLayout(toolbar)

        canvas_frame = QFrame()
        canvas_frame.setObjectName("Panel")
        canvas_layout = QVBoxLayout(canvas_frame)
        canvas_layout.setContentsMargins(round(3 * s), round(3 * s), round(3 * s), round(3 * s))
        self.figure = Figure(figsize=(6, 4), dpi=100)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.canvas.setStyleSheet(f"background: {theme.surface};")
        self.ax = self.figure.add_axes((0.0, 0.0, 1.0, 1.0))
        canvas_layout.addWidget(self.canvas)
        right.addWidget(canvas_frame, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(round(6 * s))
        self.bound_edits: list[QLineEdit] = []
        for label, index in (("x", 0), ("to", 1), ("y", 2), ("to", 3)):
            text = QLabel(label)
            text.setObjectName("Faint")
            bottom.addWidget(text)
            edit = QLineEdit()
            edit.setObjectName("MonoField")
            edit.setFixedWidth(round(74 * s))
            edit.editingFinished.connect(self._bounds_typed)
            bottom.addWidget(edit)
            self.bound_edits.append(edit)
            if index == 1:
                bottom.addSpacing(round(10 * s))
        bottom.addStretch(1)
        self.readout = QLabel("")
        self.readout.setObjectName("Source")
        bottom.addWidget(self.readout)
        right.addLayout(bottom)
        root.addLayout(right, 1)

        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("button_release_event", self._on_release)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("axes_leave_event", self._on_leave)
        self.canvas.mpl_connect("resize_event", self._on_resize)

    def _build_analysis(self) -> None:
        s = self.theme.scale
        grid = QGridLayout()
        grid.setHorizontalSpacing(round(5 * s))
        grid.setVerticalSpacing(round(5 * s))

        f_label = QLabel("f")
        f_label.setObjectName("Muted")
        self.f_combo = QComboBox()
        self.f_combo.currentIndexChanged.connect(lambda _i: self.redraw())
        grid.addWidget(f_label, 0, 0)
        grid.addWidget(self.f_combo, 0, 1, 1, 3)
        g_label = QLabel("g")
        g_label.setObjectName("Muted")
        self.g_combo = QComboBox()
        grid.addWidget(g_label, 1, 0)
        grid.addWidget(self.g_combo, 1, 1, 1, 3)

        buttons = [("Roots", self.analyze_roots), ("Extrema", self.analyze_extrema),
                   ("Intercepts", self.analyze_intercepts),
                   ("f ∩ g", self.analyze_intersections)]
        row = QHBoxLayout()
        row.setSpacing(round(4 * s))
        for text, slot in buttons:
            button = QPushButton(text)
            button.clicked.connect(slot)
            row.addWidget(button)
        grid.addLayout(row, 2, 0, 1, 4)

        def small(text: str, width: int = 54) -> QLineEdit:
            edit = QLineEdit(text)
            edit.setObjectName("MonoField")
            edit.setFixedWidth(round(width * s))
            return edit

        def label(text: str) -> QLabel:
            widget = QLabel(text)
            widget.setObjectName("Muted")
            return widget

        integral_row = QHBoxLayout()
        integral_row.setSpacing(round(4 * s))
        integral_row.addWidget(label("∫ from"))
        self.int_a = small("0")
        integral_row.addWidget(self.int_a)
        integral_row.addWidget(label("to"))
        self.int_b = small("1")
        integral_row.addWidget(self.int_b)
        integral_button = QPushButton("Integrate")
        integral_button.clicked.connect(self.analyze_integral)
        integral_row.addWidget(integral_button, 1)
        grid.addLayout(integral_row, 3, 0, 1, 4)

        tangent_row = QHBoxLayout()
        tangent_row.setSpacing(round(4 * s))
        tangent_row.addWidget(label("Tangent at x ="))
        self.tan_x = small("1")
        tangent_row.addWidget(self.tan_x)
        tangent_button = QPushButton("Draw")
        tangent_button.clicked.connect(self.analyze_tangent)
        tangent_row.addWidget(tangent_button, 1)
        grid.addLayout(tangent_row, 4, 0, 1, 4)

        table_row = QHBoxLayout()
        table_row.setSpacing(round(4 * s))
        table_row.addWidget(label("Table from"))
        self.table_start = small("0", 44)
        table_row.addWidget(self.table_start)
        table_row.addWidget(label("step"))
        self.table_step = small("1", 40)
        table_row.addWidget(self.table_step)
        table_button = QPushButton("Table")
        table_button.clicked.connect(self.analyze_table)
        table_row.addWidget(table_button, 1)
        grid.addLayout(table_row, 5, 0, 1, 4)

        extra = QHBoxLayout()
        self.derivative_check = QCheckBox("Show f′")
        self.derivative_check.toggled.connect(lambda _v: self.redraw())
        extra.addWidget(self.derivative_check)
        extra.addStretch(1)
        clear = QPushButton("Clear marks")
        clear.clicked.connect(self.clear_analysis)
        extra.addWidget(clear)
        grid.addLayout(extra, 6, 0, 1, 4)
        grid.setColumnStretch(1, 1)
        self.left.addLayout(grid)

        self.results_title = QLabel("")
        self.results_title.setObjectName("Muted")
        self.results_title.setWordWrap(True)
        self.results_title.hide()
        self.left.addWidget(self.results_title)
        self.results_box = QVBoxLayout()
        self.results_box.setSpacing(round(3 * s))
        self.left.addLayout(self.results_box)
        self.copy_all = QPushButton("Copy all results")
        self.copy_all.clicked.connect(self._copy_all_results)
        self.copy_all.hide()
        self.left.addWidget(self.copy_all)
        self._result_lines: list[str] = []

    # ------------------------------------------------------------- rows
    def add_row(self, text: str = "", color: str | None = None, visible: bool = True,
                focus: bool = False, reparse: bool = True) -> ExpressionRow:
        if color is None:
            used = [row.color for row in self.rows]
            color = next((c for c in self.palette if c not in used),
                         self.palette[len(self.rows) % len(self.palette)])
        row = ExpressionRow(self.theme, self.palette, color, text, visible)
        row.changed.connect(self._parse_timer.start)
        row.toggled.connect(self.redraw)
        row.removed.connect(self.remove_row)
        row.focused.connect(self._row_focused)
        row.submitted.connect(self._row_submitted)
        self.rows.append(row)
        self.rows_box.addWidget(row)
        if focus:
            QTimer.singleShot(0, row.edit.setFocus)
        if reparse:
            self.reparse()
        return row

    def remove_row(self, row: ExpressionRow) -> None:
        if row not in self.rows:
            return
        self.rows.remove(row)
        if self.active_row is row:
            self.active_row = None
        if self.integral and self.integral[0] is row:
            self.integral = None
        if self.tangent and self.tangent[0] is row:
            self.tangent = None
        row.hide()
        row.setParent(None)
        row.deleteLater()
        if not self.rows:
            self.add_row("", reparse=False)
        self.reparse()

    def _row_focused(self, row: ExpressionRow) -> None:
        self.active_row = row
        if row.spec.kind == "explicit":
            index = self.f_combo.findData(id(row))
            if index >= 0:
                self.f_combo.setCurrentIndex(index)

    def _row_submitted(self, row: ExpressionRow) -> None:
        self.reparse()
        if row is self.rows[-1] and row.text().strip():
            self.add_row("", focus=True)
        else:
            index = self.rows.index(row)
            if index + 1 < len(self.rows):
                self.rows[index + 1].edit.setFocus()

    def add_expression(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if self.rows and not self.rows[-1].text().strip():
            row = self.rows[-1]
            row.edit.setText(text)
        else:
            row = self.add_row(text, reparse=False)
        self.active_row = row
        self.reparse()
        self.canvas.setFocus()
        if row.spec.kind == "error":
            self.status.emit(f"Couldn't plot: {row.spec.error}")
        else:
            self.status.emit(f"Added “{text}” to the graph")

    # ------------------------------------------------------------- parsing
    def params(self) -> dict[str, float]:
        return {name: float(cfg["value"]) for name, cfg in self.slider_state.items()}

    def reparse(self) -> None:
        self._parse_timer.stop()
        needed: list[str] = []
        for row in self.rows:
            if row.spec.source != row.text():
                row.set_spec(plotting.classify(row.text()))
            for name in row.spec.params:
                if name not in needed:
                    needed.append(name)
        self._sync_sliders(sorted(needed))
        self._sync_combos()
        self.redraw()

    def _sync_sliders(self, needed: list[str]) -> None:
        for name in list(self.slider_rows):
            if name not in needed:
                widget = self.slider_rows.pop(name)
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        for name in needed:
            if name in self.slider_rows:
                continue
            config = self.slider_state.setdefault(
                name, {"value": 1.0, "min": plotting.DEFAULT_PARAM_RANGE[0],
                       "max": plotting.DEFAULT_PARAM_RANGE[1], "step": 0.1})
            widget = SliderRow(self.theme, name, config)
            widget.value_changed.connect(self._slider_changed)
            self.slider_rows[name] = widget
            position = sorted(self.slider_rows).index(name)
            self.sliders_box.insertWidget(position, widget)
        self.params_title.setVisible(bool(self.slider_rows))

    def _slider_changed(self, _name: str, _value: float) -> None:
        if not self._redraw_timer.isActive():
            self._redraw_timer.start(25)

    def _animate(self) -> None:
        playing = [row for row in self.slider_rows.values() if row.playing]
        if not playing or not self.isVisible():
            return
        for row in playing:
            row.advance()

    def _function_rows(self) -> list[ExpressionRow]:
        return [row for row in self.rows if row.spec.kind == "explicit"]

    def _sync_combos(self) -> None:
        for combo in (self.f_combo, self.g_combo):
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for row in self._function_rows():
                index = self.rows.index(row) + 1
                combo.addItem(f"{index}:  {row.text().strip()[:32]}", id(row))
            position = combo.findData(current)
            if position >= 0:
                combo.setCurrentIndex(position)
            if combo is self.g_combo and combo.count() > 1 \
                    and combo.currentData() == self.f_combo.currentData():
                other = 1 if self.f_combo.currentIndex() == 0 else 0
                combo.setCurrentIndex(other)
            combo.blockSignals(False)

    def _combo_row(self, combo: QComboBox) -> ExpressionRow | None:
        key = combo.currentData()
        for row in self.rows:
            if id(row) == key:
                return row
        return None

    def _selected_function(self) -> ExpressionRow | None:
        row = self._combo_row(self.f_combo)
        if row is None:
            self.status.emit("Add a function y = f(x) to analyse")
        return row

    def _selected_row(self) -> ExpressionRow | None:
        if self.active_row is not None and self.active_row in self.rows \
                and self.active_row.spec.ok:
            return self.active_row
        row = self._combo_row(self.f_combo)
        if row is not None:
            return row
        return next((r for r in self.rows if r.spec.ok), None)

    # ------------------------------------------------------------- drawing
    def _style_axes(self) -> None:
        theme = self.theme
        ax = self.ax
        xmin, xmax, ymin, ymax = self.view
        self.figure.patch.set_facecolor(theme.surface)
        ax.set_facecolor(theme.surface)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.spines["left"].set_position(("data", 0) if xmin < 0 < xmax else ("axes", 0.0))
        ax.spines["bottom"].set_position(("data", 0) if ymin < 0 < ymax else ("axes", 0.0))
        for side in ("left", "bottom"):
            ax.spines[side].set_color(theme.muted)
            ax.spines[side].set_linewidth(1.1)
            ax.spines[side].set_zorder(1.5)
        ax.tick_params(colors=theme.muted, labelsize=8.5, direction="inout", length=5,
                       pad=3)
        for label in ax.get_xticklabels() + ax.get_yticklabels():
            label.set_bbox({"facecolor": theme.surface, "edgecolor": "none", "pad": 1,
                            "alpha": 0.85})
        if self.grid_button.isChecked():
            ax.minorticks_on()
            ax.grid(True, which="major", color=theme.border_strong, linewidth=0.7, alpha=0.8)
            ax.grid(True, which="minor", color=theme.border, linewidth=0.5, alpha=0.6)
            ax.tick_params(which="minor", length=0)
        else:
            ax.grid(False)
        ax.xaxis.set_major_formatter(FuncFormatter(self._x_label))
        ax.yaxis.set_major_formatter(FuncFormatter(self._y_label))
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)

    def _x_label(self, value: float, _pos=None) -> str:
        lo, hi = self.ax.get_xlim()
        if not lo + 0.03 * (hi - lo) < value < hi - 0.03 * (hi - lo):
            return ""
        return format_number(value).replace("-", "−")

    def _y_label(self, value: float, _pos=None) -> str:
        lo, hi = self.ax.get_ylim()
        x_lo, x_hi = self.ax.get_xlim()
        if not lo + 0.04 * (hi - lo) < value < hi - 0.03 * (hi - lo):
            return ""
        if abs(value) < 1e-12 * max(1.0, hi - lo) and x_lo < 0 < x_hi:
            return ""
        return format_number(value).replace("-", "−")

    def redraw(self) -> None:
        self._redraw_timer.stop()
        ax = self.ax
        ax.clear()
        xmin, xmax, ymin, ymax = self.view
        params = self.params()
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore")
            for row in self.rows:
                if not row.visible() or not row.spec.ok:
                    continue
                try:
                    self._draw_spec(row.spec, row.color, params)
                except Exception as exc:  # noqa: BLE001 - keep the rest drawing
                    row.info.setObjectName("Error")
                    row.info.setText(f"⚠ {str(exc).splitlines()[0][:160]}")
                    row.info.show()
                    _repolish(row.info)
            self._draw_analysis(params)
        self._style_axes()
        self._crosshair = [
            ax.axvline(0, color=self.theme.faint, lw=0.8, ls="--", visible=False, zorder=5),
            ax.axhline(0, color=self.theme.faint, lw=0.8, ls="--", visible=False, zorder=5),
            ax.plot([], [], "o", ms=6, color=self.theme.accent, visible=False, zorder=6)[0],
            ax.text(0.01, 0.985, "", transform=ax.transAxes, va="top", ha="left",
                    fontsize=9, color=self.theme.text, family="monospace", zorder=7,
                    bbox={"facecolor": self.theme.surface_alt, "edgecolor": self.theme.border,
                          "boxstyle": "round,pad=0.35"}, visible=False),
        ]
        self._update_bound_edits()
        self.canvas.draw_idle()

    def _draw_spec(self, spec: PlotSpec, color: str, params: dict[str, float]) -> None:
        ax = self.ax
        xmin, xmax, ymin, ymax = self.view
        width = 2.2
        if spec.kind in {"explicit", "explicit_y"}:
            xs, ys = plotting.sample_explicit(spec, params, xmin, xmax, ymin, ymax)
            ax.plot(xs, ys, color=color, lw=width, solid_capstyle="round", zorder=3)
        elif spec.kind == "vline":
            ax.axvline(plotting.vline_value(spec, params), color=color, lw=width, zorder=3)
        elif spec.kind in {"parametric", "polar"}:
            xs, ys = plotting.sample_parametric(spec, params)
            ax.plot(xs, ys, color=color, lw=width, zorder=3)
        elif spec.kind == "implicit":
            gx, gy, gz = plotting.sample_grid(spec, params, xmin, xmax, ymin, ymax)
            if np.isfinite(gz).any() and np.nanmin(gz) <= 0 <= np.nanmax(gz):
                ax.contour(gx, gy, np.ma.masked_invalid(gz), levels=[0], colors=[color],
                           linewidths=width, zorder=3)
        elif spec.kind == "inequality":
            style = "--" if spec.op in {"<", ">"} else "-"
            if spec.boundary is not None:
                bounded = PlotSpec("explicit", spec.source, expr=spec.boundary,
                                   params=spec.params)
                xs, ys = plotting.sample_explicit(bounded, params, xmin, xmax, ymin, ymax)
                span = ymax - ymin
                edge = ymax + span if spec.op in {">", ">="} else ymin - span
                finite = np.isfinite(ys)
                ax.fill_between(xs, np.where(finite, ys, edge), edge, where=finite,
                                color=color, alpha=0.2, linewidth=0, zorder=2)
                ax.plot(xs, ys, color=color, lw=width, ls=style, zorder=3)
            else:
                gx, gy, gz = plotting.sample_grid(spec, params, xmin, xmax, ymin, ymax)
                mask = plotting.inequality_mask(spec, gz)
                if mask.any():
                    ax.contourf(gx, gy, mask.astype(float), levels=[0.5, 1.5],
                                colors=[color], alpha=0.2, zorder=2)
                if np.isfinite(gz).any() and np.nanmin(gz) <= 0 <= np.nanmax(gz):
                    ax.contour(gx, gy, np.ma.masked_invalid(gz), levels=[0], colors=[color],
                               linewidths=width, linestyles=style, zorder=3)
        elif spec.kind == "points":
            xs = [p[0] for p in spec.points]
            ys = [p[1] for p in spec.points]
            ax.scatter(xs, ys, s=42, color=color, zorder=4, edgecolors=self.theme.surface,
                       linewidths=1.2)
            if len(spec.points) <= 12:
                for x, y in spec.points:
                    ax.annotate(f"({format_number(x)}, {format_number(y)})", (x, y),
                                textcoords="offset points", xytext=(7, 6), fontsize=8.5,
                                color=self.theme.muted, zorder=4)

    def _draw_analysis(self, params: dict[str, float]) -> None:
        ax = self.ax
        xmin, xmax, ymin, ymax = self.view
        row = self._combo_row(self.f_combo)
        if self.derivative_check.isChecked() and row is not None and row.visible():
            try:
                deriv = plotting.derivative_spec(row.spec)
                xs, ys = plotting.sample_explicit(deriv, params, xmin, xmax, ymin, ymax)
                ax.plot(xs, ys, color=row.color, lw=1.6, ls="--", alpha=0.8, zorder=3)
            except Exception:  # noqa: BLE001
                pass
        if self.integral and self.integral[0] in self.rows:
            irow, a, b = self.integral
            try:
                func = plotting.make_function(irow.spec, params)
                xs = np.linspace(a, b, 600)
                ys = func(xs)
                ax.fill_between(xs, 0, ys, where=np.isfinite(ys), color=irow.color,
                                alpha=0.28, linewidth=0, zorder=2)
            except Exception:  # noqa: BLE001
                pass
        if self.tangent and self.tangent[0] in self.rows:
            trow, x0 = self.tangent
            try:
                slope, intercept, _latex = plotting.tangent_line(trow.spec, params, x0)
                xs = np.array([xmin, xmax])
                ax.plot(xs, slope * xs + intercept, color=self.theme.text, lw=1.3,
                        ls="-.", alpha=0.85, zorder=4)
                ax.scatter([x0], [slope * x0 + intercept], s=36, color=self.theme.text,
                           zorder=5)
            except Exception:  # noqa: BLE001
                pass
        for x, y, label, color in self.marks:
            ax.scatter([x], [y], s=46, color=color, edgecolors=self.theme.surface,
                       linewidths=1.5, zorder=6)
            ax.annotate(label, (x, y), textcoords="offset points", xytext=(8, 8),
                        fontsize=8.5, color=self.theme.text, zorder=6,
                        bbox={"facecolor": self.theme.surface_alt,
                              "edgecolor": self.theme.border, "boxstyle": "round,pad=0.25",
                              "alpha": 0.92})

    # ------------------------------------------------------------- view
    def _set_view(self, view: list[float], resample: bool = True) -> None:
        self.view = [float(v) for v in view]
        self.ax.set_xlim(self.view[0], self.view[1])
        self.ax.set_ylim(self.view[2], self.view[3])
        self._update_bound_edits()
        self.canvas.draw_idle()
        if resample:
            self._redraw_timer.start(110)

    def reset_view(self) -> None:
        self.view = list(DEFAULT_VIEW)
        if self.equal_button.isChecked():
            self._enforce_aspect()
        self.redraw()

    def fit_view(self) -> None:
        params = self.params()
        xs_all: list[np.ndarray] = []
        ys_all: list[np.ndarray] = []
        xmin, xmax, ymin, ymax = self.view
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore")
            for row in self.rows:
                spec = row.spec
                if not row.visible() or not spec.ok:
                    continue
                try:
                    if spec.kind == "explicit":
                        xs, ys = plotting.sample_explicit(spec, params, xmin, xmax, -1e9, 1e9)
                    elif spec.kind in {"parametric", "polar"}:
                        xs, ys = plotting.sample_parametric(spec, params)
                    elif spec.kind == "points":
                        xs = np.array([p[0] for p in spec.points])
                        ys = np.array([p[1] for p in spec.points])
                    else:
                        continue
                except Exception:  # noqa: BLE001
                    continue
                xs_all.append(np.asarray(xs))
                ys_all.append(np.asarray(ys))
        if not ys_all:
            self.status.emit("Nothing to fit")
            return
        xs = np.concatenate(xs_all)
        ys = np.concatenate(ys_all)
        keep = np.isfinite(xs) & np.isfinite(ys)
        if not keep.any():
            return
        xs, ys = xs[keep], ys[keep]
        lo, hi = np.percentile(ys, [2, 98])
        x_lo, x_hi = xs.min(), xs.max()
        if hi - lo < 1e-9:
            lo, hi = lo - 1, hi + 1
        if x_hi - x_lo < 1e-9:
            x_lo, x_hi = x_lo - 1, x_hi + 1
        pad_y = (hi - lo) * 0.12
        pad_x = (x_hi - x_lo) * 0.05
        self.view = [float(x_lo - pad_x), float(x_hi + pad_x), float(lo - pad_y),
                     float(hi + pad_y)]
        if self.equal_button.isChecked():
            self._enforce_aspect()
        self.redraw()

    def _toggle_equal(self) -> None:
        if self.equal_button.isChecked():
            self._enforce_aspect()
        self.redraw()

    def _enforce_aspect(self) -> None:
        width = max(1, self.canvas.width())
        height = max(1, self.canvas.height())
        xmin, xmax, ymin, ymax = self.view
        y_center = (ymin + ymax) / 2
        y_range = (xmax - xmin) * height / width
        self.view = [xmin, xmax, y_center - y_range / 2, y_center + y_range / 2]

    def _on_resize(self, _event) -> None:
        if self.equal_button.isChecked():
            self._enforce_aspect()
            self._set_view(self.view)

    def _update_bound_edits(self) -> None:
        for edit, value in zip(self.bound_edits, self.view):
            if not edit.hasFocus():
                edit.setText(format_number(value))

    def _bounds_typed(self) -> None:
        try:
            values = [_num(edit.text()) for edit in self.bound_edits]
        except Exception:  # noqa: BLE001
            self._update_bound_edits()
            self.status.emit("Bounds must be numbers")
            return
        if values[0] >= values[1] or values[2] >= values[3]:
            self._update_bound_edits()
            self.status.emit("Each minimum must be smaller than its maximum")
            return
        if values != self.view:
            self.equal_button.setChecked(False)
            self.view = values
            self.redraw()

    # ------------------------------------------------------------- mouse
    def _on_scroll(self, event) -> None:
        factor = 0.85 if event.button == "up" else 1 / 0.85
        xmin, xmax, ymin, ymax = self.view
        cx = event.xdata if event.xdata is not None else (xmin + xmax) / 2
        cy = event.ydata if event.ydata is not None else (ymin + ymax) / 2
        new = [cx + (xmin - cx) * factor, cx + (xmax - cx) * factor,
               cy + (ymin - cy) * factor, cy + (ymax - cy) * factor]
        if new[1] - new[0] < 1e-9 or new[1] - new[0] > 1e9:
            return
        self._set_view(new)

    def _on_press(self, event) -> None:
        if event.inaxes is not self.ax:
            return
        if event.dblclick:
            self.reset_view()
            return
        if event.button == 1:
            self._pan = (event.x, event.y, list(self.view))
            self.canvas.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _on_release(self, _event) -> None:
        if self._pan is not None:
            self._pan = None
            self.canvas.unsetCursor()
            self._redraw_timer.start(30)

    def _on_motion(self, event) -> None:
        if self._pan is not None:
            x0, y0, view = self._pan
            bbox = self.ax.get_window_extent()
            dx = (event.x - x0) * (view[1] - view[0]) / max(1.0, bbox.width)
            dy = (event.y - y0) * (view[3] - view[2]) / max(1.0, bbox.height)
            self._set_view([view[0] - dx, view[1] - dx, view[2] - dy, view[3] - dy])
            return
        if event.inaxes is self.ax and event.xdata is not None:
            self._hover = (event.xdata, event.ydata)
            if not self._hover_timer.isActive():
                self._hover_timer.start()

    def _on_leave(self, _event) -> None:
        self._hover = None
        for artist in self._crosshair:
            artist.set_visible(False)
        self.readout.setText("")
        self.canvas.draw_idle()

    def _update_hover(self) -> None:
        if self._hover is None or len(self._crosshair) < 4:
            return
        x, y = self._hover
        vline, hline, dot, text = self._crosshair
        vline.set_xdata([x, x])
        hline.set_ydata([y, y])
        vline.set_visible(True)
        hline.set_visible(True)
        readout = f"x = {format_number(x)}   y = {format_number(y)}"
        label = f"({format_number(x)}, {format_number(y)})"
        dot.set_visible(False)
        row = self._combo_row(self.f_combo)
        if row is not None and row.visible():
            try:
                fx = float(plotting.make_function(row.spec, self.params())(np.array([x]))[0])
            except Exception:  # noqa: BLE001
                fx = float("nan")
            if math.isfinite(fx):
                dot.set_data([x], [fx])
                dot.set_color(row.color)
                dot.set_visible(True)
                name = row.spec.name or "f"
                label += f"\n{name}({format_number(x)}) = {format_number(fx)}"
                readout += f"   {name}(x) = {format_number(fx)}"
        text.set_text(label)
        text.set_visible(True)
        self.readout.setText(readout)
        self.canvas.draw_idle()

    # ------------------------------------------------------------- analysis
    def _set_results(self, title: str, lines: list[tuple[str, str]]) -> None:
        while self.results_box.count():
            item = self.results_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self.results_title.setText(title)
        self.results_title.setVisible(bool(title))
        self._result_lines = [copy for _shown, copy in lines]
        s = self.theme.scale
        for shown, copy_text in lines:
            frame = QFrame()
            frame.setObjectName("Card")
            layout = QHBoxLayout(frame)
            layout.setContentsMargins(round(8 * s), round(3 * s), round(4 * s), round(3 * s))
            label = QLabel(shown)
            label.setObjectName("Source")
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setWordWrap(True)
            layout.addWidget(label, 1)
            button = QToolButton()
            button.setObjectName("Tool")
            button.setText("Copy")
            button.clicked.connect(lambda _c=False, t=copy_text: self.copy(t, "result"))
            layout.addWidget(button)
            self.results_box.addWidget(frame)
        self.copy_all.setVisible(len(lines) > 1)

    def _copy_all_results(self) -> None:
        self.copy("\n".join(self._result_lines), "results")

    def clear_analysis(self) -> None:
        self.marks.clear()
        self.integral = None
        self.tangent = None
        self.derivative_check.setChecked(False)
        self._set_results("", [])
        self.redraw()

    def _pt(self, x: float, y: float) -> str:
        return f"({format_number(x)}, {format_number(y)})"

    def analyze_roots(self) -> None:
        row = self._selected_function()
        if row is None:
            return
        try:
            func = plotting.make_function(row.spec, self.params())
            roots = plotting.find_roots(func, self.view[0], self.view[1])
        except Exception as exc:  # noqa: BLE001
            self.status.emit(f"Roots failed: {exc}")
            return
        self.marks = [(r, 0.0, f"x = {format_number(r)}", row.color) for r in roots]
        self._set_results(
            f"{len(roots)} root{'s' if len(roots) != 1 else ''} of {row.text().strip()} "
            "in view" if roots else "No roots in the visible range",
            [(f"x = {format_number(r)}", format_number(r)) for r in roots],
        )
        self.redraw()

    def analyze_extrema(self) -> None:
        row = self._selected_function()
        if row is None:
            return
        try:
            extrema = plotting.find_extrema(row.spec, self.params(), self.view[0], self.view[1])
        except Exception as exc:  # noqa: BLE001
            self.status.emit(f"Extrema failed: {exc}")
            return
        self.marks = [(x, y, f"{kind} {self._pt(x, y)}", row.color) for x, y, kind in extrema]
        self._set_results(
            f"{len(extrema)} local extrem{'a' if len(extrema) != 1 else 'um'} in view"
            if extrema else "No local extrema in the visible range",
            [(f"{'max' if kind == 'max' else 'min'}  {self._pt(x, y)}", self._pt(x, y))
             for x, y, kind in extrema],
        )
        self.redraw()

    def analyze_intercepts(self) -> None:
        row = self._selected_function()
        if row is None:
            return
        params = self.params()
        lines: list[tuple[str, str]] = []
        self.marks = []
        try:
            y0 = plotting.y_intercept(row.spec, params)
            if y0 is not None:
                self.marks.append((0.0, y0, f"y-int {self._pt(0, y0)}", row.color))
                lines.append((f"y-intercept  {self._pt(0, y0)}", self._pt(0, y0)))
            func = plotting.make_function(row.spec, params)
            for root in plotting.find_roots(func, self.view[0], self.view[1]):
                self.marks.append((root, 0.0, f"x-int {self._pt(root, 0)}", row.color))
                lines.append((f"x-intercept  {self._pt(root, 0)}", self._pt(root, 0)))
        except Exception as exc:  # noqa: BLE001
            self.status.emit(f"Intercepts failed: {exc}")
            return
        self._set_results("Intercepts" if lines else "No intercepts in view", lines)
        self.redraw()

    def analyze_intersections(self) -> None:
        f_row = self._combo_row(self.f_combo)
        g_row = self._combo_row(self.g_combo)
        if f_row is None or g_row is None or f_row is g_row:
            self.status.emit("Pick two different functions f and g")
            return
        try:
            points = plotting.find_intersections(f_row.spec, g_row.spec, self.params(),
                                                 self.view[0], self.view[1])
        except Exception as exc:  # noqa: BLE001
            self.status.emit(f"Intersection failed: {exc}")
            return
        self.marks = [(x, y, self._pt(x, y), self.theme.text) for x, y in points]
        self._set_results(
            f"{len(points)} intersection{'s' if len(points) != 1 else ''} in view"
            if points else "No intersections in the visible range",
            [(self._pt(x, y), self._pt(x, y)) for x, y in points],
        )
        self.redraw()

    def analyze_integral(self) -> None:
        row = self._selected_function()
        if row is None:
            return
        try:
            a, b = _num(self.int_a.text()), _num(self.int_b.text())
            value, error = plotting.definite_integral(row.spec, self.params(), a, b)
        except Exception as exc:  # noqa: BLE001
            self.status.emit(f"Integral failed: {exc}")
            return
        self.integral = (row, a, b)
        expr_latex = sp.latex(row.spec.expr)
        latex = (rf"\int_{{{format_number(a)}}}^{{{format_number(b)}}} {expr_latex}\,dx"
                 rf" \approx {format_number(value)}")
        lines = [(f"∫ from {format_number(a)} to {format_number(b)} ≈ {format_number(value)}",
                  format_number(value)), ("LaTeX", latex)]
        lines[1] = (latex, latex)
        self._set_results(f"Signed area (error ≈ {error:.1e})", lines)
        self.redraw()

    def analyze_tangent(self) -> None:
        row = self._selected_function()
        if row is None:
            return
        try:
            x0 = _num(self.tan_x.text())
            slope, intercept, latex = plotting.tangent_line(row.spec, self.params(), x0)
        except Exception as exc:  # noqa: BLE001
            self.status.emit(f"Tangent failed: {exc}")
            return
        self.tangent = (row, x0)
        y0 = slope * x0 + intercept
        self._set_results(f"Tangent at x = {format_number(x0)}", [
            (latex.replace("y = ", "y = "), latex),
            (f"slope  {format_number(slope)}", format_number(slope)),
            (f"point  {self._pt(x0, y0)}", self._pt(x0, y0)),
        ])
        self.redraw()

    def analyze_table(self) -> None:
        row = self._selected_function()
        if row is None:
            return
        try:
            start, step = _num(self.table_start.text()), _num(self.table_step.text())
            if step == 0:
                raise ValueError("step must not be zero")
            table = plotting.value_table(row.spec, self.params(), start, step, 11)
        except Exception as exc:  # noqa: BLE001
            self.status.emit(f"Table failed: {exc}")
            return
        name = row.spec.name or "f"
        lines = [(f"{format_number(x):>9}   {format_number(y) if y is not None else '—':>12}",
                  f"{format_number(x)}\t{format_number(y) if y is not None else ''}")
                 for x, y in table]
        self._set_results(f"x  →  {name}(x)", lines)
        tsv = "x\t" + name + "(x)\n" + "\n".join(copy for _s, copy in lines)
        self._result_lines = [tsv]
        self.copy_all.setText("Copy table")
        self.copy_all.show()

    # ------------------------------------------------------------- export
    def _visible_items(self) -> list[tuple[PlotSpec, str]]:
        return [(row.spec, row.color) for row in self.rows if row.visible() and row.spec.ok]

    def _hide_crosshair(self) -> list[bool]:
        states = [artist.get_visible() for artist in self._crosshair]
        for artist in self._crosshair:
            artist.set_visible(False)
        return states

    def _restore_crosshair(self, states: list[bool]) -> None:
        for artist, visible in zip(self._crosshair, states):
            artist.set_visible(visible)

    def figure_png(self, dpi: int = 200) -> bytes:
        states = self._hide_crosshair()
        buffer = io.BytesIO()
        try:
            self.figure.savefig(buffer, format="png", dpi=dpi,
                                facecolor=self.figure.get_facecolor())
        finally:
            self._restore_crosshair(states)
        return buffer.getvalue()

    def save_figure(self) -> None:
        default = str(Path.home() / "Pictures" / "graph.png")
        path, chosen = QFileDialog.getSaveFileName(
            self, "Save graph", default, "PNG image (*.png);;SVG vector (*.svg);;PDF (*.pdf)"
        )
        if not path:
            return
        if not Path(path).suffix:
            path += {"SVG": ".svg", "PDF": ".pdf"}.get(chosen.split()[0], ".png")
        states = self._hide_crosshair()
        try:
            self.figure.savefig(path, dpi=200, facecolor=self.figure.get_facecolor())
            self.status.emit(f"✓ Saved {path}")
        except Exception as exc:  # noqa: BLE001
            self.status.emit(f"Save failed: {exc}")
        finally:
            self._restore_crosshair(states)

    def copy_figure(self) -> None:
        self.copy_image(self.figure_png(), "graph image")

    def pgfplots(self) -> str:
        return plotting.pgfplots_code(self._visible_items(), self.params(), tuple(self.view),
                                      self.grid_button.isChecked(),
                                      self.equal_button.isChecked())

    def copy_pgfplots(self) -> None:
        if not self._visible_items():
            self.status.emit("Nothing to export")
            return
        try:
            code = self.pgfplots()
        except Exception as exc:  # noqa: BLE001
            self.status.emit(f"pgfplots export failed: {exc}")
            return
        self.copy(code, "pgfplots code")

    def copy_latex(self) -> None:
        row = self._selected_row()
        if row is None:
            self.status.emit("Nothing selected")
            return
        self.copy(row.spec.latex, "LaTeX")

    def insert_selected(self) -> None:
        row = self._selected_row()
        if row is None:
            self.status.emit("Nothing selected")
            return
        self.insert_latex.emit(row.spec.latex)
        self.status.emit("Sent to the editor")

    # ------------------------------------------------------------- state
    def state(self) -> dict:
        return {
            "expressions": [{"text": row.text(), "color": row.color, "visible": row.visible()}
                            for row in self.rows],
            "sliders": {name: dict(cfg) for name, cfg in self.slider_state.items()},
            "view": list(self.view),
            "grid": self.grid_button.isChecked(),
            "equal": self.equal_button.isChecked(),
            "derivative": self.derivative_check.isChecked(),
        }

    def restore(self, data: dict) -> None:
        if not isinstance(data, dict):
            return
        sliders = data.get("sliders")
        if isinstance(sliders, dict):
            for name, cfg in sliders.items():
                if not isinstance(cfg, dict):
                    continue
                try:
                    clean = {key: float(cfg.get(key, default)) for key, default in
                             (("value", 1.0), ("min", -10.0), ("max", 10.0), ("step", 0.1))}
                except (TypeError, ValueError):
                    continue
                if clean["max"] > clean["min"]:
                    self.slider_state[str(name)] = clean
        expressions = data.get("expressions")
        if isinstance(expressions, list):
            for row in list(self.rows):
                self.rows.remove(row)
                row.hide()
                row.setParent(None)
                row.deleteLater()
            for item in expressions:
                if not isinstance(item, dict):
                    continue
                color = item.get("color")
                if not isinstance(color, str) or not color.startswith("#"):
                    color = None
                self.add_row(str(item.get("text", "")), color, bool(item.get("visible", True)),
                             reparse=False)
            if not self.rows:
                self.add_row("", reparse=False)
        view = data.get("view")
        if isinstance(view, list) and len(view) == 4:
            try:
                values = [float(v) for v in view]
                if values[0] < values[1] and values[2] < values[3] and all(
                        math.isfinite(v) for v in values):
                    self.view = values
            except (TypeError, ValueError):
                pass
        self.grid_button.setChecked(bool(data.get("grid", True)))
        self.equal_button.setChecked(bool(data.get("equal", False)))
        self.derivative_check.blockSignals(True)
        self.derivative_check.setChecked(bool(data.get("derivative", False)))
        self.derivative_check.blockSignals(False)
        self.reparse()

    def focus_primary(self) -> None:
        if not self.rows:
            self.add_row("", reparse=False)
        target = next((row for row in self.rows if not row.text().strip()), self.rows[-1])
        target.edit.setFocus()

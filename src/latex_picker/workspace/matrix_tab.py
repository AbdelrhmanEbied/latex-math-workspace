"""Linear algebra workspace: matrix editor, row operations and computations."""

from __future__ import annotations

import itertools
import random
import re
import threading
from typing import Any, Callable

import sympy as sp
from PyQt6.QtCore import QObject, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QKeySequence, QPainter, QPen, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..theme import Theme
from . import linalg as L
from .widgets import FlowLayout, MathLabel, ToolTab, section_label

FORMATS = [("bmatrix", "[ ] bmatrix"), ("pmatrix", "( ) pmatrix"), ("vmatrix", "| | vmatrix"),
           ("Vmatrix", "‖ ‖ Vmatrix"), ("Bmatrix", "{ } Bmatrix"), ("matrix", "matrix"),
           ("plain", "Plain text"), ("python", "Python list"), ("matlab", "MATLAB")]
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,7}$")
_job_ids = itertools.count(1)


# --------------------------------------------------------------------------
# Native matrix display
# --------------------------------------------------------------------------

class MatrixView(QWidget):
    """Paints a matrix with brackets; independent of the LaTeX renderer."""

    def __init__(self, theme: Theme, matrix: sp.Matrix, aug_col: int | None = None,
                 decimal: bool = False, highlight: set[tuple[int, int]] | None = None,
                 changed_rows: set[int] | None = None, size: float = 14,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.matrix = sp.Matrix(matrix)
        self.aug_col = aug_col
        self.decimal = decimal
        self.highlight = highlight or set()
        self.changed_rows = changed_rows or set()
        self.font_ = QFont(theme.math_family)
        self.font_.setPixelSize(max(9, round(size * theme.scale)))
        self._layout()
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_decimal(self, decimal: bool) -> None:
        self.decimal = decimal
        self._layout()
        self.updateGeometry()
        self.update()

    def _layout(self) -> None:
        metrics = QFontMetricsF(self.font_)
        rows, cols = self.matrix.shape
        self._texts = [[L.fmt_entry(self.matrix[r, c], self.decimal) for c in range(cols)]
                       for r in range(rows)]
        self._col_w = [max([metrics.horizontalAdvance(self._texts[r][c]) for r in range(rows)]
                           + [metrics.horizontalAdvance("0")]) for c in range(cols)]
        self._row_h = metrics.height() * 1.35
        self._gap = metrics.horizontalAdvance("0") * 1.6
        self._bracket = metrics.horizontalAdvance("0") * 0.9
        width = sum(self._col_w) + self._gap * max(0, cols - 1) + 2 * self._bracket + 16
        if self.aug_col:
            width += self._gap * 0.6
        height = max(1, rows) * self._row_h + 10
        self._size = QSize(int(width) + 2, int(height) + 2)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self._size

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self._size

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setFont(self.font_)
        rows, cols = self.matrix.shape
        top, bottom = 5.0, 5.0 + rows * self._row_h
        left = 4.0
        pen = QPen(QColor(self.theme.muted), max(1.2, 1.4 * self.theme.scale))
        painter.setPen(pen)
        tick = self._bracket * 0.55
        right = self._size.width() - 6.0
        painter.drawLine(int(left), int(top), int(left), int(bottom))
        painter.drawLine(int(left), int(top), int(left + tick), int(top))
        painter.drawLine(int(left), int(bottom), int(left + tick), int(bottom))
        painter.drawLine(int(right), int(top), int(right), int(bottom))
        painter.drawLine(int(right - tick), int(top), int(right), int(top))
        painter.drawLine(int(right - tick), int(bottom), int(right), int(bottom))
        x = left + self._bracket + 4
        for c in range(cols):
            if self.aug_col and c == self.aug_col:
                bar_x = x - self._gap * 0.8
                painter.setPen(QPen(QColor(self.theme.faint), 1))
                painter.drawLine(int(bar_x), int(top + 2), int(bar_x), int(bottom - 2))
                x += self._gap * 0.6
            for r in range(rows):
                rect = QRectF(x, top + r * self._row_h, self._col_w[c], self._row_h)
                if (r, c) in self.highlight:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(self.theme.accent_soft))
                    painter.drawRoundedRect(rect.adjusted(-4, 2, 4, -2), 4, 4)
                    painter.setPen(QColor(self.theme.accent))
                elif r in self.changed_rows:
                    painter.setPen(QColor(self.theme.accent))
                else:
                    painter.setPen(QColor(self.theme.math))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._texts[r][c])
            x += self._col_w[c] + self._gap
        painter.end()


# --------------------------------------------------------------------------
# Output cards
# --------------------------------------------------------------------------

class Card(QFrame):
    def __init__(self, tab: MatrixTab, title: str, subtitle: str = "") -> None:
        super().__init__()
        self.tab = tab
        self.setObjectName("Card")
        self.latex_parts: list[str] = []
        self.matrix: sp.Matrix | None = None
        self.aug_col: int | None = None
        layout = QVBoxLayout(self)
        s = tab.theme.scale
        layout.setContentsMargins(round(12 * s), round(9 * s), round(12 * s), round(9 * s))
        layout.setSpacing(round(6 * s))
        header = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: 700;")
        header.addWidget(title_label)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("Muted")
            sub.setWordWrap(True)
            header.addWidget(sub, 1)
        else:
            header.addStretch(1)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(4)
        header.addLayout(self.buttons)
        layout.addLayout(header)
        self.body = QVBoxLayout()
        self.body.setSpacing(round(6 * s))
        layout.addLayout(self.body)
        self._add_button("Copy", "Copy as LaTeX", self._copy)
        self._add_button("→ Editor", "Insert into the LaTeX editor",
                         lambda: tab.insert_latex.emit(self.latex()))

    def _add_button(self, text: str, tip: str, slot: Callable) -> QPushButton:
        button = QPushButton(text)
        button.setToolTip(tip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(slot)
        self.buttons.addWidget(button)
        return button

    def latex(self) -> str:
        return " \\\\ ".join(self.latex_parts) if len(self.latex_parts) > 1 else (
            self.latex_parts[0] if self.latex_parts else "")

    def _copy(self) -> None:
        if self.matrix is not None and len(self.latex_parts) <= 1 and \
                self.tab.copy_format() in {"plain", "python", "matlab"}:
            self.tab.copy(L.format_matrix(self.matrix, self.tab.copy_format(), self.aug_col,
                                          self.tab.decimal()), "matrix")
            return
        latex = self.latex()
        if len(self.latex_parts) > 1:
            latex = "\\begin{gathered} " + latex + " \\end{gathered}"
        self.tab.copy(latex)

    def add_matrix(self, matrix: sp.Matrix, label: str = "", aug_col: int | None = None,
                   highlight: set | None = None, savable: bool = True,
                   changed_rows: set[int] | None = None) -> None:
        matrix = sp.Matrix(matrix)
        row = QHBoxLayout()
        if label:
            text = QLabel(label)
            text.setObjectName("PreviewText")
            text.setStyleSheet(f"font-size: {round(15 * self.tab.theme.scale)}px;")
            row.addWidget(text)
        view = MatrixView(self.tab.theme, matrix, aug_col, self.tab.decimal(), highlight,
                          changed_rows)
        self.tab.register_view(view)
        row.addWidget(view)
        row.addStretch(1)
        self.body.addLayout(row)
        latex_label = re.sub(r"[ =]+$", "", label)
        body = L.matrix_to_latex(matrix, self.tab.latex_env(), aug_col, self.tab.decimal())
        self.latex_parts.append(f"{self._label_latex(latex_label)} = {body}" if latex_label
                                else body)
        if self.matrix is None:
            self.matrix, self.aug_col = matrix, aug_col
            if savable:
                self._add_button("Save", "Save as a new named matrix",
                                 lambda: self.tab.save_matrix(self.matrix))

    @staticmethod
    def _label_latex(label: str) -> str:
        table = {"⁻¹": "^{-1}", "ᵀ": "^{T}", "λ": r"\lambda", "·": r"\cdot "}
        for key, value in table.items():
            label = label.replace(key, value)
        return label

    def add_latex(self, latex: str, size: float = 18) -> None:
        label = MathLabel(self.tab.theme, size)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        label.set_latex(latex)
        self.body.addWidget(label)
        self.latex_parts.append(latex)

    def add_text(self, text: str, muted: bool = True) -> None:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if muted:
            label.setObjectName("Muted")
        self.body.addWidget(label)


class _Signals(QObject):
    finished = pyqtSignal(int, object, object)   # job id, result, error


class MatrixTable(QTableWidget):
    pasted = pyqtSignal(str)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.matches(QKeySequence.StandardKey.Paste):
            text = QApplication.clipboard().text()
            if "\n" in text.strip() or "\\begin" in text or text.strip().startswith("["):
                self.pasted.emit(text)
                return
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and not self.state() == \
                QAbstractItemView.State.EditingState:
            for item in self.selectedItems():
                item.setText("0")
            return
        super().keyPressEvent(event)


# --------------------------------------------------------------------------
# The tab
# --------------------------------------------------------------------------

class MatrixTab(ToolTab):
    key = "matrix"
    title = "Matrix"
    hints = [("Ctrl+Enter", "Apply op"), ("Ctrl+Z", "Undo op"), ("Ctrl+V", "Paste matrix")]

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent)
        self.matrices: dict[str, dict[str, Any]] = {}
        self.current: str | None = None
        self._loading = False
        self._views: list[MatrixView] = []
        self._jobs: dict[int, Callable[[Any], None]] = {}
        self._signals = _Signals(self)
        self._signals.finished.connect(self._on_job_finished)
        self.synchronous = False
        # row-operation session
        self.work_steps: list[L.Step] = []
        self.redo_stack: list[L.Step] = []
        self.work_aug: int | None = None
        self.work_source = ""
        self._build_ui()
        self._add_matrix("A", [["2", "1", "-1", "8"], ["-3", "-1", "2", "-11"],
                               ["-2", "1", "2", "-3"]], aug=True)
        self._add_matrix("B", [["1", "2"], ["3", "4"]])
        self._select("A")

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        s = self.theme.scale
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter)

        left = QWidget()
        left.setObjectName("Transparent")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, round(6 * s), 0)
        left_layout.setSpacing(round(8 * s))
        left_layout.addWidget(self._build_editor(), 3)
        left_layout.addWidget(self._build_tools(), 4)
        splitter.addWidget(left)
        splitter.addWidget(self._build_output())
        splitter.setSizes([round(560 * s), round(560 * s)])

        apply_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        apply_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        apply_shortcut.activated.connect(self._apply_typed_or_selected)
        undo = QShortcut(QKeySequence("Ctrl+Z"), self.tools)
        undo.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        undo.activated.connect(self.undo_op)

    def _build_editor(self) -> QWidget:
        s = self.theme.scale
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(round(10 * s), round(10 * s), round(10 * s), round(10 * s))
        layout.setSpacing(round(10 * s))

        side = QVBoxLayout()
        side.addWidget(section_label("Matrices"))
        self.name_list = QListWidget()
        self.name_list.setFixedWidth(round(84 * s))
        self.name_list.setToolTip("Double-click to rename")
        self.name_list.currentTextChanged.connect(self._on_name_selected)
        self.name_list.itemDoubleClicked.connect(self._start_rename)
        self.name_list.itemChanged.connect(self._on_renamed)
        side.addWidget(self.name_list, 1)
        grid = QGridLayout()
        grid.setSpacing(3)
        for index, (text, tip, slot) in enumerate([
            ("+", "New matrix", self.new_matrix),
            ("⧉", "Duplicate", self.duplicate_matrix),
            ("✕", "Delete", self.delete_matrix),
            ("✎", "Rename", lambda: self._start_rename(self.name_list.currentItem())),
        ]):
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            grid.addWidget(button, index // 2, index % 2)
        side.addLayout(grid)
        layout.addLayout(side)

        main = QVBoxLayout()
        main.setSpacing(round(6 * s))
        header = QHBoxLayout()
        self.title_label = QLabel("A")
        self.title_label.setStyleSheet(f"font-size: {round(17 * s)}px; font-weight: 700;")
        header.addWidget(self.title_label)
        header.addSpacing(8)
        header.addWidget(QLabel("Rows"))
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 10)
        header.addWidget(self.rows_spin)
        header.addWidget(QLabel("Cols"))
        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(1, 10)
        header.addWidget(self.cols_spin)
        self.aug_check = QCheckBox("Augmented")
        self.aug_check.setToolTip("Draw a bar before the last column: [A | b]")
        header.addWidget(self.aug_check)
        header.addStretch(1)
        main.addLayout(header)
        self.rows_spin.valueChanged.connect(self._resize_current)
        self.cols_spin.valueChanged.connect(self._resize_current)
        self.aug_check.toggled.connect(self._on_aug_toggled)

        self.table = MatrixTable()
        self.table.horizontalHeader().setDefaultSectionSize(round(64 * s))
        self.table.verticalHeader().setDefaultSectionSize(round(30 * s))
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.itemChanged.connect(self._on_cell_changed)
        self.table.pasted.connect(self._import_text)
        main.addWidget(self.table, 1)

        fills = FlowLayout(spacing=4)
        for text, tip, slot in [
            ("0", "Fill with zeros", lambda: self._fill("zero")),
            ("I", "Identity", lambda: self._fill("identity")),
            ("🎲", "Random integers −9…9", lambda: self._fill("random")),
            ("Aᵀ", "Transpose in place", lambda: self._fill("transpose")),
            ("Import…", "Paste LaTeX, [1 2; 3 4], Python lists or rows of numbers",
             self._toggle_import),
            ("Copy", "Copy this matrix in the selected format", self._copy_current),
            ("→ Editor", "Insert this matrix into the editor",
             lambda: self.insert_latex.emit(self._current_latex())),
        ]:
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            fills.addWidget(button)
        fill_host = QWidget()
        fill_host.setObjectName("Transparent")
        fill_host.setLayout(fills)
        main.addWidget(fill_host)

        self.import_box = QWidget()
        self.import_box.setObjectName("Transparent")
        import_layout = QHBoxLayout(self.import_box)
        import_layout.setContentsMargins(0, 0, 0, 0)
        self.import_edit = QPlainTextEdit()
        self.import_edit.setPlaceholderText("[1 2; 3 4]   or   \\begin{bmatrix}1&2\\\\3&4\\end{bmatrix}"
                                            "   or rows of numbers")
        self.import_edit.setFixedHeight(round(64 * s))
        import_layout.addWidget(self.import_edit, 1)
        load = QPushButton("Load")
        load.setObjectName("Primary")
        load.clicked.connect(lambda: self._import_text(self.import_edit.toPlainText()))
        import_layout.addWidget(load)
        self.import_box.setVisible(False)
        main.addWidget(self.import_box)
        layout.addLayout(main, 1)
        return panel

    def _build_tools(self) -> QWidget:
        self.tools = QTabWidget()
        self.tools.addTab(self._build_rowops(), "Row ops")
        self.tools.addTab(self._build_compute(), "Compute")
        self.tools.addTab(self._build_combine(), "Combine")
        self.tools.addTab(self._build_solve(), "Solve Ax=b")
        self.tools.addTab(self._build_expression(), "Expression")
        return self.tools

    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        page.setObjectName("Transparent")
        layout = QVBoxLayout(page)
        s = self.theme.scale
        layout.setContentsMargins(round(4 * s), round(8 * s), round(4 * s), round(4 * s))
        layout.setSpacing(round(7 * s))
        return page, layout

    def _row_spin(self) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(1, 10)
        spin.setPrefix("R")
        return spin

    def _build_rowops(self) -> QWidget:
        page, layout = self._page()
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        self.swap_i, self.swap_j = self._row_spin(), self._row_spin()
        self.swap_j.setValue(2)
        swap_btn = QPushButton("Swap")
        swap_btn.clicked.connect(lambda: self.apply_op(
            L.RowOp.swap(self.swap_i.value() - 1, self.swap_j.value() - 1)))
        grid.addWidget(self.swap_i, 0, 0)
        grid.addWidget(QLabel("↔"), 0, 1, Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.swap_j, 0, 2)
        grid.addWidget(swap_btn, 0, 5)

        self.scale_i = self._row_spin()
        self.scale_k = QLineEdit("1/2")
        self.scale_k.setObjectName("MonoField")
        self.scale_k.setToolTip("Any nonzero number: 2, -1/3, 0.5, sqrt(2)")
        scale_btn = QPushButton("Scale")
        scale_btn.clicked.connect(self._apply_scale)
        grid.addWidget(self.scale_i, 1, 0)
        grid.addWidget(QLabel("←"), 1, 1, Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.scale_k, 1, 2, 1, 2)
        grid.addWidget(QLabel("· Rᵢ"), 1, 4)
        grid.addWidget(scale_btn, 1, 5)

        self.add_i, self.add_j = self._row_spin(), self._row_spin()
        self.add_i.setValue(2)
        self.add_k = QLineEdit("-2")
        self.add_k.setObjectName("MonoField")
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._apply_add)
        grid.addWidget(self.add_i, 2, 0)
        grid.addWidget(QLabel("← Rᵢ +"), 2, 1)
        grid.addWidget(self.add_k, 2, 2)
        grid.addWidget(QLabel("·"), 2, 3, Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.add_j, 2, 4)
        grid.addWidget(add_btn, 2, 5)
        grid.setColumnStretch(2, 1)
        layout.addLayout(grid)

        typed = QHBoxLayout()
        self.op_edit = QLineEdit()
        self.op_edit.setObjectName("MonoField")
        self.op_edit.setPlaceholderText("Type: R1<->R2   R2 -> R2 - 3R1   R3 = 1/2 R3")
        self.op_edit.returnPressed.connect(self._apply_typed)
        typed.addWidget(self.op_edit, 1)
        go = QPushButton("Apply")
        go.setObjectName("Primary")
        go.clicked.connect(self._apply_typed)
        typed.addWidget(go)
        layout.addLayout(typed)

        actions = FlowLayout(spacing=4)
        for text, tip, slot, name in [
            ("↶ Undo", "Undo the last row operation (Ctrl+Z)", self.undo_op, ""),
            ("↷ Redo", "Redo", self.redo_op, ""),
            ("⟲ Restart", "Start again from the selected matrix", self.reset_work, ""),
            ("Next step", "Let the app pick the next Gauss–Jordan step", self.next_step,
             "KeyAccent"),
            ("Auto REF", "Gaussian elimination to row echelon form", lambda: self.auto("ref"),
             ""),
            ("Auto RREF", "Gauss–Jordan elimination to reduced row echelon form",
             lambda: self.auto("rref"), ""),
            ("Save result", "Store the working matrix as a new matrix",
             lambda: self.save_matrix(self.work_matrix()) if self.work_steps else None, ""),
            ("Copy steps", "Copy every step as an aligned LaTeX chain", self.copy_steps, ""),
        ]:
            button = QPushButton(text)
            button.setToolTip(tip)
            if name:
                button.setObjectName(name)
            button.clicked.connect(slot)
            actions.addWidget(button)
        host = QWidget()
        host.setObjectName("Transparent")
        host.setLayout(actions)
        layout.addWidget(host)
        self.work_label = QLabel("Row operations act on a working copy of the selected matrix.")
        self.work_label.setObjectName("Muted")
        self.work_label.setWordWrap(True)
        layout.addWidget(self.work_label)
        layout.addStretch(1)
        return page

    def _build_compute(self) -> QWidget:
        page, layout = self._page()
        groups = [
            ("Basics", [("det", "Determinant (with steps)"), ("cofactor", "Cofactor expansion"),
                        ("inverse", "Inverse (Gauss–Jordan)"), ("transpose", "Transpose"),
                        ("rank", "Rank"), ("trace", "Trace"), ("ref", "REF"), ("rref", "RREF"),
                        ("power", "Power Aⁿ"), ("analyze", "Analyze")]),
            ("Spaces", [("null", "Null space"), ("col", "Column space"), ("row", "Row space"),
                        ("leftnull", "Left null space"), ("gs", "Gram–Schmidt"),
                        ("orthonormal", "Orthonormal basis")]),
            ("Eigen", [("eigen", "Eigenvalues && vectors"), ("charpoly", "Char. polynomial"),
                       ("diag", "Diagonalize"), ("jordan", "Jordan form")]),
            ("Decompose", [("lu", "LU (PLU)"), ("qr", "QR"), ("cholesky", "Cholesky"),
                           ("svd", "SVD"), ("adj", "Adjugate"), ("cof", "Cofactor matrix"),
                           ("norms", "Norms"), ("cond", "Condition no.")]),
        ]
        for title, items in groups:
            layout.addWidget(section_label(title))
            flow = FlowLayout(spacing=4)
            for key, label in items:
                button = QPushButton(label)
                button.clicked.connect(lambda _c=False, k=key: self.compute(k))
                flow.addWidget(button)
                if key == "power":
                    self.power_spin = QSpinBox()
                    self.power_spin.setRange(-20, 50)
                    self.power_spin.setValue(2)
                    self.power_spin.setPrefix("n = ")
                    flow.addWidget(self.power_spin)
            host = QWidget()
            host.setObjectName("Transparent")
            host.setLayout(flow)
            layout.addWidget(host)
        layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        return scroll

    def _build_combine(self) -> QWidget:
        page, layout = self._page()
        row = QHBoxLayout()
        self.x_combo, self.y_combo = QComboBox(), QComboBox()
        row.addWidget(QLabel("X ="))
        row.addWidget(self.x_combo)
        row.addSpacing(10)
        row.addWidget(QLabel("Y ="))
        row.addWidget(self.y_combo)
        row.addSpacing(10)
        row.addWidget(QLabel("k ="))
        self.k_edit = QLineEdit("2")
        self.k_edit.setObjectName("MonoField")
        self.k_edit.setMaximumWidth(round(80 * self.theme.scale))
        row.addWidget(self.k_edit)
        row.addStretch(1)
        layout.addLayout(row)
        flow = FlowLayout(spacing=4)
        for key, label in [("add", "X + Y"), ("sub", "X − Y"), ("mul", "X · Y"), ("rmul", "Y · X"),
                           ("scalar", "k · X"), ("kron", "X ⊗ Y"), ("hadamard", "X ∘ Y"),
                           ("comm", "XY − YX"), ("hjoin", "[X | Y]"), ("vjoin", "[X ; Y]"),
                           ("solvexy", "Solve XZ = Y")]:
            button = QPushButton(label)
            button.clicked.connect(lambda _c=False, k=key: self.combine(k))
            flow.addWidget(button)
        host = QWidget()
        host.setObjectName("Transparent")
        host.setLayout(flow)
        layout.addWidget(host)
        layout.addStretch(1)
        return page

    def _build_solve(self) -> QWidget:
        page, layout = self._page()
        self.solve_aug = QCheckBox("Use the selected augmented matrix [A | b]")
        self.solve_aug.setChecked(True)
        layout.addWidget(self.solve_aug)
        row = QHBoxLayout()
        self.a_combo, self.b_combo = QComboBox(), QComboBox()
        row.addWidget(QLabel("A ="))
        row.addWidget(self.a_combo)
        row.addSpacing(10)
        row.addWidget(QLabel("b ="))
        row.addWidget(self.b_combo)
        row.addStretch(1)
        layout.addLayout(row)
        self.solve_aug.toggled.connect(lambda on: (self.a_combo.setEnabled(not on),
                                                   self.b_combo.setEnabled(not on)))
        self.a_combo.setEnabled(False)
        self.b_combo.setEnabled(False)
        buttons = QHBoxLayout()
        solve = QPushButton("Solve (Gauss–Jordan)")
        solve.setObjectName("Primary")
        solve.clicked.connect(lambda: self.solve("gj"))
        buttons.addWidget(solve)
        cramer = QPushButton("Cramer's rule")
        cramer.clicked.connect(lambda: self.solve("cramer"))
        buttons.addWidget(cramer)
        lsq = QPushButton("Least squares")
        lsq.clicked.connect(lambda: self.solve("lsq"))
        buttons.addWidget(lsq)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        note = QLabel("Shows every elimination step, then classifies the system: unique, "
                      "infinitely many (with a parametric general solution) or none.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _build_expression(self) -> QWidget:
        page, layout = self._page()
        row = QHBoxLayout()
        self.expr_edit = QLineEdit()
        self.expr_edit.setObjectName("MonoField")
        self.expr_edit.setPlaceholderText("A*B - 2C^T   ·   A^-1   ·   inv(A)*B   ·   det(A)   ·   A^3")
        self.expr_edit.returnPressed.connect(self.evaluate_expression)
        row.addWidget(self.expr_edit, 1)
        go = QPushButton("Evaluate")
        go.setObjectName("Primary")
        go.clicked.connect(self.evaluate_expression)
        row.addWidget(go)
        layout.addLayout(row)
        store = QHBoxLayout()
        self.store_check = QCheckBox("Store matrix results as")
        self.store_name = QLineEdit()
        self.store_name.setObjectName("MonoField")
        self.store_name.setPlaceholderText("auto")
        self.store_name.setMaximumWidth(round(90 * self.theme.scale))
        store.addWidget(self.store_check)
        store.addWidget(self.store_name)
        store.addStretch(1)
        layout.addLayout(store)
        help_text = QLabel("Use matrix names, + − *, ^n, ^T or ', inv(), det(), rank(), "
                           "trace(), rref(), adj(), kron(A,B), eye(n), numbers and symbols.")
        help_text.setObjectName("Muted")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        layout.addStretch(1)
        return page

    def _build_output(self) -> QWidget:
        s = self.theme.scale
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(round(10 * s), round(8 * s), round(10 * s), round(10 * s))
        header = QHBoxLayout()
        header.addWidget(QLabel("Copy as"))
        self.format_combo = QComboBox()
        for key, label in FORMATS:
            self.format_combo.addItem(label, key)
        header.addWidget(self.format_combo)
        self.decimal_check = QCheckBox("Decimals")
        self.decimal_check.toggled.connect(self._on_decimal_toggled)
        header.addWidget(self.decimal_check)
        header.addStretch(1)
        self.busy_label = QLabel("")
        self.busy_label.setObjectName("Muted")
        header.addWidget(self.busy_label)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.clear_output)
        header.addWidget(clear)
        layout.addLayout(header)

        self.output_tabs = QTabWidget()
        self.steps_area, self.steps_layout = self._scroll_list()
        self.results_area, self.results_layout = self._scroll_list()
        self.output_tabs.addTab(self.steps_area, "Steps")
        self.output_tabs.addTab(self.results_area, "Results")
        layout.addWidget(self.output_tabs, 1)
        return panel

    def _scroll_list(self) -> tuple[QScrollArea, QVBoxLayout]:
        area = QScrollArea()
        area.setWidgetResizable(True)
        host = QWidget()
        host.setObjectName("Transparent")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 4, 4, 4)
        layout.setSpacing(round(8 * self.theme.scale))
        layout.addStretch(1)
        area.setWidget(host)
        return area, layout

    # ------------------------------------------------------- matrix store
    def _add_matrix(self, name: str, rows: list[list[str]], aug: bool = False) -> None:
        self.matrices[name] = {"rows": rows, "aug": aug}
        self._refresh_names()

    def _refresh_names(self) -> None:
        self._loading = True
        current = self.current
        self.name_list.clear()
        for name in self.matrices:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.name_list.addItem(item)
        for combo in (self.x_combo, self.y_combo, self.a_combo, self.b_combo):
            selected = combo.currentText()
            combo.clear()
            combo.addItems(list(self.matrices))
            if selected in self.matrices:
                combo.setCurrentText(selected)
        names = list(self.matrices)
        if len(names) > 1 and self.y_combo.currentText() == self.x_combo.currentText():
            self.y_combo.setCurrentIndex(1)
        if current in self.matrices:
            items = self.name_list.findItems(current, Qt.MatchFlag.MatchExactly)
            if items:
                self.name_list.setCurrentItem(items[0])
        self._loading = False

    def _next_name(self) -> str:
        for name in "ABCDEFGHJKLMNPQRSTUVWXYZ":
            if name not in self.matrices:
                return name
        index = 1
        while f"M{index}" in self.matrices:
            index += 1
        return f"M{index}"

    def _select(self, name: str) -> None:
        if name not in self.matrices:
            return
        self.current = name
        data = self.matrices[name]
        rows = data["rows"]
        self._loading = True
        self.title_label.setText(name)
        self.rows_spin.setValue(len(rows))
        self.cols_spin.setValue(len(rows[0]) if rows else 1)
        self.aug_check.setChecked(bool(data.get("aug")))
        self.table.setRowCount(len(rows))
        self.table.setColumnCount(len(rows[0]) if rows else 1)
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, c, item)
        self._update_headers()
        items = self.name_list.findItems(name, Qt.MatchFlag.MatchExactly)
        if items:
            self.name_list.setCurrentItem(items[0])
        self._loading = False
        for spin in (self.swap_i, self.swap_j, self.scale_i, self.add_i, self.add_j):
            spin.setMaximum(max(1, len(rows)))
        if self.work_source != name:
            self.work_label.setText(f"Row operations act on a working copy of {name}.")

    def _update_headers(self) -> None:
        cols = self.table.columnCount()
        aug = self.aug_check.isChecked() and cols > 1
        labels = [f"c{c + 1}" for c in range(cols)]
        if aug:
            labels[-1] = "b"
        self.table.setHorizontalHeaderLabels(labels)
        self.table.setVerticalHeaderLabels([f"R{r + 1}" for r in range(self.table.rowCount())])

    def _on_name_selected(self, name: str) -> None:
        if not self._loading and name:
            self._select(name)

    def _start_rename(self, item) -> None:
        if item is not None:
            self._rename_from = item.text()
            self.name_list.editItem(item)

    def _on_renamed(self, item) -> None:
        if self._loading:
            return
        old = getattr(self, "_rename_from", None)
        new = item.text().strip()
        if not old or old == new:
            return
        if not _NAME_RE.match(new) or new in self.matrices:
            self.status.emit("Names must be unique letters/digits, starting with a letter")
            self._refresh_names()
            return
        self.matrices = {(new if k == old else k): v for k, v in self.matrices.items()}
        if self.current == old:
            self.current = new
        self._rename_from = None
        self._refresh_names()
        self._select(new)

    def new_matrix(self) -> None:
        name = self._next_name()
        self._add_matrix(name, [["0"] * 3 for _ in range(3)])
        self._select(name)
        self.table.setFocus()

    def duplicate_matrix(self) -> None:
        if not self.current:
            return
        name = self._next_name()
        data = self.matrices[self.current]
        self._add_matrix(name, [list(r) for r in data["rows"]], data.get("aug", False))
        self._select(name)

    def delete_matrix(self) -> None:
        if not self.current or len(self.matrices) <= 1:
            self.status.emit("Keep at least one matrix")
            return
        del self.matrices[self.current]
        self.current = next(iter(self.matrices))
        self._refresh_names()
        self._select(self.current)

    def save_matrix(self, matrix: sp.Matrix | None, name: str | None = None,
                    aug: bool = False) -> str | None:
        if matrix is None:
            return None
        name = name if name and _NAME_RE.match(name) else self._next_name()
        rows = [[sp.sstr(matrix[r, c]) for c in range(matrix.cols)] for r in range(matrix.rows)]
        self._add_matrix(name, rows, aug)
        self._select(name)
        self.status.emit(f"Saved as {name}")
        return name

    # ---------------------------------------------------------- grid edits
    def _on_cell_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or not self.current:
            return
        text = item.text().strip()
        try:
            L.parse_entry(text or "0")
            item.setForeground(QColor(self.theme.text))
            item.setToolTip("")
        except ValueError as exc:
            item.setForeground(QColor(self.theme.danger))
            item.setToolTip(str(exc))
        self._store_table()

    def _store_table(self) -> None:
        rows = []
        for r in range(self.table.rowCount()):
            row = []
            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                row.append(item.text().strip() if item and item.text().strip() else "0")
            rows.append(row)
        self.matrices[self.current]["rows"] = rows

    def _resize_current(self) -> None:
        if self._loading or not self.current:
            return
        old = self.matrices[self.current]["rows"]
        rows, cols = self.rows_spin.value(), self.cols_spin.value()
        new = [[(old[r][c] if r < len(old) and c < len(old[r]) else "0") for c in range(cols)]
               for r in range(rows)]
        self.matrices[self.current]["rows"] = new
        self._select(self.current)

    def _on_aug_toggled(self, on: bool) -> None:
        if self._loading or not self.current:
            return
        self.matrices[self.current]["aug"] = on
        self._update_headers()

    def _fill(self, kind: str) -> None:
        if not self.current:
            return
        rows, cols = self.rows_spin.value(), self.cols_spin.value()
        if kind == "zero":
            new = [["0"] * cols for _ in range(rows)]
        elif kind == "identity":
            new = [["1" if r == c else "0" for c in range(cols)] for r in range(rows)]
        elif kind == "random":
            new = [[str(random.randint(-9, 9)) for _ in range(cols)] for _ in range(rows)]
        else:
            try:
                matrix = self.matrix(self.current).T
            except ValueError as exc:
                self.status.emit(str(exc))
                return
            new = [[sp.sstr(matrix[r, c]) for c in range(matrix.cols)] for r in range(matrix.rows)]
        self.matrices[self.current]["rows"] = new
        self._select(self.current)

    def _toggle_import(self) -> None:
        self.import_box.setVisible(not self.import_box.isVisible())
        if self.import_box.isVisible():
            self.import_edit.setFocus()

    def _import_text(self, text: str) -> None:
        try:
            matrix, aug_col = L.parse_matrix(text)
        except ValueError as exc:
            self.status.emit(f"Error: {exc}")
            return
        if not self.current:
            return
        rows = [[sp.sstr(matrix[r, c]) for c in range(matrix.cols)] for r in range(matrix.rows)]
        aug = aug_col is not None and aug_col == matrix.cols - 1
        self.matrices[self.current] = {"rows": rows, "aug": aug or (
            self.matrices[self.current].get("aug", False) and matrix.cols > 1)}
        self._select(self.current)
        self.import_box.setVisible(False)
        self.status.emit(f"Loaded a {matrix.rows}×{matrix.cols} matrix into {self.current}")

    def matrix(self, name: str) -> sp.Matrix:
        data = self.matrices[name]
        values = []
        for r, row in enumerate(data["rows"]):
            out = []
            for c, text in enumerate(row):
                try:
                    out.append(L.parse_entry(text))
                except ValueError as exc:
                    raise ValueError(f"{name}: row {r + 1}, column {c + 1}: {exc}") from None
            values.append(out)
        return sp.Matrix(values)

    def aug_col(self, name: str) -> int | None:
        data = self.matrices[name]
        cols = len(data["rows"][0]) if data["rows"] else 0
        return cols - 1 if data.get("aug") and cols > 1 else None

    def _current_latex(self) -> str:
        try:
            return L.matrix_to_latex(self.matrix(self.current), self.latex_env(),
                                     self.aug_col(self.current), self.decimal())
        except ValueError as exc:
            self.status.emit(f"Error: {exc}")
            return ""

    def _copy_current(self) -> None:
        try:
            matrix = self.matrix(self.current)
        except ValueError as exc:
            self.status.emit(f"Error: {exc}")
            return
        self.copy(L.format_matrix(matrix, self.copy_format(), self.aug_col(self.current),
                                  self.decimal()), f"matrix {self.current}")

    # ------------------------------------------------------ output helpers
    def copy_format(self) -> str:
        return self.format_combo.currentData() or "bmatrix"

    def latex_env(self) -> str:
        fmt = self.copy_format()
        return fmt if fmt not in {"plain", "python", "matlab"} else "bmatrix"

    def decimal(self) -> bool:
        return self.decimal_check.isChecked()

    def register_view(self, view: MatrixView) -> None:
        self._views.append(view)
        view.destroyed.connect(lambda _obj=None, v=view: self._views.remove(v)
                               if v in self._views else None)

    def _on_decimal_toggled(self, on: bool) -> None:
        for view in list(self._views):
            try:
                view.set_decimal(on)
            except RuntimeError:
                continue

    def _add_card(self, card: Card, steps: bool = False) -> Card:
        layout = self.steps_layout if steps else self.results_layout
        layout.insertWidget(layout.count() - 1, card)
        self.output_tabs.setCurrentIndex(0 if steps else 1)
        area = self.steps_area if steps else self.results_area
        bar = area.verticalScrollBar()
        bar.rangeChanged.connect(lambda _a, b, sb=bar: sb.setValue(b))
        return card

    def _error_card(self, title: str, message: str) -> None:
        card = Card(self, title)
        card.add_text(message, muted=False)
        card.findChildren(QLabel)[-1].setObjectName("Error")
        self._add_card(card)
        self.status.emit(f"Error: {message}")

    def clear_output(self) -> None:
        for layout in (self.steps_layout, self.results_layout):
            while layout.count() > 1:
                item = layout.takeAt(0)
                if item.widget() is not None:
                    item.widget().deleteLater()
        self._steps_cards: list[Card] = []

    def _show_steps(self, title: str, steps: list[L.Step], aug_col: int | None) -> Card:
        card = Card(self, title, f"{max(0, len(steps) - 1)} operation"
                                 f"{'' if len(steps) == 2 else 's'}")
        for index, step in enumerate(steps):
            label = "" if step.op is None else step.op.text()
            if step.note and (step.op is None or index == 0):
                card.add_text(step.note)
            changed = {step.op.i} if step.op is not None else set()
            pivots = set(L.pivot_positions(step.matrix, aug_col)) if index == len(steps) - 1 \
                else set()
            row = QHBoxLayout()
            if label:
                op_label = QLabel(f"{label}  ⟶")
                op_label.setObjectName("Muted")
                op_label.setMinimumWidth(round(150 * self.theme.scale))
                row.addWidget(op_label)
            view = MatrixView(self.theme, step.matrix, aug_col, self.decimal(), pivots, changed)
            self.register_view(view)
            row.addWidget(view)
            row.addStretch(1)
            card.body.addLayout(row)
        card.latex_parts = [L.steps_to_latex(steps, self.latex_env(), aug_col, self.decimal())]
        card.matrix = steps[-1].matrix if steps else None
        card.aug_col = aug_col
        card._add_button("Save", "Save the final matrix",
                         lambda: self.save_matrix(card.matrix, aug=aug_col is not None))
        return self._add_card(card, steps=True)

    # ----------------------------------------------------------- jobs
    def _run(self, label: str, fn: Callable[[], Any], done: Callable[[Any], None]) -> None:
        if self.synchronous:
            try:
                result, error = fn(), None
            except Exception as exc:  # noqa: BLE001
                result, error = None, exc
            self._deliver(label, done, result, error)
            return
        job = next(_job_ids)
        self._jobs[job] = (label, done)
        self.busy_label.setText(f"Computing {label}…")

        def work() -> None:
            try:
                result, error = fn(), None
            except Exception as exc:  # noqa: BLE001
                result, error = None, exc
            try:
                self._signals.finished.emit(job, result, error)
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True, name=f"matrix-{label}").start()

    def _on_job_finished(self, job: int, result: Any, error: Any) -> None:
        entry = self._jobs.pop(job, None)
        if not self._jobs:
            self.busy_label.setText("")
        if entry is not None:
            self._deliver(entry[0], entry[1], result, error)

    def _deliver(self, label: str, done: Callable[[Any], None], result: Any, error: Any) -> None:
        if error is not None:
            self._error_card(label, _message(error))
            return
        try:
            done(result)
        except Exception as exc:  # noqa: BLE001
            self._error_card(label, _message(exc))

    # ------------------------------------------------------ row operations
    def work_matrix(self) -> sp.Matrix | None:
        return self.work_steps[-1].matrix if self.work_steps else None

    def reset_work(self) -> None:
        if not self.current:
            return
        try:
            matrix = self.matrix(self.current)
        except ValueError as exc:
            self.status.emit(f"Error: {exc}")
            return
        self.work_source = self.current
        self.work_aug = self.aug_col(self.current)
        self.work_steps = [L.Step(None, matrix, f"Start from {self.current}")]
        self.redo_stack = []
        self._clear_steps()
        card = Card(self, f"Row reduction of {self.current}")
        card.add_matrix(matrix, aug_col=self.work_aug, savable=False)
        self._add_card(card, steps=True)
        self._update_work_label()

    def _clear_steps(self) -> None:
        while self.steps_layout.count() > 1:
            item = self.steps_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    def _ensure_work(self) -> bool:
        if not self.work_steps or self.work_source != self.current:
            self.reset_work()
        return bool(self.work_steps)

    def _update_work_label(self) -> None:
        matrix = self.work_matrix()
        if matrix is None:
            return
        ops = len(self.work_steps) - 1
        state = ""
        if L.is_rref(matrix, self.work_aug):
            state = " · reduced row echelon form ✓"
        self.work_label.setText(f"Working copy of {self.work_source}: {ops} operation"
                                f"{'' if ops == 1 else 's'}{state}")

    def apply_op(self, op: L.RowOp) -> bool:
        if not self._ensure_work():
            return False
        matrix = self.work_matrix()
        try:
            op.validate(matrix.rows)
            new = op.apply(matrix)
        except ValueError as exc:
            self.status.emit(f"Error: {exc}")
            return False
        step = L.Step(op, new)
        self.work_steps.append(step)
        self.redo_stack = []
        self._append_step_card(step)
        self._update_work_label()
        return True

    def _append_step_card(self, step: L.Step) -> None:
        card = Card(self, step.op.text() if step.op else "Step")
        card.add_matrix(step.matrix, aug_col=self.work_aug, savable=False,
                        changed_rows={step.op.i} if step.op else set(),
                        highlight=set(L.pivot_positions(step.matrix, self.work_aug))
                        if L.is_rref(step.matrix, self.work_aug) else None)
        card.latex_parts = [rf"\xrightarrow{{{step.op.latex()}}} "
                            + L.matrix_to_latex(step.matrix, self.latex_env(), self.work_aug,
                                                self.decimal())]
        if step.note:
            card.add_text(step.note)
        self._add_card(card, steps=True)

    def _apply_scale(self) -> None:
        try:
            k = L.parse_entry(self.scale_k.text())
        except ValueError as exc:
            self.status.emit(f"Error: {exc}")
            return
        self.apply_op(L.RowOp.scale(self.scale_i.value() - 1, k))

    def _apply_add(self) -> None:
        try:
            k = L.parse_entry(self.add_k.text())
        except ValueError as exc:
            self.status.emit(f"Error: {exc}")
            return
        self.apply_op(L.RowOp.add(self.add_i.value() - 1, self.add_j.value() - 1, k))

    def _apply_typed(self) -> None:
        text = self.op_edit.text().strip()
        if not text:
            return
        self._ensure_work()
        try:
            op = L.parse_row_op(text, self.work_matrix().rows if self.work_steps else None)
        except ValueError as exc:
            self.status.emit(f"Error: {exc}")
            return
        if self.apply_op(op):
            self.op_edit.clear()

    def _apply_typed_or_selected(self) -> None:
        if self.op_edit.text().strip():
            self._apply_typed()

    def undo_op(self) -> None:
        if len(self.work_steps) <= 1:
            self.status.emit("Nothing to undo")
            return
        self.redo_stack.append(self.work_steps.pop())
        if self.steps_layout.count() > 2:
            item = self.steps_layout.takeAt(self.steps_layout.count() - 2)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._update_work_label()

    def redo_op(self) -> None:
        if not self.redo_stack:
            self.status.emit("Nothing to redo")
            return
        step = self.redo_stack.pop()
        self.work_steps.append(step)
        self._append_step_card(step)
        self._update_work_label()

    def next_step(self) -> None:
        if not self._ensure_work():
            return
        step = L.next_rref_step(self.work_matrix(), self.work_aug)
        if step is None or step.op is None:
            self.status.emit("Already in reduced row echelon form ✓")
            self._update_work_label()
            return
        if self.apply_op(step.op) and step.note:
            self.status.emit(step.note)

    def auto(self, kind: str) -> None:
        if not self._ensure_work():
            return
        start = self.work_matrix()
        steps = (L.ref_steps if kind == "ref" else L.rref_steps)(start, self.work_aug)
        added = [s for s in steps[1:] if s.op is not None]
        if not added:
            self.status.emit("No operations needed")
            return
        for step in added:
            self.work_steps.append(step)
            self._append_step_card(step)
        self.redo_stack = []
        self._update_work_label()
        self.status.emit(f"{kind.upper()} in {len(added)} operation"
                         f"{'' if len(added) == 1 else 's'}")

    def copy_steps(self) -> None:
        if len(self.work_steps) < 2:
            self.status.emit("Apply some row operations first")
            return
        self.copy(L.steps_to_latex(self.work_steps, self.latex_env(), self.work_aug,
                                   self.decimal()), "steps")

    # ------------------------------------------------------------ compute
    def compute(self, key: str) -> None:
        if not self.current:
            return
        name = self.current
        try:
            matrix = self.matrix(name)
        except ValueError as exc:
            self.status.emit(f"Error: {exc}")
            return
        aug = self.aug_col(name)
        coeff = matrix[:, :aug] if aug else matrix
        n_power = self.power_spin.value()
        handlers: dict[str, tuple[str, Callable[[], Any], Callable[[Any], None]]] = {
            "det": ("determinant", lambda: L.det_steps(coeff), lambda r: self._show_det(name, r)),
            "cofactor": ("cofactor expansion", lambda: (L.cofactor_expansion_latex(coeff),
                                                         coeff.det()),
                         lambda r: self._latex_card(f"det({name}) by cofactor expansion",
                                                    [r[0]])),
            "inverse": ("inverse", lambda: L.inverse_steps(coeff),
                        lambda r: self._show_inverse(name, r)),
            "transpose": ("transpose", lambda: matrix.T,
                          lambda r: self._matrix_card("Transpose", r, f"{name}ᵀ =")),
            "rank": ("rank", lambda: coeff.rank(),
                     lambda r: self._latex_card("Rank", [rf"\operatorname{{rank}}({name}) = {r}"])),
            "trace": ("trace", lambda: L.simplify_entry(coeff.trace()),
                      lambda r: self._latex_card("Trace",
                                                 [rf"\operatorname{{tr}}({name}) = {sp.latex(r)}"])),
            "ref": ("REF", lambda: L.ref_steps(matrix, aug),
                    lambda r: self._show_steps(f"Row echelon form of {name}", r, aug)),
            "rref": ("RREF", lambda: L.rref_steps(matrix, aug),
                     lambda r: self._show_steps(f"Reduced row echelon form of {name}", r, aug)),
            "power": ("power", lambda: L.power(coeff, n_power),
                      lambda r: self._matrix_card(f"Power n = {n_power}", r,
                                                  f"{name}^{n_power} =")),
            "analyze": ("analysis", lambda: L.analyze(coeff), lambda r: self._show_analysis(name, r)),
            "null": ("null space", lambda: L.nullspace(coeff),
                     lambda r: self._basis_card(f"Null space of {name}", r, "N")),
            "col": ("column space", lambda: L.columnspace(coeff),
                    lambda r: self._basis_card(f"Column space of {name}", r, "C")),
            "row": ("row space", lambda: L.rowspace(coeff),
                    lambda r: self._basis_card(f"Row space of {name}", r, "R")),
            "leftnull": ("left null space", lambda: L.left_nullspace(coeff),
                         lambda r: self._basis_card(f"Left null space of {name}", r, "N(Aᵀ)")),
            "gs": ("Gram–Schmidt", lambda: L.gram_schmidt(coeff, False),
                   lambda r: self._matrix_card("Gram–Schmidt (orthogonal columns)", r, "Q =")),
            "orthonormal": ("orthonormal basis", lambda: L.gram_schmidt(coeff, True),
                            lambda r: self._matrix_card("Orthonormal columns", r, "Q =")),
            "eigen": ("eigenvalues", lambda: L.eigen_info(coeff), lambda r: self._show_eigen(name, r)),
            "charpoly": ("characteristic polynomial", lambda: L.charpoly(coeff),
                         lambda r: self._latex_card(
                             "Characteristic polynomial",
                             [rf"p(\lambda) = \det(\lambda I - {name}) = {sp.latex(r)}",
                              rf"{sp.latex(sp.factor(r))} = 0"])),
            "diag": ("diagonalization", lambda: L.diagonalize(coeff),
                     lambda r: self._multi_matrix_card(f"{name} = P D P⁻¹", [("P =", r[0]),
                                                                              ("D =", r[1])])),
            "jordan": ("Jordan form", lambda: L.jordan(coeff),
                       lambda r: self._multi_matrix_card(f"{name} = P J P⁻¹", [("P =", r[0]),
                                                                                ("J =", r[1])])),
            "lu": ("LU", lambda: L.lu(coeff),
                   lambda r: self._multi_matrix_card(f"P{name} = LU", [("P =", r[0]), ("L =", r[1]),
                                                                         ("U =", r[2])])),
            "qr": ("QR", lambda: L.qr(coeff),
                   lambda r: self._multi_matrix_card(f"{name} = QR", [("Q =", r[0]),
                                                                      ("R =", r[1])])),
            "cholesky": ("Cholesky", lambda: L.cholesky(coeff),
                         lambda r: self._multi_matrix_card(f"{name} = L Lᵀ", [("L =", r)])),
            "svd": ("SVD", lambda: L.svd(coeff),
                    lambda r: self._multi_matrix_card(f"{name} = U Σ Vᵀ (numeric)",
                                                      [("U =", r[0]), ("Σ =", r[1]),
                                                       ("V =", r[2])])),
            "adj": ("adjugate", lambda: L.adjugate(coeff),
                    lambda r: self._matrix_card("Adjugate", r, f"adj({name}) =")),
            "cof": ("cofactor matrix", lambda: L.cofactor_matrix(coeff),
                    lambda r: self._matrix_card("Cofactor matrix", r, "C =")),
            "norms": ("norms", lambda: L.norms(coeff), lambda r: self._show_norms(name, r)),
            "cond": ("condition number", lambda: L.condition_number(coeff),
                     lambda r: self._latex_card("Condition number (2-norm)",
                                                [rf"\kappa({name}) \approx {r:.6g}"])),
        }
        label, fn, done = handlers[key]
        self._run(label, fn, done)

    def _matrix_card(self, title: str, matrix: sp.Matrix, label: str = "") -> Card:
        card = Card(self, title)
        card.add_matrix(matrix, label)
        return self._add_card(card)

    def _multi_matrix_card(self, title: str, parts: list[tuple[str, sp.Matrix]]) -> Card:
        card = Card(self, title)
        for label, matrix in parts:
            card.add_matrix(matrix, label)
        return self._add_card(card)

    def _latex_card(self, title: str, lines: list[str], subtitle: str = "") -> Card:
        card = Card(self, title, subtitle)
        for line in lines:
            card.add_latex(line)
        return self._add_card(card)

    def _show_det(self, name: str, result: L.DetResult) -> None:
        if len(result.steps) > 1:
            self._show_steps(f"Determinant of {name} by row reduction", result.steps, None)
        card = self._latex_card(f"Determinant of {name}",
                                [rf"\det({name}) = {sp.latex(result.value)}"])
        if result.explanation:
            card.add_text(result.explanation)

    def _show_inverse(self, name: str, result: tuple[list[L.Step], sp.Matrix | None]) -> None:
        steps, inverse = result
        n = steps[0].matrix.rows if steps else 0
        self._show_steps(f"[{name} | I] → [I | {name}⁻¹]", steps, n)
        if inverse is None:
            card = self._latex_card(f"{name} is not invertible",
                                    [rf"\det({name}) = 0"])
            card.add_text("The left block can't be reduced to I, so no inverse exists.")
            return
        self._matrix_card(f"Inverse of {name}", inverse, f"{name}⁻¹ =")

    def _basis_card(self, title: str, vectors: list[sp.Matrix], symbol: str) -> None:
        card = Card(self, title, f"dimension {len(vectors)}")
        if not vectors:
            card.add_latex(r"\{\mathbf{0}\}")
        for index, vector in enumerate(vectors):
            card.add_matrix(vector, f"v{index + 1} =", savable=index == 0)
        basis = L.basis_matrix(vectors)
        if basis is not None and len(vectors) > 1:
            card._add_button("Save basis", "Save the basis vectors as columns of a matrix",
                             lambda: self.save_matrix(basis))
        card.latex_parts = [rf"\operatorname{{span}}\left\{{ " + ",\\; ".join(
            L.matrix_to_latex(v, self.latex_env()) for v in vectors) + r" \right\}"
            if vectors else r"\{\mathbf{0}\}"]
        self._add_card(card)

    def _show_eigen(self, name: str, entries: list[L.EigenEntry]) -> None:
        card = Card(self, f"Eigenvalues and eigenvectors of {name}")
        lines = []
        for entry in entries:
            value = sp.latex(entry.value)
            card.add_latex(rf"\lambda = {value} \quad (\text{{alg. mult. }} {entry.algebraic},"
                           rf"\ \text{{geom. mult. }} {entry.geometric})", 17)
            for index, vector in enumerate(entry.vectors):
                card.add_matrix(vector, f"   v{index + 1} =", savable=False)
            vecs = ",\\; ".join(L.matrix_to_latex(v, self.latex_env()) for v in entry.vectors)
            lines.append(rf"\lambda = {value}: \; {vecs}")
        defective = any(e.geometric < e.algebraic for e in entries)
        card.add_text("Not diagonalizable: some eigenvalue has fewer eigenvectors than its "
                      "multiplicity." if defective else "Diagonalizable: a full set of "
                      "eigenvectors exists.")
        card.latex_parts = lines
        self._add_card(card)

    def _show_norms(self, name: str, norms: dict[str, Any]) -> None:
        lines = [rf"\|{name}\|_{{{key}}} = {sp.latex(value)}" for key, value in norms.items()]
        self._latex_card(f"Norms of {name}", lines)

    def _show_analysis(self, name: str, rows: list[tuple[str, str]]) -> None:
        card = Card(self, f"Analysis of {name}")
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        for index, (label, value) in enumerate(rows):
            key = QLabel(label)
            key.setObjectName("Muted")
            val = QLabel(value)
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(key, index, 0)
            grid.addWidget(val, index, 1)
        card.body.addLayout(grid)
        card.latex_parts = [r"\begin{aligned} " + r" \\ ".join(
            rf"&\text{{{label}}}: && \text{{{value}}}" for label, value in rows) + r" \end{aligned}"]
        self._add_card(card)

    # ------------------------------------------------------------ combine
    def combine(self, key: str) -> None:
        xn, yn = self.x_combo.currentText(), self.y_combo.currentText()
        if not xn or not yn:
            return
        try:
            x, y = self.matrix(xn), self.matrix(yn)
            k = L.parse_entry(self.k_edit.text() or "1")
        except ValueError as exc:
            self.status.emit(f"Error: {exc}")
            return
        ops: dict[str, tuple[str, Callable[[], Any]]] = {
            "add": (f"{xn} + {yn}", lambda: x + y),
            "sub": (f"{xn} − {yn}", lambda: x - y),
            "mul": (f"{xn}·{yn}", lambda: x * y),
            "rmul": (f"{yn}·{xn}", lambda: y * x),
            "scalar": (f"{sp.sstr(k)}·{xn}", lambda: k * x),
            "kron": (f"{xn} ⊗ {yn}", lambda: sp.kronecker_product(x, y)),
            "hadamard": (f"{xn} ∘ {yn}", lambda: x.multiply_elementwise(y)),
            "comm": (f"{xn}{yn} − {yn}{xn}", lambda: x * y - y * x),
            "hjoin": (f"[{xn} | {yn}]", lambda: x.row_join(y)),
            "vjoin": (f"[{xn} ; {yn}]", lambda: x.col_join(y)),
            "solvexy": (f"Solve {xn}·Z = {yn}", lambda: L.solve_matrix_equation(x, y)),
        }
        label, fn = ops[key]

        def done(result: Any) -> None:
            if key == "solvexy":
                solution, params = result
                card = Card(self, label, "free parameters: " + ", ".join(map(str, params))
                            if params else "")
                card.add_matrix(solution, "Z =")
                self._add_card(card)
            elif key == "hjoin":
                card = Card(self, label)
                card.add_matrix(result, f"{label} =", aug_col=x.cols)
                self._add_card(card)
            else:
                self._matrix_card(label, L._clean(result), f"{label} =")

        self._run(label, fn, done)

    # -------------------------------------------------------------- solve
    def solve(self, method: str) -> None:
        try:
            if self.solve_aug.isChecked():
                name = self.current
                matrix = self.matrix(name)
                if matrix.cols < 2:
                    raise ValueError("The augmented matrix needs at least two columns")
                a, b = matrix[:, :-1], matrix[:, -1]
                title = name
            else:
                an, bn = self.a_combo.currentText(), self.b_combo.currentText()
                a, b = self.matrix(an), self.matrix(bn)
                if b.cols != 1 and b.rows == 1:
                    b = b.T
                title = f"{an}x = {bn}"
        except ValueError as exc:
            self.status.emit(f"Error: {exc}")
            return
        if b.rows != a.rows:
            self.status.emit(f"Error: b needs {a.rows} entries")
            return
        if method == "cramer":
            self._run("Cramer's rule", lambda: L.cramer(a, b),
                      lambda r: self._show_cramer(title, r))
        elif method == "lsq":
            self._run("least squares", lambda: L.least_squares(a, b),
                      lambda r: self._matrix_card(f"Least-squares solution of {title}", r,
                                                  "x̂ ="))
        else:
            self._run("solve", lambda: L.solve_system(a, b),
                      lambda r: self._show_solution(title, r, a.cols))

    def _show_solution(self, title: str, result: L.SolveResult, n: int) -> None:
        if result.steps:
            self._show_steps(f"Gauss–Jordan on [A | b] ({title})", result.steps, n)
        card = Card(self, result.summary, title)
        if result.kind == "none":
            card.add_text("A row reduced to [0 ⋯ 0 | c] with c ≠ 0, so the equations "
                          "contradict each other.")
            card.latex_parts = [r"\text{No solution}"]
            if result.least_squares is not None:
                card.add_matrix(result.least_squares, "Least squares x̂ =")
                card.latex_parts = [r"\text{No solution}",
                                    r"\hat{\mathbf{x}} = " + L.matrix_to_latex(
                                        result.least_squares, self.latex_env())]
        else:
            card.add_latex(result.latex(self.latex_env()), 17)
            equations = result.equations_latex()
            if equations:
                card.add_latex(equations, 16)
            if result.params:
                card.add_text("Free variables: " + ", ".join(str(p) for p in result.params)
                              + " can be any real numbers.")
            card.latex_parts = [result.latex(self.latex_env())] + ([equations] if equations else [])
            general = result.general()
            if general is not None and result.kind == "unique":
                card.matrix = general
                card._add_button("Save", "Save x as a matrix", lambda: self.save_matrix(general))
        self._add_card(card)

    def _show_cramer(self, title: str, result: tuple[sp.Matrix, str]) -> None:
        solution, latex = result
        card = Card(self, "Cramer's rule", title)
        card.add_latex(latex, 16)
        card.add_matrix(solution, "x =")
        card.latex_parts = [latex]
        self._add_card(card)

    # --------------------------------------------------------- expression
    def evaluate_expression(self) -> None:
        text = self.expr_edit.text().strip()
        if not text:
            return
        try:
            env = {name: self.matrix(name) for name in self.matrices}
        except ValueError as exc:
            self.status.emit(f"Error: {exc}")
            return

        def done(value: Any) -> None:
            if isinstance(value, sp.MatrixBase):
                card = self._matrix_card(text, value, "=")
                if self.store_check.isChecked():
                    self.save_matrix(sp.Matrix(value), self.store_name.text().strip() or None)
                card.latex_parts = [f"{text} = " + card.latex_parts[0].lstrip("= ")]
            else:
                self._latex_card(text, [f"{_expr_latex(text)} = {sp.latex(value)}"])

        self._run(text, lambda: L.evaluate_matrix_expression(text, env), done)

    # -------------------------------------------------------- persistence
    def state(self) -> dict:
        return {
            "matrices": [{"name": name, "rows": data["rows"], "aug": bool(data.get("aug"))}
                         for name, data in self.matrices.items()],
            "current": self.current,
            "format": self.copy_format(),
            "decimal": self.decimal(),
            "tool": self.tools.currentIndex(),
            "power": self.power_spin.value(),
        }

    def restore(self, data: dict) -> None:
        matrices = {}
        for entry in data.get("matrices") or []:
            try:
                name = str(entry["name"])
                rows = [[str(v) for v in row] for row in entry["rows"]]
            except (KeyError, TypeError):
                continue
            if _NAME_RE.match(name) and rows and all(len(r) == len(rows[0]) for r in rows) \
                    and 0 < len(rows) <= 10 and 0 < len(rows[0]) <= 10:
                matrices[name] = {"rows": rows, "aug": bool(entry.get("aug"))}
        if matrices:
            self.matrices = matrices
            self.current = None
            self._refresh_names()
            current = data.get("current")
            self._select(current if current in matrices else next(iter(matrices)))
        index = self.format_combo.findData(data.get("format"))
        if index >= 0:
            self.format_combo.setCurrentIndex(index)
        self.decimal_check.setChecked(bool(data.get("decimal")))
        if isinstance(data.get("tool"), int):
            self.tools.setCurrentIndex(data["tool"])
        if isinstance(data.get("power"), int):
            self.power_spin.setValue(data["power"])

    def focus_primary(self) -> None:
        self.table.setFocus()
        if self.table.currentItem() is None and self.table.rowCount():
            self.table.setCurrentCell(0, 0)


def _message(error: Any) -> str:
    text = str(error).strip() or type(error).__name__
    if "NonSquare" in type(error).__name__:
        text = "This needs a square matrix"
    return text.splitlines()[0][:300]


def _expr_latex(text: str) -> str:
    return text.replace("*", r" \cdot ").replace("^T", "^{T}")

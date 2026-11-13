"""Calculator / CAS tab.

A friendly input line (with live typeset preview), a scrolling history of
result cards, CAS actions that wrap the current input, a clickable keypad and
a variables panel.  Evaluation happens on a daemon thread so a slow sympy call
never freezes the window; stale results are ignored.
"""

from __future__ import annotations

import itertools
import threading
from typing import Any

import sympy as sp
from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from ..theme import Theme
from . import mathcore
from .mathcore import CalcResult, CalcSession
from .widgets import FlowLayout, MathLabel, ToolTab, section_label

HISTORY_LIMIT = 100

HELP_TEXT = """<b>Calculator syntax</b><br><br>
<code>2x^2 + 3x - 5</code> implicit multiplication, <code>^</code> powers<br>
<code>sqrt(2)</code>, <code>|x-1|</code>, <code>5!</code>, <code>15%</code>, <code>30deg</code><br>
<code>a = 3</code> store a variable &nbsp; <code>ans</code> last answer<br>
<code>f(x) = x^2</code> define a function, then <code>f(3)</code><br>
<code>x^2 - 4 = 0</code> solve an equation<br>
<code>x + y = 3, x - y = 1</code> solve a system<br>
<code>x^2 &lt; 4</code> solve an inequality<br>
<code>diff(f, x)</code>, <code>diff(x^3, x, 2)</code> derivatives<br>
<code>integrate(f, x)</code>, <code>integrate(f, x, 0, 1)</code><br>
<code>limit(sin(x)/x, x, 0)</code>, <code>sum(1/n^2, n, 1, oo)</code><br>
<code>taylor(e^x, x, 0, 5)</code>, <code>factor</code>, <code>expand</code>, <code>apart</code><br>
<code>nCr(5,2)</code>, <code>nPr</code>, <code>gcd</code>, <code>lcm</code>, <code>isprime</code>, <code>factorint</code><br>
<code>mean(1,2,3)</code>, <code>median</code>, <code>std</code>, <code>var</code><br>
<code>log(x)</code> is base 10, <code>ln(x)</code> natural, <code>log(x, b)</code> base b<br>
Paste LaTeX directly: <code>\\frac{1}{2} + \\sqrt{2}</code><br><br>
<b>Keys</b>: Enter evaluate · ↑/↓ input history · Ctrl+Shift+C copy last result
"""


class _Signals(QObject):
    evaluated = pyqtSignal(int, object)
    previewed = pyqtSignal(int, str, str)


class _InputLine(QLineEdit):
    history_prev = pyqtSignal()
    history_next = pyqtSignal()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Up:
            self.history_prev.emit()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Down:
            self.history_next.emit()
            event.accept()
            return
        super().keyPressEvent(event)


def entry_from_result(result: CalcResult) -> dict[str, Any]:
    plot_expr = ""
    value = result.value
    if (result.ok and result.kind in {"value", "assign"} and isinstance(value, sp.Expr)
            and len(value.free_symbols) == 1 and not value.has(sp.I)):
        plot_expr = mathcore.to_plain(value)
    elif result.ok and result.kind == "function" and isinstance(value, sp.Lambda) \
            and len(value.variables) == 1:
        expr = value.expr.subs(value.variables[0], sp.Symbol("x"))
        plot_expr = mathcore.to_plain(expr)
    return {
        "input": result.input_text,
        "ok": result.ok,
        "kind": result.kind,
        "input_latex": result.input_latex,
        "result_latex": result.result_latex,
        "result_plain": result.result_plain,
        "approx_latex": result.approx_latex,
        "approx_plain": result.approx_plain,
        "full_latex": result.full_latex,
        "error": result.error,
        "note": result.note,
        "plot": plot_expr,
    }


def _decimal_full_latex(entry: dict[str, Any]) -> str:
    if not entry.get("approx_latex"):
        return entry.get("full_latex", "")
    if entry.get("kind") in {"equation"}:
        return entry["approx_latex"]
    if entry.get("kind") == "assign":
        name = entry["result_latex"].split("=", 1)[0].strip()
        return f"{name} \\approx {entry['approx_latex']}"
    left = entry.get("input_latex", "")
    return f"{left} \\approx {entry['approx_latex']}" if left else entry["approx_latex"]


class ResultCard(QFrame):
    reuse = pyqtSignal(str)
    action = pyqtSignal(str, dict)   # action name, entry

    def __init__(self, theme: Theme, entry: dict[str, Any], prefer_decimal: bool,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.entry = entry
        self.setObjectName("Card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        s = theme.scale
        layout = QVBoxLayout(self)
        layout.setContentsMargins(round(12 * s), round(8 * s), round(10 * s), round(8 * s))
        layout.setSpacing(round(4 * s))

        source = QLabel(entry.get("input", ""))
        source.setObjectName("Source")
        source.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        source.setToolTip("Click the card to reuse this input")
        layout.addWidget(source)

        if entry.get("ok"):
            self.math = MathLabel(theme, 19)
            self.math.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.math.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            layout.addWidget(self.math)
        else:
            self.math = None

        bottom = QHBoxLayout()
        bottom.setSpacing(round(4 * s))
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bottom.addWidget(self.detail, 1)

        if entry.get("ok"):
            for label, name, tip in [
                ("Copy", "copy_full", "Copy LaTeX of input = result"),
                ("Result", "copy_result", "Copy only the result as LaTeX"),
                ("Plain", "copy_plain", "Copy the plain-text / decimal result"),
                ("→ Editor", "editor", "Insert into the LaTeX editor"),
            ]:
                bottom.addWidget(self._small_button(label, name, tip))
            if entry.get("plot"):
                bottom.addWidget(self._small_button("Plot", "plot", "Send to the graph tab"))
        layout.addLayout(bottom)
        self.set_prefer_decimal(prefer_decimal)

    def _small_button(self, label: str, name: str, tip: str) -> QPushButton:
        button = QPushButton(label)
        button.setToolTip(tip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        s = self.theme.scale
        button.setStyleSheet(
            f"padding: {round(1 * s)}px {round(7 * s)}px; font-size: {round(11 * s)}px;"
        )
        button.clicked.connect(lambda: self.action.emit(name, self.entry))
        return button

    def set_prefer_decimal(self, prefer: bool) -> None:
        entry = self.entry
        if not entry.get("ok"):
            self.detail.setObjectName("Error")
            self.detail.setText("⚠ " + (entry.get("error") or "Error"))
            self.detail.style().unpolish(self.detail)
            self.detail.style().polish(self.detail)
            return
        main = _decimal_full_latex(entry) if prefer and entry.get("approx_latex") \
            else entry.get("full_latex", "")
        if self.math is not None:
            self.math.set_latex(main or entry.get("result_latex", ""))
        lines = []
        if entry.get("approx_plain"):
            if prefer:
                lines.append("exact: " + entry.get("result_plain", ""))
            else:
                lines.append("≈ " + entry["approx_plain"])
        if entry.get("note"):
            lines.append(entry["note"])
        self.detail.setObjectName("Muted")
        self.detail.setText("   ·   ".join(lines))
        self.detail.style().unpolish(self.detail)
        self.detail.style().polish(self.detail)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.reuse.emit(self.entry.get("input", ""))
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = QMenu(self)
        items = [("Reuse input", "reuse")]
        if self.entry.get("ok"):
            items += [
                ("Copy LaTeX (input = result)", "copy_full"),
                ("Copy result LaTeX", "copy_result"),
                ("Copy input LaTeX", "copy_input"),
                ("Copy plain result", "copy_plain_exact"),
            ]
            if self.entry.get("approx_plain"):
                items.append(("Copy decimal", "copy_decimal"))
            items.append(("Insert into editor", "editor"))
            if self.entry.get("plot"):
                items.append(("Plot in graph", "plot"))
        items.append(("Delete card", "delete"))
        for label, name in items:
            act = QAction(label, menu)
            act.triggered.connect(lambda _=False, n=name: self._menu_action(n))
            menu.addAction(act)
        menu.exec(event.globalPos())

    def _menu_action(self, name: str) -> None:
        if name == "reuse":
            self.reuse.emit(self.entry.get("input", ""))
        else:
            self.action.emit(name, self.entry)


class CalculatorTab(ToolTab):
    key = "calculator"
    title = "Calculator"
    hints = [("Enter", "Evaluate"), ("↑ ↓", "History"), ("Ctrl+Shift+C", "Copy result")]

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent)
        self.session = CalcSession()
        self.synchronous = False          # tests evaluate inline
        self.prefer_decimal = False
        self.entries: list[dict[str, Any]] = []
        self.cards: list[ResultCard] = []
        self.input_history: list[str] = []
        self._history_index: int | None = None
        self._draft = ""
        self._job_ids = itertools.count(1)
        self._eval_job = 0
        self._preview_job = 0
        self._signals = _Signals(self)
        self._signals.evaluated.connect(self._on_evaluated)
        self._signals.previewed.connect(self._on_previewed)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(220)
        self._preview_timer.timeout.connect(self._start_preview)
        self._build_ui()
        self._refresh_variables()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        s = self.theme.scale
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter)

        # ---- left: input + history
        left = QWidget()
        left.setObjectName("Transparent")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, round(6 * s), 0)
        left_layout.setSpacing(round(8 * s))

        input_row = QHBoxLayout()
        input_row.setSpacing(round(6 * s))
        self.input = _InputLine()
        self.input.setObjectName("MonoField")
        self.input.setPlaceholderText("Type an expression, equation or LaTeX…  e.g. x^2 - 5x + 6 = 0")
        self.input.returnPressed.connect(self.evaluate_current)
        self.input.textChanged.connect(self._on_text_changed)
        self.input.history_prev.connect(lambda: self._recall(-1))
        self.input.history_next.connect(lambda: self._recall(1))
        input_row.addWidget(self.input, 1)
        self.busy_label = QLabel("")
        self.busy_label.setObjectName("Muted")
        input_row.addWidget(self.busy_label)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancel)
        input_row.addWidget(self.cancel_button)
        self.eval_button = QPushButton("=")
        self.eval_button.setObjectName("Primary")
        self.eval_button.setToolTip("Evaluate (Enter)")
        self.eval_button.setMinimumWidth(round(44 * s))
        self.eval_button.clicked.connect(self.evaluate_current)
        input_row.addWidget(self.eval_button)
        self.help_button = QToolButton()
        self.help_button.setObjectName("Tool")
        self.help_button.setText("?")
        self.help_button.setToolTip(HELP_TEXT)
        self.help_button.clicked.connect(self._show_help)
        input_row.addWidget(self.help_button)
        left_layout.addLayout(input_row)

        preview_frame = QFrame()
        preview_frame.setObjectName("Panel")
        preview_layout = QHBoxLayout(preview_frame)
        preview_layout.setContentsMargins(round(12 * s), round(6 * s), round(12 * s), round(6 * s))
        self.preview = MathLabel(self.theme, 21)
        self.preview.setMinimumHeight(round(44 * s))
        self.preview.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        preview_layout.addWidget(self.preview, 1)
        self.preview_error = QLabel("Live preview of your input appears here")
        self.preview_error.setObjectName("Faint")
        self.preview_error.setWordWrap(True)
        preview_layout.addWidget(self.preview_error)
        left_layout.addWidget(preview_frame)

        history_header = QHBoxLayout()
        history_header.addWidget(section_label("History"))
        history_header.addStretch(1)
        for label, slot, tip in [
            ("Copy all", self.copy_all, "Copy the whole history as an aligned LaTeX block"),
            ("Clear", self.clear_history, "Clear the history"),
        ]:
            button = QPushButton(label)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            history_header.addWidget(button)
        left_layout.addLayout(history_header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history_widget = QWidget()
        self.history_widget.setObjectName("Transparent")
        self.history_layout = QVBoxLayout(self.history_widget)
        self.history_layout.setContentsMargins(0, 0, round(4 * s), 0)
        self.history_layout.setSpacing(round(6 * s))
        self.history_layout.addStretch(1)
        self.empty_label = QLabel("Results appear here.  Click a card to reuse its input;\n"
                                  "right-click for more copy options.")
        self.empty_label.setObjectName("Faint")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.history_layout.addWidget(self.empty_label)
        self.scroll.setWidget(self.history_widget)
        self.scroll.verticalScrollBar().rangeChanged.connect(self._scroll_to_bottom)
        left_layout.addWidget(self.scroll, 1)
        splitter.addWidget(left)

        # ---- right: tools
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right = QWidget()
        right.setObjectName("Transparent")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(round(6 * s), 0, round(6 * s), 0)
        right_layout.setSpacing(round(8 * s))
        right_layout.addWidget(section_label("Keypad"))
        right_layout.addWidget(self._build_keypad())
        right_layout.addWidget(section_label("Actions on input"))
        right_layout.addWidget(self._build_actions())
        right_layout.addWidget(section_label("Settings"))
        right_layout.addLayout(self._build_settings())
        right_layout.addWidget(section_label("Variables & functions"))
        self.variables_list = QListWidget()
        self.variables_list.setMinimumHeight(round(80 * s))
        self.variables_list.setMaximumHeight(round(150 * s))
        self.variables_list.setToolTip("Double-click to insert · Delete key removes")
        self.variables_list.itemDoubleClicked.connect(self._insert_variable)
        self.variables_list.installEventFilter(self)
        right_layout.addWidget(self.variables_list)
        var_buttons = QHBoxLayout()
        remove = QPushButton("Delete selected")
        remove.clicked.connect(self._delete_variable)
        var_buttons.addWidget(remove)
        clear_vars = QPushButton("Clear all")
        clear_vars.clicked.connect(self.clear_variables)
        var_buttons.addWidget(clear_vars)
        right_layout.addLayout(var_buttons)
        right_layout.addStretch(1)
        right_scroll.setWidget(right)
        right_scroll.setMinimumWidth(round(360 * s))
        splitter.addWidget(right_scroll)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([round(720 * s), round(380 * s)])

        shortcut = QShortcut(QKeySequence("Ctrl+Shift+C"), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self.copy_last)

    def _build_keypad(self) -> QWidget:
        s = self.theme.scale
        widget = QWidget()
        widget.setObjectName("Transparent")
        grid = QGridLayout(widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(round(4 * s))
        # (label, insert, kind, tooltip)
        rows = [
            [("sin", "sin()", "fn"), ("cos", "cos()", "fn"), ("tan", "tan()", "fn"),
             ("ln", "ln()", "fn"), ("log", "log()", "fn"), ("eˣ", "exp()", "fn")],
            [("sin⁻¹", "asin()", "fn"), ("cos⁻¹", "acos()", "fn"), ("tan⁻¹", "atan()", "fn"),
             ("√", "sqrt()", "fn"), ("|x|", "abs()", "fn"), ("n!", "!", "op")],
            [("x²", "^2", "op"), ("xⁿ", "^", "op"), ("1/x", "1/()", "fn"),
             ("(", "(", "op"), (")", ")", "op"), ("÷", "/", "op")],
            [("7", "7", "num"), ("8", "8", "num"), ("9", "9", "num"),
             ("π", "pi", "sym"), ("e", "e", "sym"), ("×", "*", "op")],
            [("4", "4", "num"), ("5", "5", "num"), ("6", "6", "num"),
             ("i", "i", "sym"), ("∞", "oo", "sym"), ("−", "-", "op")],
            [("1", "1", "num"), ("2", "2", "num"), ("3", "3", "num"),
             ("x", "x", "sym"), ("y", "y", "sym"), ("+", "+", "op")],
            [("0", "0", "num"), (".", ".", "num"), (",", ", ", "op"),
             ("t", "t", "sym"), ("θ", "theta", "sym"), ("=", " = ", "op")],
        ]
        for r, row in enumerate(rows):
            for c, (label, insert, kind) in enumerate(row):
                button = QPushButton(label)
                button.setObjectName("KeyOp" if kind in {"op", "fn"} else "Key")
                button.setToolTip(insert.strip() or label)
                button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                button.clicked.connect(lambda _=False, t=insert: self.insert_text(t))
                grid.addWidget(button, r, c)
        bottom = len(rows)
        for c, (label, slot, name, tip) in enumerate([
            ("ans", lambda: self.insert_text("ans"), "Key", "Last answer"),
            ("←", self._backspace, "Key", "Backspace"),
            ("C", self._clear_input, "Key", "Clear input"),
        ]):
            button = QPushButton(label)
            button.setObjectName(name)
            button.setToolTip(tip)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(slot)
            grid.addWidget(button, bottom, c)
        enter = QPushButton("Enter  =")
        enter.setObjectName("KeyAccent")
        enter.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        enter.clicked.connect(self.evaluate_current)
        grid.addWidget(enter, bottom, 3, 1, 3)
        return widget

    def _build_actions(self) -> QWidget:
        s = self.theme.scale
        box = QWidget()
        box.setObjectName("Transparent")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(round(6 * s))

        flow_host = QWidget()
        flow_host.setObjectName("Transparent")
        flow = FlowLayout(flow_host, spacing=round(4 * s))
        actions = [
            ("Simplify", "simplify", "Simplify the expression"),
            ("Expand", "expand", "Expand products and powers"),
            ("Factor", "factor", "Factor polynomials"),
            ("d/dx", "diff", "Differentiate with respect to the variable"),
            ("∫ dx", "integrate", "Indefinite integral"),
            ("∫ₐᵇ", "definite", "Definite integral from a to b"),
            ("Solve", "solve", "Solve expression = 0 (or the equation) for the variable"),
            ("Limit", "limit", "Limit as the variable approaches the point"),
            ("Taylor", "taylor", "Taylor polynomial around the point"),
            ("Partial fr.", "apart", "Partial fraction decomposition"),
            ("Together", "together", "Combine into a single fraction"),
            ("→ Decimal", "decimal", "Numeric value"),
            ("Roots", "roots", "Numeric roots of a polynomial (incl. complex)"),
        ]
        self.action_buttons: dict[str, QPushButton] = {}
        for label, name, tip in actions:
            button = QPushButton(label)
            button.setToolTip(tip + "\nApplies to the input, or to ans when the input is empty")
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda _=False, n=name: self.apply_action(n))
            flow.addWidget(button)
            self.action_buttons[name] = button
        layout.addWidget(flow_host)

        options = QGridLayout()
        options.setHorizontalSpacing(round(6 * s))
        options.setVerticalSpacing(round(4 * s))
        options.addWidget(QLabel("Variable"), 0, 0)
        self.var_combo = QComboBox()
        self.var_combo.setEditable(True)
        self.var_combo.addItems(["auto", "x", "y", "t", "z", "n", "theta"])
        self.var_combo.setToolTip("Variable for d/dx, ∫, solve, limit, Taylor…  'auto' detects it")
        options.addWidget(self.var_combo, 0, 1)
        options.addWidget(QLabel("Point"), 0, 2)
        self.point_field = QLineEdit("0")
        self.point_field.setObjectName("MonoField")
        self.point_field.setToolTip("Point for Limit / Taylor (e.g. 0, pi, oo)")
        options.addWidget(self.point_field, 0, 3)
        options.addWidget(QLabel("a"), 1, 0)
        self.lower_field = QLineEdit("0")
        self.lower_field.setObjectName("MonoField")
        self.lower_field.setToolTip("Lower bound for ∫ₐᵇ")
        options.addWidget(self.lower_field, 1, 1)
        options.addWidget(QLabel("b"), 1, 2)
        self.upper_field = QLineEdit("1")
        self.upper_field.setObjectName("MonoField")
        self.upper_field.setToolTip("Upper bound for ∫ₐᵇ")
        options.addWidget(self.upper_field, 1, 3)
        options.addWidget(QLabel("Order"), 2, 0)
        self.order_spin = QSpinBox()
        self.order_spin.setRange(1, 30)
        self.order_spin.setValue(6)
        self.order_spin.setToolTip("Taylor order (number of terms up to x^(n-1))")
        options.addWidget(self.order_spin, 2, 1)
        layout.addLayout(options)
        return box

    def _build_settings(self) -> QHBoxLayout:
        s = self.theme.scale
        row = QHBoxLayout()
        row.setSpacing(round(6 * s))
        self.angle_button = QPushButton("RAD")
        self.angle_button.setCheckable(True)
        self.angle_button.setToolTip("Angle mode for trig functions (RAD / DEG)")
        self.angle_button.toggled.connect(self._on_angle_toggled)
        row.addWidget(self.angle_button)
        row.addWidget(QLabel("Digits"))
        self.digits_spin = QSpinBox()
        self.digits_spin.setRange(4, 30)
        self.digits_spin.setValue(self.session.digits)
        self.digits_spin.setToolTip("Significant digits for decimal results")
        self.digits_spin.valueChanged.connect(self._on_digits_changed)
        row.addWidget(self.digits_spin)
        self.decimal_check = QCheckBox("Prefer decimals")
        self.decimal_check.setToolTip("Show decimal approximations as the main result")
        self.decimal_check.toggled.connect(self._on_decimal_toggled)
        row.addWidget(self.decimal_check)
        row.addStretch(1)
        return row

    # ------------------------------------------------------------- input
    def insert_text(self, text: str) -> None:
        field = self.input
        selected = field.selectedText()
        if text.endswith("()") and len(text) > 2:
            name = text[:-1]
            if selected:
                field.insert(f"{name}{selected})")
            else:
                field.insert(text)
                field.setCursorPosition(field.cursorPosition() - 1)
        else:
            field.insert(text)
        field.setFocus()

    def _backspace(self) -> None:
        self.input.backspace()
        self.input.setFocus()

    def _clear_input(self) -> None:
        self.input.clear()
        self.input.setFocus()

    def set_input(self, text: str) -> None:
        self.input.setText(text)
        self.input.setCursorPosition(len(text))
        self.input.setFocus()

    def focus_primary(self) -> None:
        self.input.setFocus()
        self.input.selectAll()

    def _recall(self, delta: int) -> None:
        if not self.input_history:
            return
        if self._history_index is None:
            if delta > 0:
                return
            self._draft = self.input.text()
            self._history_index = len(self.input_history)
        index = self._history_index + delta
        if index >= len(self.input_history):
            self._history_index = None
            self.input.setText(self._draft)
            return
        index = max(0, index)
        self._history_index = index
        self.input.setText(self.input_history[index])

    def _on_text_changed(self, _text: str) -> None:
        self._preview_timer.start()

    # ----------------------------------------------------------- preview
    def _start_preview(self) -> None:
        text = self.input.text()
        job = next(self._job_ids)
        self._preview_job = job
        if not text.strip():
            self.preview.set_latex("")
            self.preview_error.setText("Live preview of your input appears here")
            return
        session = self.session
        if self.synchronous:
            latex, error = session.preview(text)
            self._on_previewed(job, latex, error)
            return

        def work() -> None:
            latex, error = session.preview(text)
            try:
                self._signals.previewed.emit(job, latex, error)
            except RuntimeError:
                pass

        threading.Thread(target=work, name="calc-preview", daemon=True).start()

    def _on_previewed(self, job: int, latex: str, error: str) -> None:
        if job != self._preview_job:
            return
        if latex:
            self.preview.set_latex(latex)
            self.preview_error.setText("")
        else:
            self.preview_error.setText(error)

    # -------------------------------------------------------- evaluation
    def evaluate_current(self) -> None:
        text = self.input.text().strip()
        if not text:
            self.status.emit("Type an expression first")
            return
        self.evaluate_text(text)

    def evaluate_text(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if not self.input_history or self.input_history[-1] != text:
            self.input_history.append(text)
            del self.input_history[:-200]
        self._history_index = None
        job = next(self._job_ids)
        self._eval_job = job
        session = self.session
        if self.synchronous:
            self._on_evaluated(job, session.evaluate(text))
            return
        self._set_busy(True)

        def work() -> None:
            result = session.evaluate(text)
            try:
                self._signals.evaluated.emit(job, result)
            except RuntimeError:
                pass

        threading.Thread(target=work, name="calc-eval", daemon=True).start()

    def cancel(self) -> None:
        # The worker thread cannot be killed; detach from it instead.  Give it
        # a private copy of the session so its late writes are discarded.
        self._eval_job = next(self._job_ids)
        self.session = CalcSession(
            variables=dict(self.session.variables),
            functions=dict(self.session.functions),
            angle_mode=self.session.angle_mode,
            digits=self.session.digits,
        )
        self._set_busy(False)
        self.status.emit("Cancelled (the computation continues in the background)")

    def _set_busy(self, busy: bool) -> None:
        self.busy_label.setText("Computing…" if busy else "")
        self.cancel_button.setVisible(busy)

    def _on_evaluated(self, job: int, result: CalcResult) -> None:
        if job != self._eval_job:
            return
        self._set_busy(False)
        entry = entry_from_result(result)
        self._add_entry(entry)
        self._refresh_variables()
        if result.ok:
            self.input.clear()
            self.status.emit(result.note or "Evaluated")
        else:
            self.status.emit("⚠ " + result.error)
            self.input.selectAll()

    def apply_action(self, name: str) -> None:
        text = self.input.text().strip()
        if not text:
            if "ans" not in self.session.variables:
                self.status.emit("Type an expression first")
                return
            text = "ans"
        try:
            command = self.build_action(name, text)
        except mathcore.ParseError as exc:
            self.status.emit("⚠ " + str(exc))
            return
        self.input.setText(command)
        self.evaluate_text(command)

    def _variable_for(self, text: str) -> str:
        choice = self.var_combo.currentText().strip()
        if choice and choice != "auto":
            return choice
        try:
            expr = mathcore.parse(text, self.session.env())
            if isinstance(expr, sp.Equality):
                expr = expr.lhs - expr.rhs
            return str(mathcore.default_variable(expr))
        except Exception:  # noqa: BLE001
            return "x"

    def build_action(self, name: str, text: str) -> str:
        """Return the calculator command that applies *name* to *text*."""
        source = mathcore.latex_to_python(text) if mathcore.looks_like_latex(text) else text
        equation = mathcore._split_equation(source)
        if equation is not None:
            equation = (equation[0].strip(), equation[1].strip())
        if equation is not None and name not in {"solve", "decimal", "simplify"}:
            # Act on lhs - rhs for equations.
            source = f"({equation[0]}) - ({equation[1]})"
            equation = None
        target = f"({source})"
        var = self._variable_for(source if equation is None
                                 else f"({equation[0]}) - ({equation[1]})")
        point = self.point_field.text().strip() or "0"
        if name == "simplify":
            if equation is not None:
                return f"simplify({equation[0]}) = simplify({equation[1]})"
            return f"simplify{target}"
        if name in {"expand", "factor", "together"}:
            return f"{name}{target}"
        if name == "diff":
            return f"diff({source}, {var})"
        if name == "integrate":
            return f"integrate({source}, {var})"
        if name == "definite":
            lower = self.lower_field.text().strip() or "0"
            upper = self.upper_field.text().strip() or "1"
            return f"integrate({source}, {var}, {lower}, {upper})"
        if name == "solve":
            if equation is not None:
                return f"solve(Eq({equation[0]}, {equation[1]}), {var})"
            return f"solve({source}, {var})"
        if name == "limit":
            return f"limit({source}, {var}, {point})"
        if name == "taylor":
            return f"taylor({source}, {var}, {point}, {self.order_spin.value()})"
        if name == "apart":
            return f"apart({source}, {var})"
        if name == "decimal":
            if equation is not None:
                return f"N({equation[0]}, {self.session.digits}) = N({equation[1]}, {self.session.digits})"
            return f"N({source}, {self.session.digits})"
        if name == "roots":
            return f"nroots({source}, {var})"
        raise mathcore.ParseError(f"Unknown action {name}")

    # ------------------------------------------------------------ history
    def _add_entry(self, entry: dict[str, Any], scroll: bool = True) -> None:
        self.entries.append(entry)
        card = ResultCard(self.theme, entry, self.prefer_decimal)
        card.reuse.connect(self.set_input)
        card.action.connect(self._card_action)
        self.history_layout.addWidget(card)
        self.cards.append(card)
        self.empty_label.setVisible(False)
        while len(self.entries) > HISTORY_LIMIT:
            self.entries.pop(0)
            old = self.cards.pop(0)
            self.history_layout.removeWidget(old)
            old.deleteLater()
        if scroll:
            QTimer.singleShot(0, self._scroll_to_bottom)

    def _scroll_to_bottom(self, *_args) -> None:
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _card_action(self, name: str, entry: dict[str, Any]) -> None:
        if name == "copy_full":
            text = _decimal_full_latex(entry) if self.prefer_decimal else entry.get("full_latex", "")
            self.copy(text or entry.get("result_latex", ""), "LaTeX")
        elif name == "copy_result":
            text = entry.get("approx_latex") if self.prefer_decimal and entry.get("approx_latex") \
                else entry.get("result_latex", "")
            self.copy(text, "result LaTeX")
        elif name == "copy_input":
            self.copy(entry.get("input_latex", ""), "input LaTeX")
        elif name == "copy_plain":
            self.copy(entry.get("approx_plain") or entry.get("result_plain", ""), "result")
        elif name == "copy_plain_exact":
            self.copy(entry.get("result_plain", ""), "result")
        elif name == "copy_decimal":
            self.copy(entry.get("approx_plain", ""), "decimal")
        elif name == "editor":
            self.insert_latex.emit(entry.get("full_latex") or entry.get("result_latex", ""))
            self.status.emit("Sent to the editor")
        elif name == "plot":
            if entry.get("plot"):
                self.send_to_graph.emit(entry["plot"])
                self.status.emit("Sent to the graph")
        elif name == "delete":
            if entry in self.entries:
                index = self.entries.index(entry)
                self.entries.pop(index)
                card = self.cards.pop(index)
                self.history_layout.removeWidget(card)
                card.deleteLater()
                self.empty_label.setVisible(not self.entries)

    def copy_last(self) -> None:
        for entry in reversed(self.entries):
            if entry.get("ok"):
                self._card_action("copy_result", entry)
                return
        self.status.emit("No result to copy yet")

    def copy_all(self) -> None:
        rows = []
        for entry in self.entries:
            if not entry.get("ok"):
                continue
            latex = _decimal_full_latex(entry) if self.prefer_decimal else entry.get("full_latex", "")
            if latex:
                rows.append(latex)
        if not rows:
            self.status.emit("History is empty")
            return
        if len(rows) == 1:
            self.copy(rows[0], "LaTeX")
            return
        self.copy("\\begin{gathered}\n" + " \\\\\n".join(rows) + "\n\\end{gathered}",
                  f"{len(rows)} results as LaTeX")

    def clear_history(self) -> None:
        for card in self.cards:
            self.history_layout.removeWidget(card)
            card.deleteLater()
        self.cards.clear()
        self.entries.clear()
        self.empty_label.setVisible(True)
        self.status.emit("History cleared")

    # ------------------------------------------------------------ settings
    def _on_angle_toggled(self, checked: bool) -> None:
        self.session.angle_mode = "deg" if checked else "rad"
        self.angle_button.setText("DEG" if checked else "RAD")
        self.status.emit(f"Angle mode: {'degrees' if checked else 'radians'}")

    def _on_digits_changed(self, value: int) -> None:
        self.session.digits = value

    def _on_decimal_toggled(self, checked: bool) -> None:
        self.prefer_decimal = checked
        for card in self.cards:
            card.set_prefer_decimal(checked)

    def _show_help(self) -> None:
        menu = QMenu(self)
        label = QLabel(HELP_TEXT)
        label.setTextFormat(Qt.TextFormat.RichText)
        s = self.theme.scale
        label.setContentsMargins(round(12 * s), round(10 * s), round(12 * s), round(10 * s))
        action = QWidgetAction(menu)
        action.setDefaultWidget(label)
        menu.addAction(action)
        menu.exec(self.help_button.mapToGlobal(self.help_button.rect().bottomLeft()))

    # ----------------------------------------------------------- variables
    def _refresh_variables(self) -> None:
        self.variables_list.clear()
        for name, (params, body) in sorted(self.session.functions.items()):
            item = QListWidgetItem(f"{name}({', '.join(params)}) = {body}")
            item.setData(Qt.ItemDataRole.UserRole, ("function", name))
            self.variables_list.addItem(item)
        for name, value in sorted(self.session.variables.items()):
            text = mathcore.to_plain(value)
            if len(text) > 60:
                text = text[:57] + "…"
            item = QListWidgetItem(f"{name} = {text}")
            item.setData(Qt.ItemDataRole.UserRole, ("variable", name))
            self.variables_list.addItem(item)
        if self.variables_list.count() == 0:
            item = QListWidgetItem("Nothing stored yet. Try  a = 5  or  f(x) = x^2")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.variables_list.addItem(item)

    def _insert_variable(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, name = data
        self.insert_text(f"{name}()" if kind == "function" else name)

    def _delete_variable(self) -> None:
        item = self.variables_list.currentItem()
        data = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not data:
            return
        kind, name = data
        if kind == "function":
            self.session.functions.pop(name, None)
        else:
            self.session.variables.pop(name, None)
        self._refresh_variables()
        self.status.emit(f"Deleted {name}")

    def clear_variables(self) -> None:
        self.session.variables.clear()
        self.session.functions.clear()
        self._refresh_variables()
        self.status.emit("Variables cleared")

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.variables_list and event.type() == event.Type.KeyPress \
                and event.key() == Qt.Key.Key_Delete:
            self._delete_variable()
            return True
        return super().eventFilter(obj, event)

    # --------------------------------------------------------- persistence
    def state(self) -> dict:
        return {
            "session": self.session.to_state(),
            "history": self.entries[-HISTORY_LIMIT:],
            "input_history": self.input_history[-200:],
            "prefer_decimal": self.prefer_decimal,
            "input": self.input.text(),
            "variable": self.var_combo.currentText(),
            "point": self.point_field.text(),
            "lower": self.lower_field.text(),
            "upper": self.upper_field.text(),
            "order": self.order_spin.value(),
        }

    def restore(self, data: dict) -> None:
        if not isinstance(data, dict):
            return
        self.session = CalcSession.from_state(data.get("session") or {})
        self.angle_button.blockSignals(True)
        self.angle_button.setChecked(self.session.angle_mode == "deg")
        self.angle_button.setText("DEG" if self.session.angle_mode == "deg" else "RAD")
        self.angle_button.blockSignals(False)
        self.digits_spin.blockSignals(True)
        self.digits_spin.setValue(self.session.digits)
        self.digits_spin.blockSignals(False)
        self.prefer_decimal = bool(data.get("prefer_decimal", False))
        self.decimal_check.blockSignals(True)
        self.decimal_check.setChecked(self.prefer_decimal)
        self.decimal_check.blockSignals(False)
        history = data.get("input_history")
        if isinstance(history, list):
            self.input_history = [h for h in history if isinstance(h, str)][-200:]
        self.clear_history()
        for entry in data.get("history") or []:
            if isinstance(entry, dict) and isinstance(entry.get("input"), str):
                clean = {k: entry.get(k, "") for k in (
                    "input", "kind", "input_latex", "result_latex", "result_plain",
                    "approx_latex", "approx_plain", "full_latex", "error", "note", "plot")}
                clean["ok"] = bool(entry.get("ok"))
                self._add_entry(clean, scroll=False)
        QTimer.singleShot(0, self._scroll_to_bottom)
        for key, widget in (("point", self.point_field), ("lower", self.lower_field),
                            ("upper", self.upper_field)):
            if isinstance(data.get(key), str):
                widget.setText(data[key])
        if isinstance(data.get("variable"), str):
            self.var_combo.setCurrentText(data["variable"])
        if isinstance(data.get("order"), int):
            self.order_spin.setValue(data["order"])
        if isinstance(data.get("input"), str):
            self.input.setText(data["input"])
        self._refresh_variables()

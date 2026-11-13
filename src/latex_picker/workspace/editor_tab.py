"""Visual LaTeX equation editor: click palette buttons, see the result, copy."""

from __future__ import annotations

import json
import re
from pathlib import Path

from PyQt6.QtCore import QSize, QStringListModel, Qt, QTimer
from PyQt6.QtGui import (
    QColor,
    QFont,
    QKeySequence,
    QShortcut,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
)
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QCompleter,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..config import _atomic_write_json, default_custom_snippets_path
from ..latex_preview import detailed_preview
from . import render
from .palettes import (
    CATEGORIES,
    MATRIX_ENVS,
    MATRIX_FILLS,
    PH,
    PaletteButton,
    build_matrix,
    known_commands,
    search,
    template_for_command,
)
from .widgets import FlowLayout, MathLabel, ToolTab, section_label

FORMATS: list[tuple[str, str, str]] = [
    ("raw", "Raw LaTeX", "@"),
    ("inline", "$ … $", "$@$"),
    ("display", "$$ … $$", "$$@$$"),
    ("bracket", "\\[ … \\]", "\\[@\\]"),
    ("paren", "\\( … \\)", "\\(@\\)"),
    ("equation", "equation", "\\begin{equation}\n@\n\\end{equation}"),
    ("equation*", "equation*", "\\begin{equation*}\n@\n\\end{equation*}"),
    ("align*", "align*", "\\begin{align*}\n@\n\\end{align*}"),
]
_LIBRARY_PLACEHOLDER = re.compile(r"<[A-Za-z][A-Za-z0-9 _-]*>")
HISTORY_LIMIT = 50


# ---------------------------------------------------------------- pure helpers
def wrap_output(latex: str, fmt: str) -> str:
    template = next((t for key, _label, t in FORMATS if key == fmt), "@")
    return template.replace("@", latex.strip())


def strip_placeholders(latex: str) -> tuple[str, int]:
    return latex.replace(PH, ""), latex.count(PH)


def fill_template(template: str, selection: str) -> str:
    """Put *selection* into the first placeholder of *template* (if any)."""
    if selection and PH in template:
        return template.replace(PH, selection, 1)
    if selection and not template:
        return selection
    return template


def library_to_editor(latex: str) -> str:
    return _LIBRARY_PLACEHOLDER.sub(PH, latex)


def u16len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def brace_problem(latex: str) -> str:
    depth = 0
    i = 0
    while i < len(latex):
        ch = latex[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "%":
            while i < len(latex) and latex[i] != "\n":
                i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return "Unbalanced braces: an extra “}”"
        i += 1
    if depth > 0:
        return f"Unbalanced braces: {depth} “{{” not closed"
    begins = re.findall(r"\\begin\{([^}]*)\}", latex)
    ends = re.findall(r"\\end\{([^}]*)\}", latex)
    if sorted(begins) != sorted(ends):
        return "Every \\begin{…} needs a matching \\end{…}"
    lefts = len(re.findall(r"\\left(?![a-zA-Z])", latex))
    rights = len(re.findall(r"\\right(?![a-zA-Z])", latex))
    if lefts != rights:
        return "Every \\left needs a matching \\right"
    return ""


def save_snippet(title: str, latex: str, path: Path | None = None) -> str:
    """Append *latex* to the user's custom snippet file; returns the new id."""
    title = title.strip()
    latex = latex.strip()
    if not title:
        raise ValueError("Give the snippet a title")
    if not latex:
        raise ValueError("The editor is empty")
    target = Path(path) if path else default_custom_snippets_path()
    data: dict = {}
    if target.exists():
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"{target} is not valid JSON; not overwriting it") from exc
        if isinstance(raw, list):
            data = {"snippets": raw}
        elif isinstance(raw, dict):
            data = raw
        else:
            raise ValueError(f"{target} has an unexpected format; not overwriting it")
    categories = data.setdefault("categories", [])
    if not isinstance(categories, list):
        raise ValueError(f"{target}: 'categories' must be a list")
    if not any(isinstance(c, dict) and c.get("id") == "custom" for c in categories):
        categories.append({"id": "custom", "name": "My Snippets", "symbol": "★",
                           "description": "Equations saved from the editor"})
    snippets = data.setdefault("snippets", [])
    if not isinstance(snippets, list):
        raise ValueError(f"{target}: 'snippets' must be a list")
    slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-") or "snippet"
    existing = {s.get("id") for s in snippets if isinstance(s, dict)}
    ident = f"custom-{slug}"
    counter = 2
    while ident in existing:
        ident = f"custom-{slug}-{counter}"
        counter += 1
    numbered = [0]

    def number(_match) -> str:
        numbered[0] += 1
        return f"<arg{numbered[0]}>"

    stored = re.sub(re.escape(PH), number, latex)
    snippets.append({
        "id": ident,
        "category": "custom",
        "title": title,
        "latex": stored,
        "description": "Saved from the LaTeX editor",
        "keywords": ["custom", "saved"],
    })
    _atomic_write_json(target, data)
    return ident


# ---------------------------------------------------------------- highlighting
class LatexHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument, theme) -> None:
        super().__init__(document)

        def fmt(color: str, bold: bool = False, background: str | None = None) -> QTextCharFormat:
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(QFont.Weight.Bold)
            if background:
                f.setBackground(QColor(background))
            return f

        self.rules = [
            (re.compile(r"\\(begin|end)\b"), fmt(theme.danger, True)),
            (re.compile(r"\\[A-Za-z]+\*?|\\[^A-Za-z]"), fmt(theme.accent)),
            (re.compile(r"[{}]"), fmt(theme.muted, True)),
            (re.compile(r"[\[\]()]"), fmt(theme.muted)),
            (re.compile(r"\d+(\.\d+)?"), fmt(theme.math)),
            (re.compile(r"&|\\\\"), fmt(theme.danger, True)),
            (re.compile(r"[\^_]"), fmt(theme.faint, True)),
            (re.compile(PH), fmt(theme.accent, True, theme.accent_soft)),
            (re.compile(r"(?<!\\)%.*$"), fmt(theme.faint)),
        ]

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        # QSyntaxHighlighter indexes in UTF-16 units; convert Python offsets.
        def to16(index: int) -> int:
            return u16len(text[:index])

        for pattern, style in self.rules:
            for match in pattern.finditer(text):
                start, end = match.span()
                self.setFormat(to16(start), to16(end) - to16(start), style)


# ---------------------------------------------------------------- source edit
class SourceEdit(QPlainTextEdit):
    PAIRS = {"{": "}", "(": ")", "[": "]"}

    def __init__(self, tab: EditorTab) -> None:
        super().__init__()
        self.tab = tab
        self.auto_close = True
        self.setObjectName("CodeEditor")
        self.setTabChangesFocus(False)
        self.setPlaceholderText(
            "Click buttons on the left or type LaTeX here…   Tab jumps between ⬚ placeholders"
        )
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.completer = QCompleter(self)
        self.completer.setModel(QStringListModel(known_commands(), self.completer))
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseSensitive)
        self.completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.completer.setWidget(self)
        self.completer.activated.connect(self._complete)
        self.cursorPositionChanged.connect(self._match_braces)

    # -- completion
    def _prefix(self) -> str:
        cursor = self.textCursor()
        block = cursor.block().text()
        before = block[: self._py_index(block, cursor.positionInBlock())]
        match = re.search(r"\\[A-Za-z]+$", before)
        return match.group() if match else ""

    @staticmethod
    def _py_index(text: str, utf16_pos: int) -> int:
        count = 0
        for index, ch in enumerate(text):
            if count >= utf16_pos:
                return index
            count += 2 if ord(ch) > 0xFFFF else 1
        return len(text)

    def _update_completer(self) -> None:
        prefix = self._prefix()
        popup = self.completer.popup()
        if len(prefix) < 3:
            popup.hide()
            return
        self.completer.setCompletionPrefix(prefix)
        if self.completer.completionCount() == 0 or (
            self.completer.completionCount() == 1
            and self.completer.currentCompletion() == prefix
        ):
            popup.hide()
            return
        popup.setCurrentIndex(self.completer.completionModel().index(0, 0))
        rect = self.cursorRect()
        rect.setWidth(popup.sizeHintForColumn(0) + popup.verticalScrollBar().sizeHint().width() + 16)
        self.completer.complete(rect)

    def _complete(self, command: str) -> None:
        prefix = self._prefix()
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Left,
                            QTextCursor.MoveMode.KeepAnchor, u16len(prefix))
        self.setTextCursor(cursor)
        self.tab.insert_template(template_for_command(command))

    # -- keys
    def keyPressEvent(self, event) -> None:  # noqa: N802
        popup = self.completer.popup()
        key = event.key()
        if popup.isVisible() and key in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab,
                                         Qt.Key.Key_Escape, Qt.Key.Key_Backtab}:
            if key == Qt.Key.Key_Tab:
                index = popup.currentIndex()
                if index.isValid():
                    popup.hide()
                    self._complete(index.data())
                    event.accept()
                    return
            event.ignore()
            return
        modifiers = event.modifiers()
        if key == Qt.Key.Key_Backtab or (key == Qt.Key.Key_Tab and modifiers & Qt.KeyboardModifier.ShiftModifier):
            self.tab.jump_placeholder(-1)
            event.accept()
            return
        if key == Qt.Key.Key_Tab and not modifiers & Qt.KeyboardModifier.ControlModifier:
            if not self.tab.jump_placeholder(1):
                self.insertPlainText("  ")
            event.accept()
            return
        if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter} and modifiers & Qt.KeyboardModifier.ControlModifier:
            event.ignore()  # handled by the tab's shortcut
            return
        text = event.text()
        if self.auto_close and text in self.PAIRS and not modifiers & Qt.KeyboardModifier.ControlModifier:
            cursor = self.textCursor()
            selected = cursor.selectedText().replace("\u2029", "\n")
            prev = self._char_before(cursor)
            if prev == "\\" and text == "{":
                pass  # literal \{ : don't auto-close
            else:
                closer = self.PAIRS[text]
                cursor.insertText(text + selected + closer)
                cursor.movePosition(QTextCursor.MoveOperation.Left, n=1)
                if selected:
                    cursor.movePosition(QTextCursor.MoveOperation.Left,
                                        QTextCursor.MoveMode.KeepAnchor, u16len(selected))
                self.setTextCursor(cursor)
                event.accept()
                return
        if self.auto_close and text in {"}", ")", "]"}:
            cursor = self.textCursor()
            if not cursor.hasSelection() and self._char_after(cursor) == text:
                cursor.movePosition(QTextCursor.MoveOperation.Right)
                self.setTextCursor(cursor)
                event.accept()
                return
        if self.auto_close and key == Qt.Key.Key_Backspace:
            cursor = self.textCursor()
            if not cursor.hasSelection():
                before, after = self._char_before(cursor), self._char_after(cursor)
                if before in self.PAIRS and self.PAIRS[before] == after:
                    cursor.deleteChar()
        super().keyPressEvent(event)
        if text and (text.isalpha() or text == "\\") or key == Qt.Key.Key_Backspace:
            self._update_completer()
        else:
            popup.hide()

    def _char_before(self, cursor: QTextCursor) -> str:
        pos = cursor.position()
        return self.document().characterAt(pos - 1) if pos > 0 else ""

    def _char_after(self, cursor: QTextCursor) -> str:
        return self.document().characterAt(cursor.position())

    # -- brace matching
    def _match_braces(self) -> None:
        doc = self.document()
        pos = self.textCursor().position()
        selections = []
        pairs = {"{": "}", "(": ")", "[": "]"}
        closers = {v: k for k, v in pairs.items()}
        if doc.characterCount() > 20000:
            self.setExtraSelections([])
            return
        for probe in (pos - 1, pos):
            if probe < 0:
                continue
            ch = doc.characterAt(probe)
            if ch not in pairs and ch not in closers:
                continue
            if probe > 0 and doc.characterAt(probe - 1) == "\\":
                continue
            match = self._find_match(probe, ch, pairs, closers)
            if match is None:
                continue
            for p in (probe, match):
                selection = QTextEdit.ExtraSelection()
                selection.format.setBackground(QColor(self.tab.theme.accent_soft))
                selection.format.setForeground(QColor(self.tab.theme.accent))
                selection.format.setProperty(QTextFormat.Property.FullWidthSelection, False)
                cursor = QTextCursor(doc)
                cursor.setPosition(p)
                cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor)
                selection.cursor = cursor
                selections.append(selection)
            break
        self.setExtraSelections(selections)

    def _find_match(self, pos: int, ch: str, pairs: dict, closers: dict) -> int | None:
        doc = self.document()
        if ch in pairs:
            target, step, end = pairs[ch], 1, doc.characterCount()
        else:
            target, step, end = closers[ch], -1, -1
        depth = 0
        p = pos
        while p != end:
            c = doc.characterAt(p)
            escaped = p > 0 and doc.characterAt(p - 1) == "\\"
            if not escaped:
                if c == ch:
                    depth += 1
                elif c == target:
                    depth -= 1
                    if depth == 0:
                        return p
            p += step
        return None


# ---------------------------------------------------------------- palette area
class _FlowPage(QWidget):
    """Content widget for a scroll area whose height follows its FlowLayout."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Transparent")
        self.flow = FlowLayout(self, spacing=4)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        height = self.flow.heightForWidth(self.width())
        if self.minimumHeight() != height:
            self.setMinimumHeight(height)

    def clear(self) -> None:
        while self.flow.count():
            item = self.flow.takeAt(0)
            if item is not None and item.widget() is not None:
                widget = item.widget()
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()


class EditorTab(ToolTab):
    key = "editor"
    title = "Editor"
    hints = [("Ctrl+Enter", "Copy"), ("Tab", "Next ⬚"), ("Ctrl+Shift+I", "Copy image")]

    def __init__(self, theme, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent)
        self.history: list[str] = []
        self.favorites: list[str] = []
        self.format_key = "raw"
        self.image_background = "transparent"   # transparent | white
        self.image_color = "black"              # black | theme
        self.font_px = 15
        self.current_category = CATEGORIES[0].id
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(150)
        self._preview_timer.timeout.connect(self._update_preview)
        self._build()
        self._show_category(self.current_category)
        self._apply_font()
        self._update_preview()

    # ------------------------------------------------------------ building
    def _px(self, value: float) -> int:
        return round(value * self.theme.scale)

    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        root.addWidget(self.splitter)

        self.splitter.addWidget(self._build_palette())
        self.splitter.addWidget(self._build_editor())
        self.splitter.addWidget(self._build_side())
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([self._px(420), self._px(640), self._px(230)])
        self.side_panel.setVisible(False)

        QShortcut(QKeySequence("Ctrl+Return"), self, self.copy_latex,
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence("Ctrl+Enter"), self, self.copy_latex,
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence("Ctrl+Shift+I"), self, self.copy_png,
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence("Ctrl+Shift+U"), self, self.copy_unicode,
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence("Ctrl+D"), self, self.toggle_favorite,
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence("Ctrl+H"), self, self.toggle_side,
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence("Ctrl+="), self, lambda: self.zoom(1),
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence("Ctrl+-"), self, lambda: self.zoom(-1),
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence("Ctrl+F"), self, lambda: self.palette_search.setFocus(),
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)

    def _build_palette(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setMinimumWidth(self._px(300))
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(self._px(10), self._px(10), self._px(6), self._px(10))
        layout.setSpacing(self._px(8))

        self.palette_search = QLineEdit()
        self.palette_search.setObjectName("Field")
        self.palette_search.setPlaceholderText("Search symbols…  (e.g. integral, theta, ≤)")
        self.palette_search.setClearButtonEnabled(True)
        self.palette_search.textChanged.connect(self._on_search)
        self.palette_search.returnPressed.connect(self._insert_first_result)
        layout.addWidget(self.palette_search)

        chips = QWidget()
        chips.setObjectName("Transparent")
        chip_flow = FlowLayout(chips, spacing=self._px(4))
        self.chip_group = QButtonGroup(self)
        self.chip_group.setExclusive(True)
        self.chips: dict[str, QPushButton] = {}
        for category in CATEGORIES:
            chip = QPushButton(f"{category.icon}  {category.name}".replace("&", "&&"))
            chip.setObjectName("CategoryChip")
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setToolTip(f"{len(category.buttons)} buttons")
            chip.clicked.connect(lambda _c=False, cid=category.id: self._show_category(cid))
            self.chip_group.addButton(chip)
            chip_flow.addWidget(chip)
            self.chips[category.id] = chip
        self.chip_page = chips
        layout.addWidget(chips)

        self.palette_title = section_label("")
        layout.addWidget(self.palette_title)

        self.palette_scroll = QScrollArea()
        self.palette_scroll.setWidgetResizable(True)
        self.palette_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.palette_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.palette_page = _FlowPage()
        self.palette_scroll.setWidget(self.palette_page)
        self.palette_scroll.viewport().setStyleSheet("background: transparent;")
        layout.addWidget(self.palette_scroll, 1)

        self.builder = self._build_matrix_builder()
        layout.addWidget(self.builder)
        self.builder.setVisible(False)
        return panel

    def _build_matrix_builder(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(self._px(10), self._px(8), self._px(10), self._px(8))
        layout.setSpacing(self._px(6))
        layout.addWidget(section_label("Matrix builder"))
        row = QHBoxLayout()
        self.mb_rows = QSpinBox()
        self.mb_rows.setRange(1, 12)
        self.mb_rows.setValue(3)
        self.mb_cols = QSpinBox()
        self.mb_cols.setRange(1, 12)
        self.mb_cols.setValue(3)
        row.addWidget(QLabel("Rows"))
        row.addWidget(self.mb_rows)
        row.addWidget(QLabel("Cols"))
        row.addWidget(self.mb_cols)
        row.addStretch(1)
        layout.addLayout(row)
        row2 = QHBoxLayout()
        self.mb_env = QComboBox()
        self.mb_env.addItems(MATRIX_ENVS)
        self.mb_env.setCurrentText("bmatrix")
        self.mb_fill = QComboBox()
        self.mb_fill.addItems(MATRIX_FILLS)
        row2.addWidget(self.mb_env, 1)
        row2.addWidget(self.mb_fill, 1)
        layout.addLayout(row2)
        row3 = QHBoxLayout()
        insert = QPushButton("Insert matrix")
        insert.setObjectName("Primary")
        insert.clicked.connect(self._insert_built_matrix)
        cancel = QPushButton("Close")
        cancel.clicked.connect(lambda: self.builder.setVisible(False))
        row3.addStretch(1)
        row3.addWidget(cancel)
        row3.addWidget(insert)
        layout.addLayout(row3)
        return frame

    def _build_editor(self) -> QWidget:
        column = QWidget()
        column.setObjectName("Transparent")
        layout = QVBoxLayout(column)
        layout.setContentsMargins(self._px(10), 0, self._px(4), 0)
        layout.setSpacing(self._px(8))

        preview_panel = QFrame()
        preview_panel.setObjectName("Panel")
        pv = QVBoxLayout(preview_panel)
        pv.setContentsMargins(self._px(12), self._px(8), self._px(12), self._px(8))
        pv.setSpacing(self._px(4))
        head = QHBoxLayout()
        head.addWidget(section_label("Preview"))
        head.addStretch(1)
        self.char_count = QLabel("")
        self.char_count.setObjectName("Faint")
        head.addWidget(self.char_count)
        pv.addLayout(head)
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.preview = MathLabel(self.theme, size=34)
        self.preview.setMinimumHeight(self._px(90))
        self.preview.setWordWrap(True)
        self.preview_scroll.setWidget(self.preview)
        self.preview_scroll.viewport().setStyleSheet("background: transparent;")
        pv.addWidget(self.preview_scroll, 1)
        self.preview_hint = QLabel("")
        self.preview_hint.setObjectName("Faint")
        self.preview_hint.setWordWrap(True)
        pv.addWidget(self.preview_hint)
        layout.addWidget(preview_panel, 3)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(self._px(4))
        toolbar.addWidget(section_label("LaTeX source"))
        toolbar.addStretch(1)

        def tool(text: str, tip: str, slot) -> QToolButton:
            button = QToolButton()
            button.setObjectName("Tool")
            button.setText(text)
            button.setToolTip(tip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(slot)
            toolbar.addWidget(button)
            return button

        tool("↶", "Undo (Ctrl+Z)", lambda: self.source.undo())
        tool("↷", "Redo (Ctrl+Shift+Z)", lambda: self.source.redo())
        tool("A−", "Smaller (Ctrl+−)", lambda: self.zoom(-1))
        tool("A+", "Larger (Ctrl+=)", lambda: self.zoom(1))
        tool("⬚→", "Next placeholder (Tab)", lambda: (self.jump_placeholder(1), self.source.setFocus()))
        self.star_button = tool("☆", "Add to favorites (Ctrl+D)", self.toggle_favorite)
        tool("= Evaluate", "Evaluate in the Calculator", self.evaluate)
        tool("📈 Plot", "Plot in the Graph tab", self.plot)
        tool("⌫ Clear", "Clear the editor", self.clear)
        self.side_button = tool("History ▸", "Show history and favorites (Ctrl+H)", self.toggle_side)
        self.options_button = QToolButton()
        self.options_button.setObjectName("Tool")
        self.options_button.setText("⋯")
        self.options_button.setToolTip("Options")
        self.options_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.options_button.setMenu(self._build_options_menu())
        toolbar.addWidget(self.options_button)
        layout.addLayout(toolbar)

        self.source = SourceEdit(self)
        self.source.setMinimumHeight(self._px(80))
        self.highlighter = LatexHighlighter(self.source.document(), self.theme)
        self.source.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.source, 2)

        self.snippet_bar = QFrame()
        self.snippet_bar.setObjectName("Card")
        sb = QHBoxLayout(self.snippet_bar)
        sb.setContentsMargins(self._px(8), self._px(6), self._px(8), self._px(6))
        sb.addWidget(QLabel("Snippet title"))
        self.snippet_title = QLineEdit()
        self.snippet_title.setObjectName("Field")
        self.snippet_title.setPlaceholderText("e.g. Quadratic formula")
        self.snippet_title.returnPressed.connect(self._confirm_snippet)
        sb.addWidget(self.snippet_title, 1)
        save = QPushButton("Save to Picker")
        save.setObjectName("Primary")
        save.clicked.connect(self._confirm_snippet)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(lambda: self.snippet_bar.setVisible(False))
        sb.addWidget(cancel)
        sb.addWidget(save)
        self.snippet_bar.setVisible(False)
        layout.addWidget(self.snippet_bar)

        actions = QHBoxLayout()
        actions.setSpacing(self._px(6))
        self.format_combo = QComboBox()
        for key, label, _template in FORMATS:
            self.format_combo.addItem(label, key)
        self.format_combo.setToolTip("How the copied LaTeX is wrapped")
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        actions.addWidget(self.format_combo)
        for text, tip, slot in [
            ("🖼 Image", "Copy as PNG image (Ctrl+Shift+I)", self.copy_png),
            ("Unicode", "Copy a plain-text Unicode version (Ctrl+Shift+U)", self.copy_unicode),
            ("Save PNG…", "Save the rendered equation as a PNG file", self.save_png),
            ("★ Snippet", "Save into the Picker's “My Snippets” category", self.ask_snippet),
        ]:
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            actions.addWidget(button)
        actions.addStretch(1)
        self.copy_button = QPushButton("Copy LaTeX  ⏎")
        self.copy_button.setObjectName("Primary")
        self.copy_button.setToolTip("Copy the LaTeX source (Ctrl+Enter)")
        self.copy_button.setMinimumWidth(self._px(140))
        self.copy_button.clicked.connect(self.copy_latex)
        actions.addWidget(self.copy_button)
        layout.addLayout(actions)
        return column

    def _build_options_menu(self) -> QMenu:
        menu = QMenu(self)
        self.auto_close_action = menu.addAction("Auto-close brackets")
        self.auto_close_action.setCheckable(True)
        self.auto_close_action.setChecked(True)
        self.auto_close_action.toggled.connect(lambda on: setattr(self.source, "auto_close", on))
        menu.addSeparator()
        menu.addSection("Image background")
        self.bg_actions = {}
        for key, label in [("transparent", "Transparent"), ("white", "White")]:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.triggered.connect(lambda _c=False, k=key: self._set_image_background(k))
            self.bg_actions[key] = action
        menu.addSection("Image text colour")
        self.color_actions = {}
        for key, label in [("black", "Black (for documents)"), ("theme", "Theme colour")]:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.triggered.connect(lambda _c=False, k=key: self._set_image_color(k))
            self.color_actions[key] = action
        self._sync_option_checks()
        return menu

    def _build_side(self) -> QWidget:
        self.side_panel = QFrame()
        self.side_panel.setObjectName("Panel")
        self.side_panel.setMinimumWidth(self._px(190))
        layout = QVBoxLayout(self.side_panel)
        layout.setContentsMargins(self._px(8), self._px(8), self._px(8), self._px(8))
        self.side_tabs = QTabWidget()
        self.history_list = QListWidget()
        self.favorites_list = QListWidget()
        for widget in (self.history_list, self.favorites_list):
            widget.itemClicked.connect(self._restore_item)
            widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            widget.customContextMenuRequested.connect(
                lambda pos, w=widget: self._list_menu(w, pos))
            widget.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.side_tabs.addTab(self.history_list, "History")
        self.side_tabs.addTab(self.favorites_list, "★ Favorites")
        layout.addWidget(self.side_tabs)
        hint = QLabel("Click to restore · right-click for more")
        hint.setObjectName("Faint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return self.side_panel

    # ------------------------------------------------------------ palette
    def _make_button(self, button: PaletteButton) -> QPushButton:
        widget = QPushButton(button.label)
        widget.setObjectName({"op": "KeyOp", "builder": "KeyAccent"}.get(button.kind, "Key"))
        if button.kind in {"wide", "builder"}:
            widget.setStyleSheet(f"font-size: {self._px(12)}px; padding: 3px 8px;")
        widget.setCursor(Qt.CursorShape.PointingHandCursor)
        widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tip = button.name
        if button.latex:
            tip = f"<b>{_html(button.name)}</b><br><code>{_html(button.latex)}</code>"
        widget.setToolTip(tip)
        widget.clicked.connect(lambda _c=False, b=button: self.press(b))
        return widget

    def _populate(self, buttons: list[PaletteButton] | tuple[PaletteButton, ...]) -> None:
        self.palette_page.clear()
        for button in buttons:
            self.palette_page.flow.addWidget(self._make_button(button))
        self.palette_page.flow.invalidate()
        QTimer.singleShot(0, self._refit_palette)
        self.palette_scroll.verticalScrollBar().setValue(0)

    def _refit_palette(self) -> None:
        page = self.palette_page
        height = page.flow.heightForWidth(max(1, self.palette_scroll.viewport().width()))
        page.setMinimumHeight(height)

    def _show_category(self, category_id: str) -> None:
        category = next((c for c in CATEGORIES if c.id == category_id), CATEGORIES[0])
        self.current_category = category.id
        self.chips[category.id].setChecked(True)
        if self.palette_search.text():
            self.palette_search.blockSignals(True)
            self.palette_search.clear()
            self.palette_search.blockSignals(False)
        self.palette_title.setText(f"{category.name.upper()} · {len(category.buttons)}")
        self._populate(category.buttons)

    def _on_search(self, text: str) -> None:
        if not text.strip():
            self._show_category(self.current_category)
            return
        results = search(text)
        self._search_results = results
        self.palette_title.setText(f"{len(results)} RESULT{'S' if len(results) != 1 else ''}")
        self._populate(results)

    def _insert_first_result(self) -> None:
        results = getattr(self, "_search_results", [])
        if self.palette_search.text().strip() and results:
            self.press(results[0])
            self.source.setFocus()

    def press(self, button: PaletteButton) -> None:
        if button.kind == "builder":
            self.builder.setVisible(not self.builder.isVisible())
            return
        self.insert_template(button.latex)
        self.source.setFocus()

    def _insert_built_matrix(self) -> None:
        latex = build_matrix(self.mb_rows.value(), self.mb_cols.value(),
                             self.mb_env.currentText(), self.mb_fill.currentText())
        self.insert_template(latex)
        self.source.setFocus()
        self.status.emit(f"Inserted {self.mb_rows.value()}×{self.mb_cols.value()} "
                         f"{self.mb_env.currentText()}")

    # ------------------------------------------------------------ editing
    def insert_template(self, template: str) -> None:
        cursor = self.source.textCursor()
        selection = cursor.selectedText().replace("\u2029", "\n")
        if selection == PH:
            selection = ""
        text = fill_template(template, selection)
        start = cursor.selectionStart()
        cursor.beginEditBlock()
        cursor.insertText(text)
        cursor.endEditBlock()
        end = start + u16len(text)
        found = self.source.document().find(PH, start)
        if not found.isNull() and found.selectionEnd() <= end:
            self.source.setTextCursor(found)
        else:
            cursor.setPosition(end)
            self.source.setTextCursor(cursor)
        self.source.ensureCursorVisible()

    def insert_latex_text(self, latex: str) -> None:
        """Insert a library snippet, converting <placeholders> to ⬚."""
        self.insert_template(library_to_editor(latex))
        self.source.setFocus()

    def jump_placeholder(self, direction: int) -> bool:
        doc = self.source.document()
        cursor = self.source.textCursor()
        if direction > 0:
            found = doc.find(PH, cursor.selectionEnd())
            if found.isNull():
                found = doc.find(PH, 0)
        else:
            found = doc.find(PH, cursor.selectionStart(), QTextDocument.FindFlag.FindBackward)
            if found.isNull():
                found = doc.find(PH, doc.characterCount(), QTextDocument.FindFlag.FindBackward)
        if found.isNull():
            return False
        self.source.setTextCursor(found)
        return True

    def text(self) -> str:
        return self.source.toPlainText()

    def set_text(self, latex: str) -> None:
        self.source.setPlainText(latex)
        cursor = self.source.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.source.setTextCursor(cursor)

    def clear(self) -> None:
        cursor = self.source.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.removeSelectedText()  # undoable, unlike clear()
        self.source.setFocus()

    def zoom(self, delta: int) -> None:
        self.font_px = max(10, min(28, self.font_px + delta))
        self._apply_font()
        self._update_preview()

    def _apply_font(self) -> None:
        font = self.theme.mono_font(self.font_px)
        self.source.setFont(font)
        self.source.setStyleSheet(f"font-size: {self._px(self.font_px)}px;")

    # ------------------------------------------------------------ preview
    def _on_text_changed(self) -> None:
        self._preview_timer.start()
        self._sync_star()

    def _update_preview(self) -> None:
        latex = self.text()
        self.char_count.setText(f"{len(latex)} chars" if latex else "")
        if not latex.strip():
            self.preview.set_latex("")
            self.preview.setText("Your equation appears here")
            self.preview_hint.setText("")
            return
        self.preview.set_latex(latex, size=34 + (self.font_px - 15) * 1.6)
        problem = brace_problem(latex)
        if not problem:
            try:
                error = render.render_error(latex)
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
            if error:
                problem = f"Preview is approximate: {error[:140]}"
        if problem:
            self.preview_hint.setText(f"⚠ {problem}")
            return
        placeholders = latex.count(PH)
        if placeholders:
            plural = "s" if placeholders != 1 else ""
            self.preview_hint.setText(f"{placeholders} empty placeholder{plural} ⬚ · Tab to jump")
        else:
            self.preview_hint.setText("")

    # ------------------------------------------------------------ output
    def _on_format_changed(self) -> None:
        self.format_key = self.format_combo.currentData() or "raw"

    def output_text(self) -> tuple[str, int]:
        cleaned, removed = strip_placeholders(self.text())
        return wrap_output(cleaned, self.format_key), removed

    def copy_latex(self) -> bool:
        if not self.text().strip():
            self.status.emit("Nothing to copy — the editor is empty")
            return False
        text, removed = self.output_text()
        label = "LaTeX" if self.format_key == "raw" else f"LaTeX ({self.format_combo.currentText()})"
        ok = self.copy(text, label)
        if ok:
            self._remember(strip_placeholders(self.text())[0].strip())
            if removed:
                self.status.emit(f"✓ Copied {label} · removed {removed} empty placeholder"
                                 f"{'s' if removed != 1 else ''}")
        return ok

    def _image_png(self, scale: float = 2.0) -> bytes:
        latex = strip_placeholders(self.text())[0]
        color = "#000000" if self.image_color == "black" else self.theme.math
        background = "#ffffff" if self.image_background == "white" else None
        return render.render_png(latex, color, 30, scale, background)

    def copy_png(self) -> bool:
        if not self.text().strip():
            self.status.emit("Nothing to copy — the editor is empty")
            return False
        ok = self.copy_image(self._image_png(), "equation image")
        if ok:
            self._remember(strip_placeholders(self.text())[0].strip())
        return ok

    def copy_unicode(self) -> bool:
        latex = strip_placeholders(self.text())[0]
        try:
            text = detailed_preview(latex)
        except Exception:  # noqa: BLE001
            text = latex
        return self.copy(text, "Unicode text")

    def save_png(self) -> None:
        if not self.text().strip():
            self.status.emit("Nothing to save — the editor is empty")
            return
        default = str(Path.home() / "Pictures" / "equation.png")
        path, _ = QFileDialog.getSaveFileName(self, "Save equation", default, "PNG image (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        try:
            Path(path).write_bytes(self._image_png(3.0))
        except OSError as exc:
            self.status.emit(f"Could not save: {exc}")
            return
        self.status.emit(f"✓ Saved {path}")

    def evaluate(self) -> None:
        latex = strip_placeholders(self.text())[0].strip()
        if not latex:
            self.status.emit("Nothing to evaluate")
            return
        self.send_to_calculator.emit(latex)

    def plot(self) -> None:
        latex = strip_placeholders(self.text())[0].strip()
        if not latex:
            self.status.emit("Nothing to plot")
            return
        self.send_to_graph.emit(latex)

    # ------------------------------------------------------------ snippets
    def ask_snippet(self) -> None:
        if not self.text().strip():
            self.status.emit("Write an equation first")
            return
        self.snippet_bar.setVisible(True)
        self.snippet_title.setFocus()
        self.snippet_title.selectAll()

    def _confirm_snippet(self) -> None:
        try:
            ident = save_snippet(self.snippet_title.text(), self.text())
        except (ValueError, OSError) as exc:
            self.status.emit(str(exc))
            return
        self.snippet_bar.setVisible(False)
        self.snippet_title.clear()
        self.status.emit(f"✓ Saved snippet “{ident}” — it appears in the Picker next time")
        self.source.setFocus()

    # ------------------------------------------------------------ history
    def _remember(self, latex: str) -> None:
        if not latex:
            return
        self.history = [latex] + [h for h in self.history if h != latex]
        del self.history[HISTORY_LIMIT:]
        self._refresh_lists()

    def toggle_favorite(self) -> None:
        latex = strip_placeholders(self.text())[0].strip()
        if not latex:
            self.status.emit("Nothing to favorite")
            return
        if latex in self.favorites:
            self.favorites.remove(latex)
            self.status.emit("Removed from favorites")
        else:
            self.favorites.insert(0, latex)
            self.status.emit("★ Added to favorites")
        self._refresh_lists()
        self._sync_star()

    def _sync_star(self) -> None:
        latex = strip_placeholders(self.text())[0].strip()
        self.star_button.setText("★" if latex and latex in self.favorites else "☆")

    def toggle_side(self) -> None:
        visible = not self.side_panel.isVisible()
        self.side_panel.setVisible(visible)
        self.side_button.setText("History ◂" if visible else "History ▸")
        if visible:
            self._refresh_lists()

    def _refresh_lists(self) -> None:
        for widget, items in ((self.history_list, self.history),
                              (self.favorites_list, self.favorites)):
            widget.clear()
            for latex in items:
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, latex)
                item.setToolTip(latex)
                item.setSizeHint(QSize(0, self._px(40)))
                widget.addItem(item)
                if self.side_panel.isVisible():
                    label = MathLabel(self.theme, size=16)
                    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    label.setContentsMargins(self._px(4), 0, 0, 0)
                    label.set_latex(latex)
                    widget.setItemWidget(item, label)
                else:
                    item.setText(latex)
            if not items:
                placeholder = QListWidgetItem(
                    "Copied equations appear here" if widget is self.history_list
                    else "Star an equation (☆ or Ctrl+D)")
                placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
                widget.addItem(placeholder)

    def _restore_item(self, item: QListWidgetItem) -> None:
        latex = item.data(Qt.ItemDataRole.UserRole)
        if latex:
            self.set_text(latex)
            self.source.setFocus()
            self.status.emit("Restored equation")

    def _list_menu(self, widget: QListWidget, pos) -> None:
        item = widget.itemAt(pos)
        latex = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not latex:
            return
        menu = QMenu(self)
        menu.addAction("Restore", lambda: self._restore_item(item))
        menu.addAction("Insert at cursor", lambda: self.insert_template(latex))
        menu.addAction("Copy LaTeX", lambda: self.copy(wrap_output(latex, self.format_key)))
        menu.addSeparator()
        if widget is self.favorites_list:
            menu.addAction("Remove from favorites", lambda: self._remove(self.favorites, latex))
        else:
            menu.addAction("Remove from history", lambda: self._remove(self.history, latex))
            menu.addAction("Clear history", self._clear_history)
        menu.exec(widget.mapToGlobal(pos))

    def _remove(self, items: list[str], latex: str) -> None:
        if latex in items:
            items.remove(latex)
        self._refresh_lists()
        self._sync_star()

    def _clear_history(self) -> None:
        self.history.clear()
        self._refresh_lists()

    # ------------------------------------------------------------ options
    def _set_image_background(self, key: str) -> None:
        self.image_background = key
        self._sync_option_checks()

    def _set_image_color(self, key: str) -> None:
        self.image_color = key
        self._sync_option_checks()

    def _sync_option_checks(self) -> None:
        for key, action in self.bg_actions.items():
            action.setChecked(key == self.image_background)
        for key, action in self.color_actions.items():
            action.setChecked(key == self.image_color)

    # ------------------------------------------------------------ ToolTab API
    def focus_primary(self) -> None:
        self.source.setFocus()

    def state(self) -> dict:
        return {
            "text": self.text(),
            "cursor": self.source.textCursor().position(),
            "format": self.format_key,
            "history": self.history[:HISTORY_LIMIT],
            "favorites": self.favorites[:200],
            "category": self.current_category,
            "font_px": self.font_px,
            "auto_close": self.source.auto_close,
            "image_background": self.image_background,
            "image_color": self.image_color,
            "side_visible": self.side_panel.isVisible() if self.isVisible() else
            not self.side_panel.isHidden(),
        }

    def restore(self, data: dict) -> None:
        if not isinstance(data, dict):
            return

        def strings(value) -> list[str]:
            return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []

        self.history = strings(data.get("history"))[:HISTORY_LIMIT]
        self.favorites = strings(data.get("favorites"))[:200]
        text = data.get("text")
        if isinstance(text, str):
            self.source.setPlainText(text)
            cursor = self.source.textCursor()
            position = data.get("cursor")
            if isinstance(position, int):
                cursor.setPosition(max(0, min(position, self.source.document().characterCount() - 1)))
            else:
                cursor.movePosition(QTextCursor.MoveOperation.End)
            self.source.setTextCursor(cursor)
        fmt = data.get("format")
        index = self.format_combo.findData(fmt)
        if index >= 0:
            self.format_combo.setCurrentIndex(index)
        category = data.get("category")
        if isinstance(category, str) and category in self.chips:
            self._show_category(category)
        font_px = data.get("font_px")
        if isinstance(font_px, int):
            self.font_px = max(10, min(28, font_px))
            self._apply_font()
        auto_close = data.get("auto_close")
        if isinstance(auto_close, bool):
            self.auto_close_action.setChecked(auto_close)
            self.source.auto_close = auto_close
        if data.get("image_background") in {"transparent", "white"}:
            self.image_background = data["image_background"]
        if data.get("image_color") in {"black", "theme"}:
            self.image_color = data["image_color"]
        self._sync_option_checks()
        if data.get("side_visible") is True and self.side_panel.isHidden():
            self.toggle_side()
        self._refresh_lists()
        self._sync_star()
        self._update_preview()


def _html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

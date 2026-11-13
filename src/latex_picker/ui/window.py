"""Main frameless popup window."""

from __future__ import annotations

import importlib
import re
import traceback

from PyQt6.QtCore import QEvent, QModelIndex, QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..clipboard import CopyResult, copy_to_clipboard, session_type
from ..config import AppConfig, State, load_workspace, record_recent, save_workspace
from ..environment import SessionInfo
from ..models import Category, Library, Snippet
from ..preview import MathPreviewService
from ..search import SearchEngine
from ..theme import Theme
from .category_bar import RECENT_ID, CategoryBar
from .model import SnippetDelegate, SnippetListModel, SnippetListView
from .preview_pane import PreviewPane
from .search_box import SearchBox


# key, label, icon, (module, class) -- the picker is built into the window.
TABS: list[tuple[str, str, str, tuple[str, str] | None]] = [
    ("picker", "Picker", "⌕", None),
    ("editor", "Editor", "✎", ("latex_picker.workspace.editor_tab", "EditorTab")),
    ("calculator", "Calculator", "=", ("latex_picker.workspace.calc_tab", "CalculatorTab")),
    ("graph", "Graph", "∿", ("latex_picker.workspace.graph_tab", "GraphTab")),
    ("matrix", "Matrix", "▦", ("latex_picker.workspace.matrix_tab", "MatrixTab")),
]
TAB_KEYS = [tab[0] for tab in TABS]
_PLACEHOLDER_RE = re.compile(r"<[A-Za-z][A-Za-z0-9 _-]*>")


class DragBar(QWidget):
    """Empty space in the top bar that moves the frameless window."""

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)


class LatexPickerWindow(QWidget):
    closed = pyqtSignal(int)  # seconds the process should stay alive for clipboard

    def __init__(
        self,
        library: Library,
        engine: SearchEngine,
        config: AppConfig,
        theme: Theme,
        state: State,
        session: SessionInfo,
        preview_service: MathPreviewService,
        warnings: list[str] | None = None,
        parent=None,
        mode: str | None = None,
        workspace: dict | None = None,
    ) -> None:
        super().__init__(parent)
        self.library = library
        self.engine = engine
        self.config = config
        self.theme = theme
        self.state = state
        self.session = session
        self.preview_service = preview_service
        self.warnings = warnings or []
        self._closed_emitted = False
        self._clipboard_hold_seconds = 0
        self._ready_for_blur = False
        self.workspace = workspace if workspace is not None else load_workspace()
        self.tabs: dict[str, QWidget] = {}
        self.current_mode = "picker"
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._clear_status)

        self.setWindowTitle("LaTeX Picker")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setStyleSheet(theme.stylesheet())

        self._build_ui()
        self._connect_signals()
        self._install_shortcuts()
        self.refresh()
        self._show_warnings()
        self.set_mode(self._initial_mode(mode), focus=False)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        theme = self.theme
        root = QVBoxLayout(self)
        root.setContentsMargins(round(18 * theme.scale), round(16 * theme.scale),
                                round(18 * theme.scale), round(12 * theme.scale))
        root.setSpacing(round(10 * theme.scale))

        root.addLayout(self._build_top_bar())
        self.pages = QStackedWidget()
        self.pages.setStyleSheet("QStackedWidget { background: transparent; }")
        self.picker_page = QWidget()
        self.picker_page.setObjectName("Transparent")
        picker_layout = QVBoxLayout(self.picker_page)
        picker_layout.setContentsMargins(0, 0, 0, 0)
        picker_layout.setSpacing(round(10 * theme.scale))
        self.pages.addWidget(self.picker_page)
        root.addWidget(self.pages, 1)
        outer_root = root
        root = picker_layout

        header = QHBoxLayout()
        header.setSpacing(round(12 * theme.scale))
        self.search_box = SearchBox(theme, self)
        header.addWidget(self.search_box, 1)
        self.count_label = QLabel("")
        self.count_label.setObjectName("Muted")
        self.count_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.count_label.setMinimumWidth(round(82 * theme.scale))
        header.addWidget(self.count_label)
        root.addLayout(header)

        counts = self.library.counts_by_category()
        valid_recent = [item for item in self.state.recent if self.library.snippet(item)]
        recent_count = len(valid_recent) if self.config.show_recent else 0
        self.category_bar = CategoryBar(
            theme, self.library.categories, counts,
            recent_count=recent_count,
        )
        root.addWidget(self.category_bar)

        content = QHBoxLayout()
        content.setSpacing(round(14 * theme.scale))
        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.stack.setStyleSheet("background: transparent;")

        self.model = SnippetListModel(self.library, self)
        self.view = SnippetListView(self)
        self.view.setModel(self.model)
        self.delegate = SnippetDelegate(theme, self.library, self.view, self.view)
        self.view.setItemDelegate(self.delegate)
        self.stack.addWidget(self.view)

        self.empty_widget = self._build_empty_state()
        self.stack.addWidget(self.empty_widget)
        content.addWidget(self.stack, 1)

        self.preview_pane: PreviewPane | None = None
        if self.config.show_preview:
            self.preview_pane = PreviewPane(theme, self.preview_service, self)
            content.addWidget(self.preview_pane)
        root.addLayout(content, 1)
        root = outer_root

        root.addWidget(self._separator())

        footer = QHBoxLayout()
        footer.setSpacing(round(10 * theme.scale))
        self.hints_widget = QWidget()
        self.hints_widget.setObjectName("Transparent")
        self.hints_layout = QHBoxLayout(self.hints_widget)
        self.hints_layout.setContentsMargins(0, 0, 0, 0)
        self.hints_layout.setSpacing(round(10 * theme.scale))
        footer.addWidget(self.hints_widget)
        footer.addStretch(1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("Faint")
        self.status_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.status_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.status_label.setMaximumWidth(round(520 * theme.scale))
        footer.addWidget(self.status_label)
        root.addLayout(footer)

    def _build_top_bar(self) -> QHBoxLayout:
        theme = self.theme
        bar = QHBoxLayout()
        bar.setSpacing(round(4 * theme.scale))
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_buttons: dict[str, QPushButton] = {}
        for index, (key, label, icon, _spec) in enumerate(TABS):
            button = QPushButton(f"{icon}  {label}")
            button.setObjectName("ModeTab")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setToolTip(f"{label}  (Ctrl+{index + 1})")
            button.clicked.connect(lambda _checked, k=key: self.set_mode(k))
            self.mode_group.addButton(button)
            self.mode_buttons[key] = button
            bar.addWidget(button)
        drag = DragBar()
        drag.setMinimumHeight(round(28 * theme.scale))
        drag.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        drag.setToolTip("Drag to move")
        bar.addWidget(drag, 1)

        self.pin_button = QPushButton("📌")
        self.pin_button.setObjectName("ModeTab")
        self.pin_button.setCheckable(True)
        self.pin_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pin_button.setToolTip("Keep open when focus is lost")
        bar.addWidget(self.pin_button)
        close_button = QPushButton("✕")
        close_button.setObjectName("ModeTab")
        close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close_button.setToolTip("Close (Esc)")
        close_button.clicked.connect(self.close)
        bar.addWidget(close_button)
        return bar

    def _install_shortcuts(self) -> None:
        for index, key in enumerate(TAB_KEYS):
            for combo in (f"Ctrl+{index + 1}", f"Alt+{index + 1}"):
                shortcut = QShortcut(QKeySequence(combo), self)
                shortcut.activated.connect(lambda k=key: self.set_mode(k))
        for combo, delta in (("Ctrl+PgDown", 1), ("Ctrl+PgUp", -1),
                             ("Ctrl+Tab", 1), ("Ctrl+Shift+Tab", -1)):
            shortcut = QShortcut(QKeySequence(combo), self)
            shortcut.activated.connect(lambda d=delta: self.cycle_mode(d))

    # --------------------------------------------------------------- modes
    def _initial_mode(self, mode: str | None) -> str:
        if mode in TAB_KEYS:
            return mode
        start = getattr(self.config, "start_mode", "last")
        if start in TAB_KEYS:
            return start
        last = self.workspace.get("mode")
        return last if last in TAB_KEYS else "picker"

    def cycle_mode(self, delta: int) -> None:
        index = TAB_KEYS.index(self.current_mode)
        self.set_mode(TAB_KEYS[(index + delta) % len(TAB_KEYS)])

    def set_mode(self, key: str, focus: bool = True) -> None:
        if key not in TAB_KEYS:
            return
        page = self.picker_page if key == "picker" else self._ensure_tab(key)
        self.current_mode = key
        self.pages.setCurrentWidget(page)
        self.mode_buttons[key].setChecked(True)
        self._update_hints()
        if focus or self.isVisible():
            QTimer.singleShot(0, self._focus_current)

    def _focus_current(self) -> None:
        if self.current_mode == "picker":
            self.search_box.focus_input()
            return
        tab = self.tabs.get(self.current_mode)
        if tab is not None and hasattr(tab, "focus_primary"):
            tab.focus_primary()

    def _ensure_tab(self, key: str) -> QWidget:
        if key in self.tabs:
            return self.tabs[key]
        spec = next(tab for tab in TABS if tab[0] == key)[3]
        try:
            module = importlib.import_module(spec[0])
            tab = getattr(module, spec[1])(self.theme, self)
        except Exception:  # noqa: BLE001 - one broken tool must not kill the app
            tab = self._error_page(key, traceback.format_exc())
        else:
            saved = (self.workspace.get("tabs") or {}).get(key)
            if isinstance(saved, dict):
                try:
                    tab.restore(saved)
                except Exception:  # noqa: BLE001 - stale state is discarded
                    self.show_status(f"Couldn't restore saved {key} state", error=True)
            tab.status.connect(self.show_status)
            tab.insert_latex.connect(self.insert_into_editor)
            tab.send_to_calculator.connect(self.send_to_calculator)
            tab.send_to_graph.connect(self.send_to_graph)
        self.tabs[key] = tab
        self.pages.addWidget(tab)
        return tab

    def _error_page(self, key: str, details: str) -> QWidget:
        page = QLabel(f"The {key} tool failed to load.\n\n{details.strip().splitlines()[-1]}")
        page.setObjectName("Error")
        page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page.setWordWrap(True)
        page.setToolTip(details)
        return page

    def _update_hints(self) -> None:
        while self.hints_layout.count():
            item = self.hints_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        if self.current_mode == "picker":
            hints = [("↑ ↓", "Navigate"), ("Tab", "Category"), ("Enter", "Copy"),
                     ("⇧ Enter", "To editor"), ("Esc", "Close")]
        else:
            tab = self.tabs.get(self.current_mode)
            hints = list(getattr(tab, "hints", []) or [])[:4]
            hints += [("Ctrl 1–5", "Switch"), ("Esc", "Close")]
        for key, label in hints:
            self._add_hint(self.hints_layout, key, label)

    # ------------------------------------------------------ cross-tab links
    def insert_into_editor(self, latex: str) -> None:
        editor = self._ensure_tab("editor")
        self.set_mode("editor")
        if hasattr(editor, "insert_latex_text"):
            editor.insert_latex_text(latex)
            self.show_status("Inserted into the editor")

    def send_to_calculator(self, text: str) -> None:
        calc = self._ensure_tab("calculator")
        self.set_mode("calculator")
        if hasattr(calc, "evaluate_text"):
            calc.evaluate_text(text)

    def send_to_graph(self, text: str) -> None:
        graph = self._ensure_tab("graph")
        self.set_mode("graph")
        if hasattr(graph, "add_expression"):
            graph.add_expression(text)

    # -------------------------------------------------------------- status
    def show_status(self, message: str, error: bool | None = None) -> None:
        if error is None:
            error = message.lower().startswith(("copy failed", "error", "couldn't"))
        self.status_label.setObjectName("Error" if error else "Success")
        self.status_label.setText(message)
        self.status_label.setToolTip(message)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self._status_timer.start(4000)

    def _clear_status(self) -> None:
        self.status_label.setObjectName("Faint")
        self.status_label.setText("")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    # ---------------------------------------------------------- persistence
    def save_workspace_state(self) -> None:
        tabs = dict(self.workspace.get("tabs") or {})
        for key, tab in self.tabs.items():
            if hasattr(tab, "state"):
                try:
                    tabs[key] = tab.state()
                except Exception:  # noqa: BLE001 - never lose the other tabs
                    continue
        self.workspace = {"version": 1, "mode": self.current_mode, "tabs": tabs}
        save_workspace(self.workspace)

    def _build_empty_state(self) -> QWidget:
        theme = self.theme
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, round(30 * theme.scale), 0, round(30 * theme.scale))
        layout.setSpacing(round(7 * theme.scale))
        layout.addStretch(1)

        glyph = QLabel("∅")
        glyph.setObjectName("PreviewText")
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        glyph.setStyleSheet(f"font-size: {round(36 * theme.scale)}px;")
        layout.addWidget(glyph)

        self.empty_title = QLabel("No expressions found")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title.setStyleSheet(
            f"font-size: {round(15 * theme.scale)}px; font-weight: 600;"
        )
        layout.addWidget(self.empty_title)

        self.empty_message = QLabel("Try another name, symbol, or LaTeX command.")
        self.empty_message.setObjectName("Muted")
        self.empty_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_message.setWordWrap(True)
        layout.addWidget(self.empty_message)
        layout.addStretch(1)
        return widget

    def _separator(self) -> QFrame:
        line = QFrame(self)
        line.setObjectName("Separator")
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        return line

    def _add_hint(self, layout: QHBoxLayout, key: str, label: str) -> None:
        key_label = QLabel(key)
        key_label.setObjectName("Keycap")
        key_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        key_label.setFont(self.theme.mono_font(9.5))
        layout.addWidget(key_label)
        text = QLabel(label)
        text.setObjectName("Faint")
        layout.addWidget(text)

    def _show_warnings(self) -> None:
        messages = list(self.warnings)
        if messages:
            self.status_label.setText(f"⚠ {len(messages)} warning{'s' if len(messages) > 1 else ''}")
            self.status_label.setToolTip("\n".join(messages))

    # ------------------------------------------------------------- wiring
    def _connect_signals(self) -> None:
        self.search_box.text_changed.connect(lambda _text: self.refresh())
        self.search_box.navigate.connect(self._navigate)
        self.search_box.activate.connect(self._copy_current)
        self.search_box.activate_alt.connect(self._insert_current)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._picker_menu)
        self.search_box.dismiss.connect(self.close)
        self.search_box.cycle_category.connect(self._cycle_category)
        self.category_bar.category_changed.connect(self._set_category)
        self.view.selectionModel().currentChanged.connect(self._on_current_changed)
        self.view.clicked.connect(self._copy_index)
        self.view.hovered.connect(self._preview_index)
        self.view.unhovered.connect(self._restore_preview)

    # ------------------------------------------------------------ filtering
    def refresh(self) -> None:
        query = self.search_box.text()
        category = self.category_bar.current
        allowed_ids = None
        search_category = None
        if category == RECENT_ID:
            allowed_ids = [item for item in self.state.recent if self.library.snippet(item)]
        else:
            search_category = category
        results = self.engine.search(query, search_category, allowed_ids=allowed_ids)
        self.model.set_snippets(results)

        if results:
            self.stack.setCurrentWidget(self.view)
            index = self.model.index(0, 0)
            self.view.setCurrentIndex(index)
            self.view.scrollToTop()
            self._preview_snippet(results[0])
        else:
            self.stack.setCurrentWidget(self.empty_widget)
            self.view.setCurrentIndex(QModelIndex())
            if query:
                self.empty_title.setText("No matching expressions")
                self.empty_message.setText(f"Nothing matches “{query}”. Try another name or symbol.")
            else:
                self.empty_title.setText("Nothing here yet")
                self.empty_message.setText("Copy an expression once and it will appear in Recent.")
            if self.preview_pane is not None:
                self.preview_pane.set_placeholder("No matching expression to preview.")

        total = len(self.library.snippets)
        if query or category is not None:
            self.count_label.setText(f"{len(results)} of {total}")
        else:
            self.count_label.setText(
                f"{total} expression{'s' if total != 1 else ''}"
            )
        self.count_label.setToolTip(
            f"{len(results)} result{'s' if len(results) != 1 else ''} · {total} total"
        )

    def _set_category(self, category: str | None) -> None:
        self.refresh()
        self.search_box.focus_input()

    def _cycle_category(self, delta: int) -> None:
        self.category_bar.cycle(delta)

    def _navigate(self, delta: int) -> None:
        if self.model.rowCount() == 0:
            return
        current = self.view.currentIndex()
        row = current.row() if current.isValid() else -1
        max_row = self.model.rowCount() - 1
        if row < 0:
            row = 0 if delta >= 0 else max_row
        else:
            row = max(0, min(max_row, row + delta))
        index = self.model.index(row, 0)
        self.view.setCurrentIndex(index)
        self.view.scrollTo(index, QAbstractItemView.ScrollHint.EnsureVisible)

    # ------------------------------------------------------------- preview
    def _on_current_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        self._preview_index(current)

    def _preview_index(self, index: QModelIndex) -> None:
        if not index.isValid() or self.preview_pane is None:
            return
        snippet = self.model.snippet(index)
        if snippet is not None:
            self._preview_snippet(snippet)

    def _preview_snippet(self, snippet: Snippet) -> None:
        if self.preview_pane is None:
            return
        category: Category | None = self.library.category(snippet.category)
        self.preview_pane.set_snippet(snippet, category)

    def _restore_preview(self) -> None:
        if self.preview_pane is None:
            return
        index = self.view.currentIndex()
        if index.isValid():
            self._preview_index(index)
        else:
            self.preview_pane.set_placeholder()

    # -------------------------------------------------------------- copying
    def _insert_current(self) -> None:
        snippet = self.model.snippet(self.view.currentIndex())
        if snippet is None:
            return
        record_recent(self.state, snippet.id, self.config.recent_limit)
        self.insert_into_editor(snippet.latex)

    def _picker_menu(self, pos) -> None:
        index = self.view.indexAt(pos)
        snippet = self.model.snippet(index) if index.isValid() else None
        if snippet is None:
            return
        menu = QMenu(self)
        menu.addAction("Copy and close", lambda: self._copy_index(index))
        menu.addAction("Copy (keep open)", lambda: self._copy_keep_open(snippet))
        menu.addSeparator()
        menu.addAction("Insert into Editor", lambda: (
            record_recent(self.state, snippet.id, self.config.recent_limit),
            self.insert_into_editor(snippet.latex)))
        if not _PLACEHOLDER_RE.search(snippet.latex):
            menu.addAction("Evaluate in Calculator",
                           lambda: self.send_to_calculator(snippet.latex))
        menu.exec(self.view.viewport().mapToGlobal(pos))

    def _copy_keep_open(self, snippet: Snippet) -> None:
        result = copy_to_clipboard(
            snippet.latex, qt_setter=lambda text: QApplication.clipboard().setText(text)
        )
        if result.ok:
            record_recent(self.state, snippet.id, self.config.recent_limit)
            self.show_status(f"✓ Copied {snippet.title}")
        else:
            self.show_status(f"Copy failed: {result.error}", error=True)

    def _copy_current(self) -> None:
        self._copy_index(self.view.currentIndex())

    def _copy_index(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        snippet = self.model.snippet(index)
        if snippet is None:
            return
        result: CopyResult = copy_to_clipboard(
            snippet.latex,
            qt_setter=lambda text: QApplication.clipboard().setText(text),
        )
        if not result.ok:
            self.status_label.setObjectName("Error")
            self.status_label.setText("Could not copy to the clipboard")
            self.status_label.setToolTip(result.error)
            self.status_label.style().unpolish(self.status_label)
            self.status_label.style().polish(self.status_label)
            return

        record_recent(self.state, snippet.id, self.config.recent_limit)
        if result.backend.startswith("qt") and session_type() == "wayland":
            # Without wl-copy the Qt client owns the Wayland clipboard.  Keep the
            # process alive for a while after hiding so the paste still works.
            self._clipboard_hold_seconds = 60
        self.close()

    # --------------------------------------------------------------- window
    def _screen(self):
        screen = QGuiApplication.screenAt(QCursor.pos())
        return screen or QGuiApplication.primaryScreen()

    def showEvent(self, event) -> None:
        screen = self._screen()
        if screen is not None:
            available = screen.availableGeometry()
            width = min(self.config.width, max(560, available.width() - 80))
            height = min(self.config.height, max(420, available.height() - 100))
            self.resize(width, height)
            if self.preview_pane is not None:
                self.preview_pane.setVisible(width >= 760)
            if not self.session.is_wayland:
                x = available.x() + (available.width() - width) // 2
                y = available.y() + (available.height() - height) // 2
                self.move(QPoint(x, y))
        else:
            self.resize(self.config.width, self.config.height)
        super().showEvent(event)
        self._ready_for_blur = False
        QTimer.singleShot(250, self._enable_blur_close)
        QTimer.singleShot(0, self.search_box.focus_input)
        self.raise_()
        self.activateWindow()

    def _enable_blur_close(self) -> None:
        self._ready_for_blur = True

    def event(self, event) -> bool:
        if (
            event.type() == QEvent.Type.WindowDeactivate
            and self._blur_close_allowed()
            and self._ready_for_blur
            and self.isVisible()
        ):
            QTimer.singleShot(0, self.close)
        return super().event(event)

    def _blur_close_allowed(self) -> bool:
        if not self.config.close_on_blur or self.pin_button.isChecked():
            return False
        if QApplication.activeModalWidget() is not None or QApplication.activePopupWidget():
            return False
        if self.current_mode != "picker" and not getattr(
                self.config, "tools_close_on_blur", False):
            return False
        return True

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        if not self._closed_emitted:
            self._closed_emitted = True
            self.save_workspace_state()
            self.closed.emit(self._clipboard_hold_seconds)
        super().closeEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)
        radius = round(16 * self.theme.scale)
        path = QPainterPath()
        path.addRoundedRect(
            float(rect.x()), float(rect.y()), float(rect.width()),
            float(rect.height()), radius, radius,
        )
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0.0, QColor(self.theme.surface))
        gradient.setColorAt(0.35, QColor(self.theme.bg))
        gradient.setColorAt(1.0, QColor(self.theme.bg))
        painter.fillPath(path, gradient)
        painter.setPen(QPen(QColor(self.theme.border_strong), 1))
        painter.drawPath(path)
        painter.end()

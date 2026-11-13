"""Search input with a painted magnifier and keyboard-first navigation."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QKeyEvent, QPainter, QPen
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QToolButton,
    QWidget,
)

from ..theme import Theme


class SearchIcon(QWidget):
    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        size = round(18 * theme.scale)
        self.setFixedSize(size, size)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(self.theme.muted), max(1.2, 1.6 * self.theme.scale))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        scale = self.theme.scale
        diameter = 10 * scale
        painter.drawEllipse(QRectF(2.0 * scale, 2.0 * scale, diameter, diameter))
        painter.drawLine(
            int(11.5 * scale), int(11.5 * scale),
            int(16 * scale), int(16 * scale),
        )
        painter.end()


class SearchLineEdit(QLineEdit):
    navigate = pyqtSignal(int)
    activate = pyqtSignal()
    activate_alt = pyqtSignal()
    dismiss = pyqtSignal()
    cycle_category = pyqtSignal(int)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Down:
            self.navigate.emit(1)
            event.accept()
            return
        if key == Qt.Key.Key_Up:
            self.navigate.emit(-1)
            event.accept()
            return
        if key == Qt.Key.Key_PageDown:
            self.navigate.emit(5)
            event.accept()
            return
        if key == Qt.Key.Key_PageUp:
            self.navigate.emit(-5)
            event.accept()
            return
        if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            if event.modifiers() & (Qt.KeyboardModifier.ShiftModifier
                                    | Qt.KeyboardModifier.ControlModifier):
                self.activate_alt.emit()
            else:
                self.activate.emit()
            event.accept()
            return
        if key == Qt.Key.Key_Escape:
            self.dismiss.emit()
            event.accept()
            return
        if key == Qt.Key.Key_Tab:
            self.cycle_category.emit(-1 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1)
            event.accept()
            return
        if key == Qt.Key.Key_Backtab:
            self.cycle_category.emit(-1)
            event.accept()
            return
        super().keyPressEvent(event)


class SearchBox(QWidget):
    text_changed = pyqtSignal(str)
    navigate = pyqtSignal(int)
    activate = pyqtSignal()
    activate_alt = pyqtSignal()
    dismiss = pyqtSignal()
    cycle_category = pyqtSignal(int)

    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.setObjectName("SearchBox")
        self.setFixedHeight(round(48 * theme.scale))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            round(14 * theme.scale), 0, round(8 * theme.scale), 0
        )
        layout.setSpacing(round(10 * theme.scale))

        self.icon = SearchIcon(theme, self)
        layout.addWidget(self.icon)

        self.line_edit = SearchLineEdit(self)
        self.line_edit.setPlaceholderText(
            "Search LaTeX — fraction, integral, matrix, alpha…"
        )
        self.line_edit.setClearButtonEnabled(False)
        self.line_edit.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.line_edit.installEventFilter(self)
        layout.addWidget(self.line_edit, 1)

        self.clear_button = QToolButton(self)
        self.clear_button.setObjectName("ClearButton")
        self.clear_button.setText("✕")
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_button.setFixedSize(
            round(24 * theme.scale), round(24 * theme.scale)
        )
        self.clear_button.setVisible(False)
        self.clear_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_button.setToolTip("Clear search (Esc)")
        layout.addWidget(self.clear_button)

        self.line_edit.textChanged.connect(self._on_text_changed)
        self.line_edit.navigate.connect(self.navigate)
        self.line_edit.activate.connect(self.activate)
        self.line_edit.activate_alt.connect(self.activate_alt)
        self.line_edit.dismiss.connect(self.dismiss)
        self.line_edit.cycle_category.connect(self.cycle_category)
        self.clear_button.clicked.connect(self._clear)
        self._focused = False

    def _on_text_changed(self, text: str) -> None:
        self.clear_button.setVisible(bool(text))
        self.text_changed.emit(text)

    def _clear(self) -> None:
        self.line_edit.clear()
        self.line_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        self.line_edit.keyPressEvent(event)

    def focus_input(self) -> None:
        self.line_edit.setFocus(Qt.FocusReason.OtherFocusReason)
        self.line_edit.selectAll()

    def text(self) -> str:
        return self.line_edit.text()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.line_edit and event.type() in {
            QEvent.Type.FocusIn, QEvent.Type.FocusOut
        }:
            focused = event.type() == QEvent.Type.FocusIn
            if focused != self._focused:
                self._focused = focused
                self.setProperty("focused", focused)
                self.style().unpolish(self)
                self.style().polish(self)
                self.update()
        return super().eventFilter(obj, event)

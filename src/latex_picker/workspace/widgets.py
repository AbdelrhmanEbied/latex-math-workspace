"""Shared widgets and helpers for the workspace tabs.

Public API (stable):

* ``ToolTab``: base class for every tool tab.  Signals ``insert_latex(str)``
  (send LaTeX to the Editor tab), ``send_to_calculator(str)``,
  ``send_to_graph(str)``, ``status(str)`` (transient footer message).
  Override ``state()``, ``restore(data)``, ``focus_primary()``.
  Helpers ``copy(text, what)`` and ``copy_image(png)``.
* ``MathLabel(theme, size=22)``: QLabel showing rendered LaTeX via
  ``set_latex(latex)``; asynchronous, falls back to Unicode text.
* ``section_label(text)``, ``hline()``, ``FlowLayout`` for wrapping buttons.
"""

from __future__ import annotations

import itertools

from PyQt6.QtCore import QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QLayout,
    QSizePolicy,
    QWidget,
)

from ..clipboard import copy_image_to_clipboard, copy_to_clipboard
from ..theme import Theme
from . import render

_ids = itertools.count(1)


class ToolTab(QWidget):
    insert_latex = pyqtSignal(str)
    send_to_calculator = pyqtSignal(str)
    send_to_graph = pyqtSignal(str)
    status = pyqtSignal(str)

    key = "tool"
    title = "Tool"
    hints: list[tuple[str, str]] = []

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.setObjectName("Transparent")

    def state(self) -> dict:
        return {}

    def restore(self, data: dict) -> None:  # noqa: ARG002
        return None

    def focus_primary(self) -> None:
        return None

    def copy(self, text: str, what: str = "LaTeX") -> bool:
        if not text:
            self.status.emit("Nothing to copy")
            return False
        result = copy_to_clipboard(
            text, qt_setter=lambda value: QApplication.clipboard().setText(value)
        )
        if result.ok:
            self.status.emit(f"✓ Copied {what}")
        else:
            self.status.emit(f"Copy failed: {result.error}")
        return result.ok

    def copy_image(self, png: bytes, what: str = "image") -> bool:
        def qt_setter(data: bytes) -> None:
            image = QImage.fromData(data, "PNG")
            QApplication.clipboard().setImage(image)

        result = copy_image_to_clipboard(png, qt_setter=qt_setter)
        self.status.emit(f"✓ Copied {what}" if result.ok else f"Copy failed: {result.error}")
        return result.ok


class MathLabel(QLabel):
    """Displays rendered LaTeX.  Rendering happens on a background thread."""

    def __init__(self, theme: Theme, size: float = 22, parent: QWidget | None = None,
                 color: str | None = None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.size_px = size
        self.color = color or theme.math
        self._key = f"math-{next(_ids)}"
        self._latex = ""
        self.setObjectName("MathOut")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        render.service().rendered.connect(self._on_rendered)

    def latex(self) -> str:
        return self._latex

    def set_latex(self, latex: str, size: float | None = None) -> None:
        if size is not None:
            self.size_px = size
        self._latex = latex or ""
        if not self._latex.strip():
            self.clear()
            return
        dpr = self.devicePixelRatioF() or 1.0
        render.service().request(self._key, self._latex, self.color,
                                 self.size_px * self.theme.scale, dpr)

    def _on_rendered(self, key: str, image: QImage) -> None:
        if key != self._key:
            return
        try:
            self.setPixmap(QPixmap.fromImage(image))
        except RuntimeError:  # widget deleted while rendering
            pass

    def png(self, background: str | None = None) -> bytes:
        return render.render_png(self._latex, self.color, self.size_px * 1.4, 2.0, background)


def section_label(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("SectionTitle")
    return label


def hline() -> QFrame:
    line = QFrame()
    line.setObjectName("Separator")
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    return line


class FlowLayout(QLayout):
    """A layout that wraps child widgets onto new lines, like text."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 4) -> None:
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._layout(QRect(0, 0, width, 0), dry=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._layout(rect, dry=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _layout(self, rect: QRect, dry: bool) -> int:
        x, y, line_height = rect.x(), rect.y(), 0
        for item in self._items:
            if item.widget() is not None and not item.widget().isVisible() and not dry:
                pass
            hint = item.sizeHint()
            next_x = x + hint.width() + self._spacing
            if next_x - self._spacing > rect.right() + 1 and line_height > 0:
                x = rect.x()
                y += line_height + self._spacing
                next_x = x + hint.width() + self._spacing
                line_height = 0
            if not dry:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y()

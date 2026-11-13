"""Right-hand detail pane with a typeset preview and the LaTeX source."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
)

from ..latex_preview import detailed_preview
from ..models import Category, Snippet
from ..preview import MathPreviewService
from ..theme import Theme


class PreviewPane(QFrame):
    def __init__(self, theme: Theme, service: MathPreviewService, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.service = service
        self.setObjectName("PreviewPane")
        self.setFixedWidth(round(300 * theme.scale))
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self._current_key = ""
        self._snippet: Snippet | None = None
        self._fallback = ""
        self._pixmaps: dict[str, QPixmap] = {}
        self._failed: set[str] = set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            round(16 * theme.scale), round(14 * theme.scale),
            round(16 * theme.scale), round(14 * theme.scale),
        )
        layout.setSpacing(round(8 * theme.scale))

        header = QLabel("PREVIEW")
        header.setObjectName("PaneTitle")
        layout.addWidget(header)

        self.math_label = QLabel("∑")
        self.math_label.setObjectName("PreviewText")
        self.math_label.setTextFormat(Qt.TextFormat.PlainText)
        self.math_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.math_label.setWordWrap(True)
        self.math_label.setMinimumHeight(round(108 * theme.scale))
        self.math_label.setMaximumHeight(round(150 * theme.scale))
        self.math_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self.math_label)

        self.title_label = QLabel("")
        self.title_label.setObjectName("PaneTitleText")
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.category_label = QLabel("")
        self.category_label.setObjectName("Muted")
        self.category_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.category_label)

        source_header = QLabel("LATEX")
        source_header.setObjectName("PaneTitle")
        layout.addSpacing(round(3 * theme.scale))
        layout.addWidget(source_header)

        self.source_label = QLabel("")
        self.source_label.setObjectName("Source")
        self.source_label.setTextFormat(Qt.TextFormat.PlainText)
        self.source_label.setWordWrap(True)
        self.source_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.source_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding
        )
        layout.addWidget(self.source_label)

        self.description_label = QLabel("")
        self.description_label.setObjectName("Muted")
        self.description_label.setTextFormat(Qt.TextFormat.PlainText)
        self.description_label.setWordWrap(True)
        layout.addWidget(self.description_label)
        layout.addStretch(1)

        self.hint_label = QLabel("Enter or click a result to copy")
        self.hint_label.setObjectName("Faint")
        self.hint_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.hint_label)

        self.service.signals.rendered.connect(self._on_rendered)
        self.service.signals.failed.connect(self._on_failed)

    def _set_math_text(self, text: str) -> None:
        self.math_label.setPixmap(QPixmap())
        self.math_label.setText(text)
        lines = max(1, text.count("\n") + 1)
        if lines == 1:
            size = 25
        elif lines <= 3:
            size = 20
        elif lines <= 5:
            size = 15
        else:
            size = 13
        self.math_label.setStyleSheet(
            f"font-size: {round(size * self.theme.scale)}px;"
        )

    def _set_pixmap(self, key: str, pixmap: QPixmap) -> None:
        self._pixmaps[key] = pixmap
        available_width = max(
            round(160 * self.theme.scale), self.width() - round(32 * self.theme.scale)
        )
        available_height = round(140 * self.theme.scale)
        scaled = pixmap.scaled(
            available_width,
            available_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.math_label.setText("")
        self.math_label.setPixmap(scaled)

    def set_snippet(self, snippet: Snippet, category: Category | None) -> None:
        self._snippet = snippet
        self.title_label.setText(snippet.title)
        if category is not None:
            self.category_label.setText(f"{category.symbol}   {category.name}")
        else:
            self.category_label.setText(snippet.category)
        self.source_label.setText(snippet.latex)
        self.description_label.setText(snippet.description)

        fallback = snippet.preview
        if "\\begin{" in snippet.latex or "\n" in fallback:
            fallback = detailed_preview(snippet.latex)
        self._fallback = fallback
        self._set_math_text(fallback)

        if not self.service.enabled:
            self._current_key = ""
            return
        key = self.service.key(snippet.id, self.theme.math)
        self._current_key = key
        if key in self._pixmaps:
            self._set_pixmap(key, self._pixmaps[key])
            return
        if key in self._failed:
            return
        cached = self.service.cached(key)
        if cached is not None:
            self._load(key, cached)
            return
        self.service.request(snippet.id, snippet.latex, self.theme.math)

    def set_placeholder(self, message: str = "Select an expression") -> None:
        self._current_key = ""
        self._snippet = None
        self._set_math_text("∑")
        self.title_label.setText("Nothing selected")
        self.category_label.setText("")
        self.source_label.setText("")
        self.description_label.setText(message)

    def _load(self, key: str, png: bytes) -> None:
        pixmap = QPixmap()
        if not pixmap.loadFromData(png, "PNG"):
            self._failed.add(key)
            return
        self._set_pixmap(key, pixmap)

    def _on_rendered(self, key: str, png: bytes) -> None:
        if key != self._current_key:
            return
        self._load(key, png)

    def _on_failed(self, key: str) -> None:
        self._failed.add(key)
        if key == self._current_key:
            self._set_math_text(self._fallback)

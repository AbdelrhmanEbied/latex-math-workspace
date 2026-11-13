"""List model, custom delegate and hover-aware list view."""

from __future__ import annotations

from PyQt6.QtCore import QAbstractListModel, QModelIndex, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import QListView, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from ..models import Category, Library, Snippet
from ..theme import Theme

SNIPPET_ROLE = Qt.ItemDataRole.UserRole + 1
_INVALID_INDEX = QModelIndex()


class SnippetListModel(QAbstractListModel):
    def __init__(self, library: Library, parent=None) -> None:
        super().__init__(parent)
        self.library = library
        self._snippets: list[Snippet] = []

    def set_snippets(self, snippets: list[Snippet]) -> None:
        self.beginResetModel()
        self._snippets = snippets
        self.endResetModel()

    def snippets(self) -> list[Snippet]:
        return list(self._snippets)

    def snippet(self, index: QModelIndex | int) -> Snippet | None:
        row = index.row() if isinstance(index, QModelIndex) else index
        if 0 <= row < len(self._snippets):
            return self._snippets[row]
        return None

    def rowCount(self, parent=_INVALID_INDEX) -> int:
        return 0 if parent.isValid() else len(self._snippets)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._snippets)):
            return None
        snippet = self._snippets[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return snippet.title
        if role == SNIPPET_ROLE:
            return snippet
        if role == Qt.ItemDataRole.ToolTipRole:
            description = f"\n\n{snippet.description}" if snippet.description else ""
            return f"{snippet.title}\n{snippet.latex}{description}"
        return None


class SnippetListView(QListView):
    hovered = pyqtSignal(object)
    unhovered = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.hovered_index = QModelIndex()
        self.setMouseTracking(True)
        self.setUniformItemSizes(True)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFrameShape(QListView.Shape.NoFrame)
        self.setSpacing(0)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        index = self.indexAt(event.position().toPoint())
        if index != self.hovered_index:
            self.hovered_index = index
            self.viewport().update()
            if index.isValid():
                self.hovered.emit(index)
            else:
                self.unhovered.emit()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self.hovered_index.isValid():
            self.hovered_index = QModelIndex()
            self.viewport().update()
        self.unhovered.emit()
        super().leaveEvent(event)


class SnippetDelegate(QStyledItemDelegate):
    def __init__(self, theme: Theme, library: Library, view: SnippetListView, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.library = library
        self.view = view
        self.row_height = round(64 * theme.scale)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(0, self.row_height)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        snippet: Snippet | None = index.data(SNIPPET_ROLE)
        if snippet is None:
            return
        theme = self.theme
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        row = option.rect.adjusted(round(5 * theme.scale), 2,
                                   -round(5 * theme.scale), -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = index == self.view.hovered_index
        radius = round(10 * theme.scale)

        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.selection))
            painter.drawRoundedRect(row, radius, radius)
        elif hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.surface))
            painter.drawRoundedRect(row, radius, radius)

        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.accent))
            bar_height = round(26 * theme.scale)
            bar_width = max(2, round(3 * theme.scale))
            painter.drawRoundedRect(
                row.left() + round(9 * theme.scale),
                row.center().y() - bar_height // 2,
                bar_width,
                bar_height,
                bar_width / 2,
                bar_width / 2,
            )

        category: Category | None = self.library.category(snippet.category)
        symbol = category.symbol if category else "·"
        badge_size = round(32 * theme.scale)
        badge_x = row.left() + round(18 * theme.scale)
        badge_y = row.center().y() - badge_size // 2
        badge_rect = QRect(badge_x, badge_y, badge_size, badge_size)
        painter.setPen(QPen(QColor(theme.border), 1))
        painter.setBrush(QColor(theme.accent_soft if selected else theme.surface_alt))
        painter.drawRoundedRect(badge_rect, round(9 * theme.scale), round(9 * theme.scale))
        painter.setPen(QColor(theme.accent))
        symbol_font = theme.math_font(16)
        painter.setFont(symbol_font)
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, symbol)

        text_x = badge_rect.right() + round(13 * theme.scale)
        right_edge = row.right() - round(16 * theme.scale)
        title_font = theme.ui_font(13.5, QFont.Weight.DemiBold)
        title_metrics = QFontMetrics(title_font)
        painter.setFont(title_font)
        painter.setPen(QColor(theme.text))

        preview_font = theme.math_font(15)
        preview_metrics = QFontMetrics(preview_font)
        preview = snippet.preview.replace("\n", "  ·  ")
        max_preview_width = max(90, int((right_edge - text_x) * 0.42))
        preview_text = preview_metrics.elidedText(
            preview, Qt.TextElideMode.ElideRight, max_preview_width
        )
        preview_width = preview_metrics.horizontalAdvance(preview_text)
        preview_x = right_edge - preview_width

        title_width = max(40, preview_x - text_x - round(14 * theme.scale))
        title_text = title_metrics.elidedText(
            snippet.title, Qt.TextElideMode.ElideRight, title_width
        )
        title_baseline = row.top() + round(25 * theme.scale)
        painter.drawText(text_x, title_baseline, title_text)

        painter.setFont(preview_font)
        painter.setPen(QColor(theme.math if selected else theme.muted))
        preview_baseline = title_baseline - (
            preview_metrics.ascent() - title_metrics.ascent()
        )
        painter.drawText(preview_x, preview_baseline, preview_text)

        latex_font = theme.mono_font(11.4)
        latex_metrics = QFontMetrics(latex_font)
        painter.setFont(latex_font)
        painter.setPen(QColor(theme.muted if selected else theme.faint))
        latex_width = right_edge - text_x
        latex_text = latex_metrics.elidedText(
            snippet.latex, Qt.TextElideMode.ElideRight, latex_width
        )
        painter.drawText(
            text_x,
            row.top() + round(46 * theme.scale),
            latex_text,
        )
        painter.restore()

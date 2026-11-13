"""Horizontally scrollable category chips."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QToolButton,
    QWidget,
)

from ..models import Category
from ..theme import Theme

RECENT_ID = "__recent__"


class _ChipScrollArea(QScrollArea):
    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y() or event.angleDelta().x()
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - delta)
        event.accept()


class CategoryBar(QWidget):
    category_changed = pyqtSignal(object)  # str or None for "All"

    def __init__(
        self,
        theme: Theme,
        categories: list[Category],
        counts: dict[str, int],
        recent_count: int = 0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.theme = theme
        self.setFixedHeight(round(40 * theme.scale))
        self._buttons: dict[str | None, QPushButton] = {}
        self._order: list[str | None] = []
        self._current: str | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll = _ChipScrollArea(self)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setWidgetResizable(False)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.nav_left = QToolButton(self)
        self.nav_left.setObjectName("ChipNav")
        self.nav_left.setText("‹")
        self.nav_left.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.nav_left.setCursor(Qt.CursorShape.PointingHandCursor)
        self.nav_left.setFixedWidth(round(22 * theme.scale))
        self.nav_left.clicked.connect(lambda: self._scroll_by(-240))
        outer.addWidget(self.nav_left)
        outer.addWidget(self.scroll, 1)
        self.nav_right = QToolButton(self)
        self.nav_right.setObjectName("ChipNav")
        self.nav_right.setText("›")
        self.nav_right.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.nav_right.setCursor(Qt.CursorShape.PointingHandCursor)
        self.nav_right.setFixedWidth(round(22 * theme.scale))
        self.nav_right.clicked.connect(lambda: self._scroll_by(240))
        outer.addWidget(self.nav_right)

        self.container = QWidget()
        self.container.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.layout = QHBoxLayout(self.container)
        self.layout.setContentsMargins(2, 2, 2, 2)
        self.layout.setSpacing(round(6 * theme.scale))
        self.layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.scroll.setWidget(self.container)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)

        self._add_chip(None, "✦  All", "Every expression in the library", sum(counts.values()))
        if recent_count:
            self._add_chip(RECENT_ID, "↺  Recent", "Recently copied expressions", recent_count)
        for category in categories:
            count = counts.get(category.id, 0)
            self._add_chip(
                category.id,
                f"{category.symbol}  {category.name}",
                category.description,
                count,
            )
        self.container.adjustSize()
        self.scroll.horizontalScrollBar().valueChanged.connect(self._update_nav)
        self.scroll.horizontalScrollBar().rangeChanged.connect(self._update_nav)
        QTimer.singleShot(0, self._update_nav)
        self.set_current(None, emit=False)

    def _add_chip(self, category_id: str | None, label: str, tooltip: str, count: int) -> None:
        button = QPushButton(label, self.container)
        button.setObjectName("CategoryChip")
        button.setText(label.replace("&", "&&"))
        button.setCheckable(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(f"{tooltip}\n{count} expression{'s' if count != 1 else ''}")
        button.setProperty("categoryId", category_id)
        button.clicked.connect(lambda _checked=False, cid=category_id: self._on_chip(cid))
        self.layout.addWidget(button)
        self.group.addButton(button)
        self._buttons[category_id] = button
        self._order.append(category_id)
        self.container.adjustSize()

    def _on_chip(self, category_id: str | None) -> None:
        if category_id == self._current:
            return
        self._current = category_id
        self._scroll_to(category_id)
        self.category_changed.emit(category_id)

    def _scroll_by(self, distance: int) -> None:
        bar = self.scroll.horizontalScrollBar()
        bar.setValue(bar.value() + round(distance * self.theme.scale))

    def _update_nav(self, *_args) -> None:
        bar = self.scroll.horizontalScrollBar()
        self.nav_left.setVisible(bar.value() > 0)
        self.nav_right.setVisible(bar.value() < bar.maximum())

    def _scroll_to(self, category_id: str | None) -> None:
        button = self._buttons.get(category_id)
        if button is not None:
            self.scroll.ensureWidgetVisible(button, round(24 * self.theme.scale), 0)
            self._update_nav()

    def set_current(self, category_id: str | None, *, emit: bool = False) -> None:
        if category_id not in self._buttons:
            category_id = None
        self._current = category_id
        button = self._buttons.get(category_id)
        if button is not None:
            button.setChecked(True)
            self._scroll_to(category_id)
        if emit:
            self.category_changed.emit(category_id)

    def cycle(self, delta: int) -> None:
        if not self._order:
            return
        try:
            index = self._order.index(self._current)
        except ValueError:
            index = 0
        index = (index + delta) % len(self._order)
        self.set_current(self._order[index], emit=True)

    @property
    def current(self) -> str | None:
        return self._current

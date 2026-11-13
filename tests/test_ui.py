"""Offscreen UI smoke tests: filtering, selection and copy flow."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from latex_picker.clipboard import CopyResult
from latex_picker.config import AppConfig, State
from latex_picker.environment import SessionInfo
from latex_picker.library import load_library
from latex_picker.preview import MathPreviewService
from latex_picker.search import SearchEngine
from latex_picker.theme import resolve_theme
from latex_picker.ui.window import LatexPickerWindow


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.library, _ = load_library()
        cls.engine = SearchEngine(cls.library)
        cls.session = SessionInfo(
            session_type="wayland",
            desktop="Hyprland",
            compositor="Hyprland",
            is_wayland=True,
            is_x11=False,
            is_hyprland=True,
        )

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {"XDG_STATE_HOME": self.temp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.window = self.make_window(
            state=State(recent=["op-nabla", "frac-basic"])
        )

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def make_window(self, state: State | None = None, **overrides) -> LatexPickerWindow:
        config = AppConfig(show_preview=False, preview_renderer="unicode")
        for key, value in overrides.items():
            setattr(config, key, value)
        return LatexPickerWindow(
            library=self.library,
            engine=self.engine,
            config=config.normalised(),
            theme=resolve_theme("dark", 1.0),
            state=state or State(),
            session=self.session,
            preview_service=MathPreviewService(enabled=False),
        )

    def test_initial_view_lists_all_snippets(self) -> None:
        self.assertEqual(self.window.model.rowCount(), 266)
        self.assertEqual(self.window.count_label.text(), "266 expressions")

    def test_search_filters_model(self) -> None:
        self.window.search_box.line_edit.setText("partial derivative")
        self.assertGreater(self.window.model.rowCount(), 0)
        self.assertLess(self.window.model.rowCount(), 266)
        self.assertTrue(self.window.count_label.text().endswith("of 266"))
        first = self.window.model.snippet(self.window.model.index(0, 0))
        self.assertIn("partial", first.title.casefold())

    def test_no_match_shows_empty_state(self) -> None:
        self.window.search_box.line_edit.setText("qqqqzzzz")
        self.assertEqual(self.window.model.rowCount(), 0)
        self.assertEqual(self.window.stack.currentWidget(), self.window.empty_widget)
        self.assertIn("No matching", self.window.empty_title.text())

    def test_enter_copy_uses_latex_and_records_recent(self) -> None:
        copied: list[str] = []

        def fake_copy(text, qt_setter=None):
            copied.append(text)
            return CopyResult(True, "wl-copy")

        self.window.search_box.line_edit.setText("Fraction")
        with patch("latex_picker.ui.window.copy_to_clipboard", side_effect=fake_copy):
            self.window._copy_current()

        self.assertEqual(copied, ["\\frac{<numerator>}{<denominator>}"])
        self.assertEqual(self.window.state.recent[0], "frac-basic")

    def test_copy_error_keeps_window_and_shows_message(self) -> None:
        self.window.search_box.line_edit.setText("Fraction")
        with patch(
            "latex_picker.ui.window.copy_to_clipboard",
            return_value=CopyResult(False, "wl-copy", "no display"),
        ):
            self.window._copy_current()
        self.assertIn("Could not copy", self.window.status_label.text())

    def test_category_filter_changes_results(self) -> None:
        self.window.category_bar.set_current("greek", emit=True)
        self.assertEqual(self.window.model.rowCount(), 41)
        self.assertEqual(self.window.count_label.text(), "41 of 266")

    def test_recent_category_uses_state_order(self) -> None:
        self.window.category_bar.set_current("__recent__", emit=True)
        self.assertEqual(self.window.model.rowCount(), 2)
        first = self.window.model.snippet(self.window.model.index(0, 0))
        self.assertEqual(first.id, "op-nabla")


if __name__ == "__main__":
    unittest.main()

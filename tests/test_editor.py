"""Tests for the LaTeX editor tab and its palettes."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent, QTextCursor
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication

from latex_picker.clipboard import CopyResult
from latex_picker.library import load_library
from latex_picker.theme import resolve_theme
from latex_picker.workspace import palettes
from latex_picker.workspace.editor_tab import (
    EditorTab,
    brace_problem,
    fill_template,
    library_to_editor,
    save_snippet,
    strip_placeholders,
    wrap_output,
)

PH = palettes.PH


def balanced(text: str) -> bool:
    depth = 0
    i = 0
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0


class PaletteTests(unittest.TestCase):
    def test_every_button_is_well_formed(self) -> None:
        buttons = palettes.all_buttons()
        self.assertGreater(len(buttons), 350)
        for button in buttons:
            self.assertTrue(button.label.strip(), button)
            self.assertTrue(button.name.strip(), button)
            if button.kind == "builder":
                continue
            self.assertTrue(button.latex, button)
            self.assertTrue(balanced(button.latex), button.latex)
            self.assertEqual(brace_problem(button.latex), "", button.latex)

    def test_category_ids_unique(self) -> None:
        ids = [c.id for c in palettes.CATEGORIES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_search(self) -> None:
        names = [b.name for b in palettes.search("integral")]
        self.assertIn("definite integral", names)
        self.assertEqual(palettes.search(""), [])
        self.assertTrue(palettes.search("theta"))

    def test_template_for_command(self) -> None:
        self.assertEqual(palettes.template_for_command(r"\frac"), r"\frac{⬚}{⬚}")
        self.assertEqual(palettes.template_for_command(r"\sqrt"), r"\sqrt{⬚}")
        self.assertTrue(palettes.template_for_command(r"\alpha").startswith(r"\alpha"))

    def test_build_matrix(self) -> None:
        self.assertEqual(palettes.build_matrix(2, 2, "pmatrix", "identity"),
                         r"\begin{pmatrix} 1 & 0 \\ 0 & 1 \end{pmatrix}")
        augmented = palettes.build_matrix(2, 3, "augmented", "zeros")
        self.assertIn("{cc|c}", augmented)
        self.assertIn("a_{12}", palettes.build_matrix(2, 2, "bmatrix", "a_ij entries"))


class HelperTests(unittest.TestCase):
    def test_wrap_formats(self) -> None:
        self.assertEqual(wrap_output("x^2", "raw"), "x^2")
        self.assertEqual(wrap_output("x^2", "inline"), "$x^2$")
        self.assertEqual(wrap_output("x^2", "display"), "$$x^2$$")
        self.assertEqual(wrap_output("x^2", "bracket"), "\\[x^2\\]")
        self.assertEqual(wrap_output("x^2", "equation"),
                         "\\begin{equation}\nx^2\n\\end{equation}")

    def test_strip_and_fill(self) -> None:
        self.assertEqual(strip_placeholders(r"\frac{1}{⬚}"), (r"\frac{1}{}", 1))
        self.assertEqual(fill_template(r"\sqrt{⬚}", "x+1"), r"\sqrt{x+1}")
        self.assertEqual(fill_template(r"\frac{⬚}{⬚}", "a"), r"\frac{a}{⬚}")
        self.assertEqual(library_to_editor(r"\frac{<numerator>}{<denominator>}"),
                         r"\frac{⬚}{⬚}")
        self.assertEqual(library_to_editor("a < b > c"), "a < b > c")

    def test_brace_problem(self) -> None:
        self.assertEqual(brace_problem(r"\frac{a}{b}"), "")
        self.assertIn("not closed", brace_problem(r"\frac{a}{b"))
        self.assertIn("extra", brace_problem("a}"))
        self.assertIn("\\end", brace_problem(r"\begin{pmatrix} 1"))
        self.assertIn("\\right", brace_problem(r"\left( x"))
        self.assertEqual(brace_problem(r"\{ x \}"), "")


class EditorTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.theme = resolve_theme("dark", 1.0)

    def setUp(self) -> None:
        self.tab = EditorTab(self.theme)
        self.tab.resize(1100, 640)
        self.statuses: list[str] = []
        self.tab.status.connect(self.statuses.append)

    def tearDown(self) -> None:
        self.tab.deleteLater()
        self.app.processEvents()

    def selected(self) -> str:
        return self.tab.source.textCursor().selectedText()

    def test_insert_template_selects_first_placeholder(self) -> None:
        self.tab.insert_template(r"\frac{⬚}{⬚}")
        self.assertEqual(self.tab.text(), r"\frac{⬚}{⬚}")
        cursor = self.tab.source.textCursor()
        self.assertEqual(self.selected(), PH)
        self.assertEqual(cursor.selectionStart(), 6)
        # Typing replaces the placeholder; Tab moves to the next one.
        self.tab.source.insertPlainText("1")
        self.assertTrue(self.tab.jump_placeholder(1))
        self.tab.source.insertPlainText("2")
        self.assertEqual(self.tab.text(), r"\frac{1}{2}")
        self.assertFalse(self.tab.jump_placeholder(1))

    def test_selection_fills_template(self) -> None:
        self.tab.set_text("x+1")
        cursor = self.tab.source.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        self.tab.source.setTextCursor(cursor)
        self.tab.insert_template(r"\sqrt{⬚}")
        self.assertEqual(self.tab.text(), r"\sqrt{x+1}")
        self.tab.set_text("a")
        cursor = self.tab.source.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        self.tab.source.setTextCursor(cursor)
        self.tab.insert_template(r"\frac{⬚}{⬚}")
        self.assertEqual(self.tab.text(), r"\frac{a}{⬚}")
        self.assertEqual(self.selected(), PH)

    def test_tab_key_navigation(self) -> None:
        self.tab.insert_template(r"\int_{⬚}^{⬚} ⬚")
        positions = []
        for _ in range(3):
            positions.append(self.tab.source.textCursor().selectionStart())
            event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier)
            self.tab.source.keyPressEvent(event)
        self.assertEqual(len(set(positions)), 3)
        # Wraps around to the first placeholder.
        self.assertEqual(self.tab.source.textCursor().selectionStart(), positions[0])
        back = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
        self.tab.source.keyPressEvent(back)
        self.assertEqual(self.tab.source.textCursor().selectionStart(), positions[2])

    def test_auto_close_braces(self) -> None:
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_BraceLeft,
                          Qt.KeyboardModifier.NoModifier, "{")
        self.tab.source.keyPressEvent(event)
        self.assertEqual(self.tab.text(), "{}")
        self.assertEqual(self.tab.source.textCursor().position(), 1)
        close = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_BraceRight,
                          Qt.KeyboardModifier.NoModifier, "}")
        self.tab.source.keyPressEvent(close)
        self.assertEqual(self.tab.text(), "{}")

    def test_insert_latex_text_converts_placeholders(self) -> None:
        self.tab.insert_latex_text(r"\frac{<numerator>}{<denominator>}")
        self.assertEqual(self.tab.text(), r"\frac{⬚}{⬚}")
        self.assertEqual(self.selected(), PH)

    def test_palette_button_press(self) -> None:
        sqrt = next(b for b in palettes.STRUCTURES if b.name == "square root")
        self.tab.press(sqrt)
        self.tab.source.insertPlainText("2")
        self.assertEqual(self.tab.text(), r"\sqrt{2}")

    def test_copy_formats_and_placeholder_stripping(self) -> None:
        copied: list[str] = []

        def fake(text, qt_setter=None):
            copied.append(text)
            return CopyResult(True, "wl-copy")

        self.tab.set_text(r"\frac{1}{⬚}")
        index = self.tab.format_combo.findData("inline")
        self.tab.format_combo.setCurrentIndex(index)
        with patch("latex_picker.workspace.widgets.copy_to_clipboard", side_effect=fake):
            self.assertTrue(self.tab.copy_latex())
        self.assertEqual(copied, [r"$\frac{1}{}$"])
        self.assertIn("removed 1 empty placeholder", self.statuses[-1])
        self.assertEqual(self.tab.history[0], r"\frac{1}{}")

    def test_copy_empty_does_nothing(self) -> None:
        with patch("latex_picker.workspace.widgets.copy_to_clipboard") as fake:
            self.assertFalse(self.tab.copy_latex())
        fake.assert_not_called()

    def test_png_export(self) -> None:
        self.tab.set_text(r"x^2 + \frac{1}{2}")
        png = self.tab._image_png()
        self.assertTrue(png.startswith(b"\x89PNG"))

    def test_favorites_and_history(self) -> None:
        self.tab.set_text("a+b")
        self.tab.toggle_favorite()
        self.assertEqual(self.tab.favorites, ["a+b"])
        self.assertEqual(self.tab.star_button.text(), "★")
        self.tab.toggle_favorite()
        self.assertEqual(self.tab.favorites, [])
        for i in range(60):
            self.tab._remember(f"x_{i}")
        self.assertEqual(len(self.tab.history), 50)
        self.assertEqual(self.tab.history[0], "x_59")

    def test_matrix_builder_inserts(self) -> None:
        self.tab.mb_rows.setValue(2)
        self.tab.mb_cols.setValue(2)
        self.tab.mb_env.setCurrentText("pmatrix")
        self.tab.mb_fill.setCurrentText("identity")
        self.tab._insert_built_matrix()
        self.assertEqual(self.tab.text(), r"\begin{pmatrix} 1 & 0 \\ 0 & 1 \end{pmatrix}")

    def test_send_signals(self) -> None:
        calc: list[str] = []
        graph: list[str] = []
        self.tab.send_to_calculator.connect(calc.append)
        self.tab.send_to_graph.connect(graph.append)
        self.tab.set_text(r"\frac{1}{2}")
        self.tab.evaluate()
        self.tab.plot()
        self.assertEqual(calc, [r"\frac{1}{2}"])
        self.assertEqual(graph, [r"\frac{1}{2}"])

    def test_state_round_trip(self) -> None:
        self.tab.set_text(r"e^{i\pi}")
        self.tab.format_combo.setCurrentIndex(self.tab.format_combo.findData("display"))
        self.tab._remember("y=mx+b")
        self.tab.favorites = ["a^2+b^2=c^2"]
        self.tab._show_category("greek")
        self.tab.zoom(2)
        state = json.loads(json.dumps(self.tab.state()))
        other = EditorTab(self.theme)
        other.restore(state)
        self.assertEqual(other.text(), r"e^{i\pi}")
        self.assertEqual(other.format_key, "display")
        self.assertEqual(other.history, ["y=mx+b"])
        self.assertEqual(other.favorites, ["a^2+b^2=c^2"])
        self.assertEqual(other.current_category, "greek")
        self.assertEqual(other.font_px, 17)
        other.restore({"text": 5, "history": "bad", "format": None})  # tolerated
        other.deleteLater()


class SnippetTests(unittest.TestCase):
    def test_save_snippet_is_loadable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": temp}):
                first = save_snippet("Quadratic formula",
                                     r"x = \frac{-b \pm \sqrt{b^2-4ac}}{2a}")
                second = save_snippet("Quadratic formula", r"\frac{⬚}{⬚}")
                path = Path(temp) / "latex-picker" / "snippets.json"
                self.assertTrue(path.exists())
                library, warnings = load_library(path)
                self.assertNotEqual(first, second)
                snippet = library.snippet(second)
                self.assertIsNotNone(snippet)
                self.assertEqual(snippet.latex, r"\frac{<arg1>}{<arg2>}")
                self.assertEqual(snippet.category, "custom")
                self.assertIsNotNone(library.snippet(first))
                self.assertTrue(any("custom snippet" in w for w in warnings))

    def test_save_snippet_merges_list_file_and_refuses_bad_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "snippets.json"
            path.write_text(json.dumps([{"id": "mine", "category": "greek",
                                         "title": "Mine", "latex": r"\alpha"}]))
            save_snippet("New", "x^2", path)
            data = json.loads(path.read_text())
            self.assertEqual([s["id"] for s in data["snippets"]], ["mine", "custom-new"])
            library, _ = load_library(path)
            self.assertIsNotNone(library.snippet("mine"))
            path.write_text("{ not json")
            with self.assertRaises(ValueError):
                save_snippet("X", "y", path)
            self.assertEqual(path.read_text(), "{ not json")
            with self.assertRaises(ValueError):
                save_snippet("", "y", path)


if __name__ == "__main__":
    unittest.main()

"""Tests for the workspace LaTeX renderer (composite mathtext + native environments)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication

from latex_picker.workspace import render


def _ink_rows(image: QImage) -> int:
    """Number of rows containing at least one non-transparent pixel."""
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    rows = 0
    for y in range(image.height()):
        for x in range(0, image.width(), 2):
            if QColor(image.pixel(x, y)).alpha() > 40:
                rows += 1
                break
    return rows


class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def assertRendersCleanly(self, latex: str) -> QImage:  # noqa: N802
        self.assertEqual(render.render_error(latex), "", latex)
        image = render.render_image(latex, "#000000", 22)
        self.assertFalse(image.isNull())
        self.assertGreater(image.width(), 5)
        return image

    def test_simple_expression(self) -> None:
        self.assertRendersCleanly(r"\frac{a}{b} + \sqrt{x}")

    def test_each_matrix_environment(self) -> None:
        single_line = render.render_image("x", "#000000", 22)
        for env in ("matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix",
                    "smallmatrix"):
            with self.subTest(env=env):
                image = self.assertRendersCleanly(
                    rf"\begin{{{env}}}1 & 2 \\ 3 & 4\end{{{env}}}")
                self.assertGreater(image.height(), single_line.height() * 1.3)

    def test_delimiters_widen_the_matrix(self) -> None:
        plain = render.render_image(r"\begin{matrix}1&2\\3&4\end{matrix}", "#000", 22)
        paren = render.render_image(r"\begin{pmatrix}1&2\\3&4\end{pmatrix}", "#000", 22)
        self.assertGreater(paren.width(), plain.width())

    def test_nested_environment(self) -> None:
        nested = self.assertRendersCleanly(
            r"\begin{bmatrix}1 & \begin{pmatrix}a&b\\c&d\end{pmatrix}\\ 0 & 1\end{bmatrix}")
        flat = render.render_image(r"\begin{bmatrix}1&x\\0&1\end{bmatrix}", "#000", 22)
        self.assertGreater(nested.height(), flat.height())

    def test_array_with_vertical_line_and_hline(self) -> None:
        self.assertRendersCleanly(
            r"\left[\begin{array}{cc|c}1&2&3\\4&5&6\\ \hline 7&8&9\end{array}\right]")

    def test_cases(self) -> None:
        self.assertRendersCleanly(
            r"f(x) = \begin{cases} x^2 & \text{if } x \ge 0 \\ -x & \text{otherwise}\end{cases}")

    def test_aligned(self) -> None:
        self.assertRendersCleanly(
            r"\begin{aligned} a &= b + c \\ &\le d \end{aligned}")

    def test_top_level_multiline(self) -> None:
        one = render.render_image("x + y = 3", "#000", 22)
        two = self.assertRendersCleanly(r"x + y = 3 \\ x - y = 1")
        self.assertGreater(_ink_rows(two), _ink_rows(one) * 1.5)
        self.assertRendersCleanly(r"a &= 1 \\ b &= 2")

    def test_superscript_after_matrix(self) -> None:
        self.assertRendersCleanly(r"\begin{pmatrix}1&2\\3&4\end{pmatrix}^{-1}")

    def test_placeholders_render(self) -> None:
        self.assertRendersCleanly(r"\frac{⬚}{⬚} + \sqrt{⬚}")

    def test_unsupported_mathtext_commands_are_substituted(self) -> None:
        for latex in (r"\boxed{x}", r"\cancel{x}", r"\xrightarrow{R_1} y",
                      r"\overbrace{x+y}", r"\underbrace{x+y}_{n}", r"a \implies b",
                      r"\operatorname*{argmax}_x f", r"\lvert x \rvert", r"\tfrac{1}{2}",
                      r"\displaystyle\sum_{n=1}^\infty", r"\int\limits_a^b", r"x \bmod 3",
                      r"a \pmod{n}", r"\square", r"\dotsc", r"\hdots", r"\textbf{v}",
                      r"\le \ge"):
            with self.subTest(latex=latex):
                self.assertEqual(render.render_error(latex), "")

    def test_render_error_reports_problems(self) -> None:
        self.assertIn("brace", render.render_error(r"\frac{1}{2").lower())
        self.assertIn("\\foo", render.render_error(r"\foo x"))
        self.assertIn("right", render.render_error(r"\left( x").lower())
        self.assertNotEqual(render.render_error(r"\begin{pmatrix}1"), "")
        self.assertNotEqual(render.render_error("x^"), "")
        self.assertEqual(render.render_error(""), "")

    def test_bad_input_still_produces_an_image(self) -> None:
        for latex in (r"\foo{", r"\begin{weird}a\end{weird}", "}{", "&&&"):
            with self.subTest(latex=latex):
                image = render.render_image(latex, "#000", 22)
                self.assertFalse(image.isNull())

    def test_render_png_returns_png_bytes(self) -> None:
        data = render.render_png(r"e^{i\pi} + 1 = 0", "#000000", 22)
        self.assertTrue(data.startswith(b"\x89PNG"))
        with_bg = render.render_png(r"\begin{pmatrix}1\end{pmatrix}", "#000", 22,
                                    background="#ffffff")
        self.assertTrue(with_bg.startswith(b"\x89PNG"))

    def test_device_pixel_ratio(self) -> None:
        one = render.render_image("x^2", "#000", 22, 1.0)
        two = render.render_image("x^2", "#000", 22, 2.0)
        self.assertAlmostEqual(two.devicePixelRatio(), 2.0)
        self.assertGreater(two.width(), one.width() * 1.5)

    def test_latex_tier_detection_is_cached_and_boolean(self) -> None:
        first = render.latex_available()
        self.assertIsInstance(first, bool)
        self.assertEqual(first, render.latex_available())


if __name__ == "__main__":
    unittest.main()

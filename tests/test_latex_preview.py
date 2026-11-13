"""Tests for the always-available Unicode preview converter."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from latex_picker.latex_preview import compact_preview, detailed_preview, render_latex


class PreviewTests(unittest.TestCase):
    def test_frac(self) -> None:
        self.assertEqual(render_latex(r"\frac{a}{b}"), "a/b")
        self.assertEqual(compact_preview(r"\frac{<numerator>}{<denominator>}"),
                         "(<numerator>)/(<denominator>)")

    def test_greek_symbols(self) -> None:
        self.assertEqual(render_latex(r"\alpha + \beta"), "α + β")
        self.assertEqual(render_latex(r"\Omega"), "Ω")

    def test_roots_and_scripts(self) -> None:
        self.assertIn("√", render_latex(r"\sqrt{x}"))
        self.assertIn("∑", render_latex(r"\sum_{i=1}^{n} i"))
        self.assertIn("ⁿ", render_latex(r"x^n"))

    def test_math_font_commands(self) -> None:
        self.assertEqual(render_latex(r"\mathbb{R}"), "ℝ")
        self.assertEqual(render_latex(r"\mathcal{L}"), "ℒ")

    def test_matrix_detail_is_multiline(self) -> None:
        latex = r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}"
        compact = compact_preview(latex)
        detail = detailed_preview(latex)
        self.assertIn("a", compact)
        self.assertIn("⎛", detail)
        self.assertIn("\n", detail)
        self.assertNotEqual(compact, detail)

    def test_cases_environment(self) -> None:
        latex = r"\begin{cases} x & x > 0 \\ -x & x \le 0 \end{cases}"
        rendered = detailed_preview(latex)
        self.assertIn("x", rendered)
        self.assertIn("≤", rendered)

    def test_placeholders_are_not_evaluated(self) -> None:
        rendered = render_latex(r"\frac{<a>}{<b>}")
        self.assertIn("<a>", rendered)
        self.assertIn("<b>", rendered)

    def test_unknown_command_does_not_raise(self) -> None:
        self.assertIsInstance(render_latex(r"\notarealcommand{x}"), str)

    def test_empty_input(self) -> None:
        self.assertEqual(render_latex(""), "")


if __name__ == "__main__":
    unittest.main()

"""Tests for the graphing engine and an offscreen GraphTab smoke test."""

from __future__ import annotations

import math
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402

from latex_picker.workspace import plotting  # noqa: E402
from latex_picker.workspace.plotting import classify  # noqa: E402


class ClassifyTests(unittest.TestCase):
    def assertKind(self, text: str, kind: str) -> plotting.PlotSpec:  # noqa: N802
        spec = classify(text)
        self.assertEqual(spec.kind, kind, f"{text!r}: {spec.error}")
        return spec

    def test_explicit_forms(self) -> None:
        self.assertKind("x^2", "explicit")
        self.assertKind("y = sin(x)", "explicit")
        spec = self.assertKind("f(x) = x^3 - x", "explicit")
        self.assertEqual(spec.name, "f")
        self.assertTrue(spec.latex.startswith("f(x) ="))

    def test_other_kinds(self) -> None:
        self.assertKind("x = y^2", "explicit_y")
        self.assertKind("x = 3", "vline")
        self.assertKind("x^2 + y^2 = 4", "implicit")
        self.assertKind("x y = 1", "implicit")
        self.assertKind("r = 1 + cos(theta)", "polar")
        self.assertKind("r = θ", "polar")
        self.assertKind("(1, 2)", "points")
        spec = self.assertKind("(1, 2), (3, 4)", "points")
        self.assertEqual(spec.points, [(1.0, 2.0), (3.0, 4.0)])

    def test_parametric_with_range(self) -> None:
        spec = self.assertKind("(cos t, sin t)", "parametric")
        self.assertAlmostEqual(spec.t_range[1], 2 * math.pi)
        spec = self.assertKind("(cos t, sin t); t = 0..pi", "parametric")
        self.assertAlmostEqual(spec.t_range[1], math.pi)

    def test_inequalities(self) -> None:
        spec = self.assertKind("y > x^2", "inequality")
        self.assertEqual(spec.op, ">")
        self.assertIsNotNone(spec.boundary)
        spec = self.assertKind("x^2 + y^2 <= 4", "inequality")
        self.assertEqual(spec.op, "<=")
        self.assertIsNone(spec.boundary)
        spec = self.assertKind("x^2 < y", "inequality")
        self.assertEqual(spec.op, ">")  # flipped so it reads y > x^2

    def test_errors_and_empty(self) -> None:
        self.assertKind("", "empty")
        spec = self.assertKind("sin(", "error")
        self.assertTrue(spec.error)

    def test_slider_detection(self) -> None:
        self.assertEqual(classify("y = a sin(b x) + c").params, ["a", "b", "c"])
        self.assertEqual(classify("(k cos t, sin t)").params, ["k"])
        self.assertEqual(classify("r = a theta").params, ["a"])
        self.assertEqual(classify("e^x + pi").params, [])


class SamplingTests(unittest.TestCase):
    def test_tan_breaks_at_every_pole(self) -> None:
        spec = classify("tan(x)")
        xs, ys = plotting.sample_explicit(spec, {}, -5, 5, -10, 10)
        self.assertEqual(int(np.isnan(ys).sum()), 4)

    def test_continuous_steep_curve_not_broken(self) -> None:
        for text in ("100 x^3", "floor(x)"):
            xs, ys = plotting.sample_explicit(classify(text), {}, -5, 5, -10, 10)
            self.assertEqual(int(np.isnan(ys).sum()), 0, text)

    def test_sqrt_domain_masked(self) -> None:
        xs, ys = plotting.sample_explicit(classify("sqrt(x)"), {}, -5, 5, -5, 5)
        self.assertTrue(np.isnan(ys[xs < -0.01]).all())
        self.assertTrue(np.isfinite(ys[xs > 0.01]).all())

    def test_parameters_are_used(self) -> None:
        spec = classify("a x")
        _xs, ys = plotting.sample_explicit(spec, {"a": 3}, 1, 1, -5, 5, n=1)
        self.assertAlmostEqual(float(ys[0]), 3.0)

    def test_polar_and_parametric(self) -> None:
        xs, ys = plotting.sample_parametric(classify("r = 2"), {})
        self.assertTrue(np.allclose(np.hypot(xs, ys), 2))
        xs, ys = plotting.sample_parametric(classify("(cos t, sin t)"), {})
        self.assertTrue(np.allclose(xs ** 2 + ys ** 2, 1))

    def test_inequality_mask(self) -> None:
        spec = classify("x^2 + y^2 < 1")
        gx, gy, gz = plotting.sample_grid(spec, {}, -2, 2, -2, 2, 41)
        mask = plotting.inequality_mask(spec, gz)
        self.assertTrue(mask[20, 20])
        self.assertFalse(mask[0, 0])


class AnalysisTests(unittest.TestCase):
    def test_roots(self) -> None:
        func = plotting.make_function(classify("x^3 - x"))
        self.assertEqual([round(r, 9) for r in plotting.find_roots(func, -3, 3)],
                         [-1.0, 0.0, 1.0])

    def test_touching_root(self) -> None:
        func = plotting.make_function(classify("(x - 1)^2"))
        roots = plotting.find_roots(func, -3, 3)
        self.assertEqual(len(roots), 1)
        self.assertAlmostEqual(roots[0], 1.0, places=5)

    def test_poles_are_not_roots(self) -> None:
        func = plotting.make_function(classify("tan(x)"))
        roots = plotting.find_roots(func, -3, 3)
        self.assertEqual(len(roots), 1)
        self.assertAlmostEqual(roots[0], 0.0, places=9)

    def test_extrema(self) -> None:
        extrema = plotting.find_extrema(classify("x^3 - 3x"), {}, -3, 3)
        self.assertEqual([(round(x, 6), round(y, 6), k) for x, y, k in extrema],
                         [(-1.0, 2.0, "max"), (1.0, -2.0, "min")])

    def test_intersections(self) -> None:
        points = plotting.find_intersections(classify("x^2"), classify("x + 2"), {}, -5, 5)
        self.assertEqual([(round(x, 9), round(y, 9)) for x, y in points],
                         [(-1.0, 1.0), (2.0, 4.0)])

    def test_integral_and_intercept(self) -> None:
        value, _err = plotting.definite_integral(classify("x^2"), {}, 0, 3)
        self.assertAlmostEqual(value, 9.0, places=9)
        value, _err = plotting.definite_integral(classify("sin(x)"), {}, 0, math.pi)
        self.assertAlmostEqual(value, 2.0, places=9)
        self.assertAlmostEqual(plotting.y_intercept(classify("x^2 + 5"), {}), 5.0)
        self.assertIsNone(plotting.y_intercept(classify("1/x"), {}))

    def test_derivative_tangent_table(self) -> None:
        deriv = plotting.derivative_spec(classify("x^3"))
        self.assertAlmostEqual(float(plotting.make_function(deriv)(np.array([2.0]))[0]), 12.0)
        slope, intercept, latex = plotting.tangent_line(classify("x^2"), {}, 1)
        self.assertEqual((slope, intercept), (2.0, -1.0))
        self.assertEqual(latex, "y = 2x - 1")
        table = plotting.value_table(classify("1/x"), {}, -1, 1, 3)
        self.assertEqual(table, [(-1.0, -1.0), (0.0, None), (1.0, 1.0)])


class PgfTests(unittest.TestCase):
    def test_to_pgf(self) -> None:
        self.assertEqual(plotting.to_pgf(classify("sin(x)/x").expr), "sin(x)/x")
        self.assertEqual(plotting.to_pgf(classify("sqrt(x) + e^x").expr), "sqrt(x) + exp(x)")
        self.assertEqual(plotting.to_pgf(classify("ln(x)").expr), "ln(x)")

    def test_pgfplots_code(self) -> None:
        items = [(classify("sin(a x)"), "#ff0000"), (classify("x^2 + y^2 = 4"), "#00ff00"),
                 (classify("(1, 2)"), "#0000ff"), (classify("r = 1"), "#123456")]
        code = plotting.pgfplots_code(items, {"a": 2}, (-5, 5, -3, 3))
        self.assertIn("\\begin{tikzpicture}", code)
        self.assertIn("trig format plots=rad", code)
        self.assertIn("\\addplot[thick, color=plotc1, domain=-5:5] {sin(2*x)};", code)
        self.assertIn("color=plotc2] coordinates {", code)
        self.assertIn("\\addplot[only marks, mark=*, color=plotc3] coordinates {(1,2)};", code)
        self.assertIn("\\definecolor{plotc4}{HTML}{123456}", code)
        self.assertTrue(code.rstrip().endswith("\\end{tikzpicture}"))


class GraphTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def make_tab(self):
        from latex_picker.theme import resolve_theme
        from latex_picker.workspace.graph_tab import GraphTab

        tab = GraphTab(resolve_theme("dark", 1.0))
        tab.resize(1150, 680)
        self.addCleanup(tab.deleteLater)
        return tab

    def test_smoke_and_state_round_trip(self) -> None:
        tab = self.make_tab()
        messages: list[str] = []
        tab.status.connect(messages.append)
        for text in ["x^2", "sin(a x)", "x^2+y^2=4", "r=1+cos(theta)", "(cos t, sin t)",
                     "y > x^2"]:
            tab.add_expression(text)
        tab.show()
        self.app.processEvents()
        self.assertEqual([row.spec.kind for row in tab.rows],
                         ["explicit", "explicit", "implicit", "polar", "parametric",
                          "inequality"])
        self.assertEqual(list(tab.slider_rows), ["a"])
        self.assertEqual(tab.f_combo.count(), 2)
        self.assertNotEqual(tab.f_combo.currentData(), tab.g_combo.currentData())

        tab.analyze_roots()
        self.assertEqual(len(tab.marks), 1)
        tab.analyze_intersections()
        self.assertTrue(tab.marks)
        tab.int_a.setText("0")
        tab.int_b.setText("3")
        tab.analyze_integral()
        self.assertIsNotNone(tab.integral)
        tab.analyze_tangent()
        tab.analyze_table()
        tab.derivative_check.setChecked(True)
        self.assertTrue(tab.figure_png(dpi=50).startswith(b"\x89PNG"))
        self.assertIn("\\begin{axis}", tab.pgfplots())

        inserted: list[str] = []
        tab.insert_latex.connect(inserted.append)
        tab.active_row = tab.rows[0]
        tab.insert_selected()
        self.assertEqual(inserted, ["y = x^{2}"])

        tab.slider_rows["a"].set_value(2.5)
        tab.view = [-3.0, 3.0, -2.0, 2.0]
        state = tab.state()
        other = self.make_tab()
        other.restore(state)
        self.assertEqual([row.text() for row in other.rows],
                         [row.text() for row in tab.rows])
        self.assertEqual([row.color for row in other.rows], [row.color for row in tab.rows])
        self.assertEqual(other.slider_state["a"]["value"], 2.5)
        self.assertEqual(other.view, [-3.0, 3.0, -2.0, 2.0])
        self.assertTrue(other.derivative_check.isChecked())

    def test_add_expression_reuses_empty_row_and_reports_errors(self) -> None:
        tab = self.make_tab()
        messages: list[str] = []
        tab.status.connect(messages.append)
        self.assertEqual(len(tab.rows), 1)
        tab.add_expression("x^3")
        self.assertEqual(len(tab.rows), 1)
        tab.add_expression("sin(")
        self.assertEqual(len(tab.rows), 2)
        self.assertEqual(tab.rows[1].spec.kind, "error")
        self.assertTrue(messages[-1].startswith("Couldn't plot"))

    def test_restore_ignores_garbage(self) -> None:
        tab = self.make_tab()
        tab.restore({"expressions": "nope", "view": [1, 0, 0, 1], "sliders": {"a": 3}})
        tab.restore(None)  # type: ignore[arg-type]
        self.assertEqual(len(tab.rows), 1)

    def test_view_interactions(self) -> None:
        tab = self.make_tab()
        tab.show()
        self.app.processEvents()
        tab.add_expression("x^2")
        tab.reset_view()
        tab.equal_button.setChecked(True)
        tab._toggle_equal()
        xmin, xmax, ymin, ymax = tab.view
        ratio = tab.canvas.height() / max(1, tab.canvas.width())
        self.assertAlmostEqual((ymax - ymin) / (xmax - xmin), ratio, places=6)
        tab.equal_button.setChecked(False)
        tab.fit_view()
        self.assertLess(tab.view[2], 0.01)
        for edit, value in zip(tab.bound_edits, ["-1", "1", "-2", "pi"]):
            edit.setText(value)
        tab._bounds_typed()
        self.assertAlmostEqual(tab.view[3], math.pi)


if __name__ == "__main__":
    unittest.main()

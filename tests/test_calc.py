"""Calculator: mathcore parsing/CAS and an offscreen CalculatorTab smoke test."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sympy as sp

from latex_picker.workspace import mathcore
from latex_picker.workspace.mathcore import CalcSession, latex_to_python, parse


def value_of(text: str, session: CalcSession | None = None):
    session = session or CalcSession()
    result = session.evaluate(text)
    if not result.ok:
        raise AssertionError(f"{text!r} failed: {result.error}")
    return result


class ParseTests(unittest.TestCase):
    CASES = [
        ("2+3*4", 14),
        ("2^10", 1024),
        ("sqrt(8)", 2 * sp.sqrt(2)),
        ("5!", 120),
        ("|3-7|", 4),
        ("sin(pi/6)", sp.Rational(1, 2)),
        ("ln(e)", 1),
        ("log(1000)", 3),
        ("log(8, 2)", 3),
        ("nCr(5, 2)", 10),
        ("nPr(5, 2)", 20),
        ("mean(1, 2, 3, 4)", sp.Rational(5, 2)),
        ("median(3, 1, 2)", 2),
        ("15% * 200", 30),
        ("√2 × √2", 2),
        ("2pi", 2 * sp.pi),
        ("integrate(x^2, x, 0, 3)", 9),
        ("integrate(x^2, 0, 1)", sp.Rational(1, 3)),
        ("sum(1/n^2, n, 1, oo)", sp.pi ** 2 / 6),
        ("limit(sin(x)/x, x, 0)", 1),
        ("diff(x^3, x, 2)", 6 * sp.Symbol("x")),
        ("gcd(12, 18)", 6),
        ("lcm(4, 6)", 12),
        ("e^(i pi)", -1),
    ]

    def test_values(self) -> None:
        for text, expected in self.CASES:
            with self.subTest(text=text):
                result = value_of(text)
                self.assertEqual(sp.simplify(result.value - expected), 0)

    LATEX_CASES = [
        (r"\frac{1}{2}+\frac{1}{3}", sp.Rational(5, 6)),
        (r"\sqrt{16}", 4),
        (r"\sqrt[3]{27}", 3),
        (r"\sin(\pi/2)", 1),
        (r"\sin\left(\frac{\pi}{2}\right)", 1),
        (r"e^{i\pi}", -1),
        (r"\int_0^1 x^2 \, dx", sp.Rational(1, 3)),
        (r"\int_{0}^{\pi} \sin x \, dx", 2),
        (r"\sum_{n=1}^{10} n", 55),
        (r"\lim_{x \to 0} \frac{\sin x}{x}", 1),
        (r"\log_2 8", 3),
        (r"\ln e", 1),
        (r"\left|-5\right|", 5),
        (r"\binom{5}{2}", 10),
        (r"2 \cdot 3 \times 4", 24),
        (r"\begin{vmatrix}1&2\\3&4\end{vmatrix}", -2),
        (r"$\frac{3}{4}$", sp.Rational(3, 4)),
        (r"\lfloor 3.7 \rfloor", 3),
    ]

    def test_latex_values(self) -> None:
        for text, expected in self.LATEX_CASES:
            with self.subTest(text=text):
                result = value_of(text)
                self.assertEqual(sp.simplify(result.value - expected), 0)

    def test_latex_derivative(self) -> None:
        result = value_of(r"\frac{d}{dx} x^3")
        self.assertEqual(result.value, 3 * sp.Symbol("x") ** 2)

    def test_latex_matrix(self) -> None:
        result = value_of(r"\begin{pmatrix}1&2\\3&4\end{pmatrix}^{-1}")
        self.assertEqual(result.value, sp.Matrix([[-2, 1], [sp.Rational(3, 2), -sp.Rational(1, 2)]]))

    def test_split_top_level_nested_environment(self) -> None:
        body = r"a & \begin{matrix}1&2\\3&4\end{matrix} & {b}"
        self.assertEqual(
            mathcore.split_top_level(body, "&"),
            ["a ", r" \begin{matrix}1&2\\3&4\end{matrix} ", " {b}"],
        )
        rows = mathcore.split_top_level(r"1 & 2 \\ \begin{pmatrix}x\\y\end{pmatrix} & 4", r"\\")
        self.assertEqual(len(rows), 2)

    def test_nested_matrix_translation(self) -> None:
        result = value_of(r"\begin{pmatrix}1&\begin{vmatrix}1&2\\3&4\end{vmatrix}\\3&4\end{pmatrix}")
        self.assertEqual(result.value, sp.Matrix([[1, -2], [3, 4]]))

    def test_latex_to_python_shape(self) -> None:
        self.assertIn("sqrt", latex_to_python(r"\sqrt{x}"))
        self.assertIn("integrate", latex_to_python(r"\int x \, dx"))

    def test_parse_rejects_dunder(self) -> None:
        with self.assertRaises(mathcore.ParseError):
            parse("__import__('os')")

    def test_incomplete_expression_message(self) -> None:
        result = CalcSession().evaluate("sin(")
        self.assertFalse(result.ok)
        self.assertIn("parentheses", result.error)

    def test_implicit_multiplication_and_split_symbols(self) -> None:
        x, y = sp.symbols("x y")
        self.assertEqual(value_of("xy").value, x * y)
        self.assertEqual(value_of("2x(x+1)").value, 2 * x * (x + 1))
        self.assertEqual(value_of("theta^2").value, sp.Symbol("theta") ** 2)


class SessionTests(unittest.TestCase):
    def test_equation(self) -> None:
        result = value_of("x^2 - 5x + 6 = 0")
        self.assertEqual(result.kind, "equation")
        self.assertEqual(sorted(result.value), [2, 3])
        self.assertIn("x = 2", result.result_latex)

    def test_irrational_solutions_have_approximations(self) -> None:
        result = value_of("x^2 = 2")
        self.assertIn("1.41421", result.approx_plain)

    def test_system(self) -> None:
        result = value_of("x + y = 3, x - y = 1")
        x, y = sp.symbols("x y")
        self.assertEqual(result.value, [{x: 2, y: 1}])
        self.assertIn(r"\begin{cases}", result.input_latex)

    def test_inequality(self) -> None:
        result = value_of("x^2 < 4")
        self.assertEqual(result.kind, "inequality")
        self.assertIn("-2", result.result_plain)

    def test_truth_equation(self) -> None:
        self.assertEqual(value_of("2 + 2 = 4").value, True)

    def test_assignment_and_ans(self) -> None:
        session = CalcSession()
        value_of("a = 3", session)
        self.assertEqual(value_of("a^2 + 1", session).value, 10)
        self.assertEqual(value_of("ans * 2", session).value, 20)

    def test_function_definition(self) -> None:
        session = CalcSession()
        result = value_of("f(x) = x^2 + 1", session)
        self.assertEqual(result.kind, "function")
        self.assertEqual(value_of("f(3)", session).value, 10)
        self.assertEqual(value_of("diff(f(x), x)", session).value, 2 * sp.Symbol("x"))

    def test_degree_mode(self) -> None:
        session = CalcSession(angle_mode="deg")
        self.assertEqual(value_of("sin(30)", session).value, sp.Rational(1, 2))
        self.assertEqual(value_of("asin(1/2)", session).value, 30)

    def test_one_sided_limits_reported(self) -> None:
        result = CalcSession().evaluate("limit(1/x, x, 0)")
        # sympy may report zoo for the two-sided limit or raise; both are handled.
        if result.ok:
            self.assertIn("Undefined", result.note)
        else:
            self.assertIn("limit", result.error)

    def test_approx_only_when_meaningful(self) -> None:
        self.assertEqual(value_of("factor(x^2-5x+6)").approx_plain, "")
        self.assertEqual(value_of("diff(x^3 sin x)").approx_plain, "")
        self.assertEqual(value_of("5!").approx_plain, "")
        self.assertTrue(value_of("sqrt(2)").approx_plain.startswith("1.41421"))

    def test_display_latex_is_clean(self) -> None:
        cases = {
            "log(100)": r"\log{\left(100\right)}",
            r"\log_2 8": r"\log_{2}{\left(8\right)}",
            "1/3": r"\frac{1}{3}",
            "-x/2": r"- \frac{x}{2}",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(value_of(text).input_latex, expected)
        limit_latex = value_of("lim(1/x, x, oo)").input_latex
        self.assertNotIn("1 \\frac", limit_latex)
        self.assertNotIn("texttt", value_of("log(100)").input_latex)

    def test_full_latex(self) -> None:
        self.assertEqual(value_of("1/2 + 1/3").full_latex, r"\frac{1}{2} + \frac{1}{3} = \frac{5}{6}")

    def test_preview(self) -> None:
        session = CalcSession()
        self.assertEqual(session.preview("x^2-4=0"), ("x^{2} - 4 = 0", ""))
        latex, error = session.preview("sin(")
        self.assertEqual(latex, "")
        self.assertTrue(error)
        self.assertEqual(session.preview("f(x) = x^2")[0], "f(x) = x^{2}")

    def test_state_round_trip(self) -> None:
        session = CalcSession(angle_mode="deg", digits=8)
        value_of("a = 1/3", session)
        value_of("g(t) = t^2 + a", session)
        restored = CalcSession.from_state(session.to_state())
        self.assertEqual(restored.angle_mode, "deg")
        self.assertEqual(restored.digits, 8)
        self.assertEqual(restored.variables["a"], sp.Rational(1, 3))
        self.assertEqual(value_of("g(2)", restored).value, 4 + sp.Rational(1, 3))

    def test_errors_do_not_raise(self) -> None:
        for text in ["", "(((", "1 +", "foo(", "solve()", "integrate()"]:
            with self.subTest(text=text):
                self.assertFalse(CalcSession().evaluate(text).ok)


class CalculatorTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def make_tab(self):
        from latex_picker.theme import resolve_theme
        from latex_picker.workspace.calc_tab import CalculatorTab

        tab = CalculatorTab(resolve_theme("dark", 1.0))
        tab.synchronous = True
        self.addCleanup(tab.deleteLater)
        return tab

    def test_evaluate_and_history(self) -> None:
        tab = self.make_tab()
        tab.set_input("2x + 3 = 7")
        tab.evaluate_current()
        self.assertEqual(len(tab.entries), 1)
        self.assertTrue(tab.entries[0]["ok"])
        self.assertIn("x = 2", tab.entries[0]["result_latex"])
        self.assertEqual(tab.input.text(), "")
        tab.evaluate_text("1/0 +")
        self.assertFalse(tab.entries[-1]["ok"])

    def test_keypad_insertion(self) -> None:
        tab = self.make_tab()
        tab.insert_text("sin()")
        tab.insert_text("pi")
        self.assertEqual(tab.input.text(), "sin(pi)")
        tab.input.selectAll()
        tab.insert_text("sqrt()")
        self.assertEqual(tab.input.text(), "sqrt(sin(pi))")

    def test_actions(self) -> None:
        tab = self.make_tab()
        self.assertEqual(tab.build_action("diff", "x^3"), "diff(x^3, x)")
        self.assertEqual(tab.build_action("solve", "x^2 = 4"), "solve(Eq(x^2, 4), x)")
        tab.set_input("x^2 - 1")
        tab.apply_action("factor")
        self.assertEqual(tab.entries[-1]["result_plain"], "(x - 1)*(x + 1)")
        tab.apply_action("diff")   # empty input -> applies to ans
        self.assertEqual(tab.entries[-1]["result_plain"], "2*x")
        tab.lower_field.setText("0")
        tab.upper_field.setText("1")
        tab.set_input("x^2")
        tab.apply_action("definite")
        self.assertEqual(tab.entries[-1]["result_plain"], "1/3")

    def test_signals(self) -> None:
        tab = self.make_tab()
        sent: list[str] = []
        tab.send_to_graph.connect(sent.append)
        tab.evaluate_text("x^2 + 1")
        tab._card_action("plot", tab.entries[-1])
        self.assertEqual(sent, ["x^2 + 1"])
        inserted: list[str] = []
        tab.insert_latex.connect(inserted.append)
        tab._card_action("editor", tab.entries[-1])
        self.assertEqual(inserted, ["x^{2} + 1"])

    def test_state_round_trip(self) -> None:
        tab = self.make_tab()
        tab.evaluate_text("a = 5")
        tab.evaluate_text("a + 1")
        tab.angle_button.setChecked(True)
        state = tab.state()
        other = self.make_tab()
        other.restore(state)
        self.assertEqual(len(other.entries), 2)
        self.assertEqual(other.session.angle_mode, "deg")
        self.assertEqual(other.session.variables["a"], 5)
        self.assertEqual(other.input_history, ["a = 5", "a + 1"])
        other.evaluate_text("sin(90)")
        self.assertEqual(other.entries[-1]["result_plain"], "1")

    def test_input_history_recall(self) -> None:
        tab = self.make_tab()
        tab.evaluate_text("1+1")
        tab.evaluate_text("2+2")
        tab._recall(-1)
        self.assertEqual(tab.input.text(), "2+2")
        tab._recall(-1)
        self.assertEqual(tab.input.text(), "1+1")
        tab._recall(1)
        tab._recall(1)
        self.assertEqual(tab.input.text(), "")


if __name__ == "__main__":
    unittest.main()

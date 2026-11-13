"""Linear algebra engine and Matrix tab tests."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sympy as sp
from PyQt6.QtWidgets import QApplication

from latex_picker.theme import resolve_theme
from latex_picker.workspace import linalg as L


class EngineTests(unittest.TestCase):
    def test_rref_steps_match_sympy(self) -> None:
        for text in ["[2 1 -1 8; -3 -1 2 -11; -2 1 2 -3]", "[1 2 3; 4 5 6; 7 8 9]",
                     "[0 1; 1 0]", "[1 2 -1 3; 2 4 1 0; -1 1 2 1]"]:
            m = L.parse_matrix_text(text)
            self.assertEqual(L.rref_steps(m)[-1].matrix, m.rref()[0], text)

    def test_steps_replay(self) -> None:
        m = L.parse_matrix_text("[2 1 -1 8; -3 -1 2 -11; -2 1 2 -3]")
        steps = L.rref_steps(m, aug_col=3)
        current = m
        for step in steps[1:]:
            current = step.op.apply(current)
            self.assertEqual(current, step.matrix)

    def test_inverse_and_det(self) -> None:
        m = sp.Matrix([[2, 1], [5, 3]])
        steps, inverse = L.inverse_steps(m)
        self.assertEqual(inverse, m.inv())
        self.assertEqual(L.det_steps(sp.Matrix([[1, 2, 3], [0, 4, 5], [1, 0, 6]])).value, 22)
        self.assertIsNone(L.inverse_steps(sp.Matrix([[1, 2], [2, 4]]))[1])

    def test_solve_classification(self) -> None:
        a = sp.Matrix([[2, 1, -1], [-3, -1, 2], [-2, 1, 2]])
        b = sp.Matrix([8, -11, -3])
        result = L.solve_system(a, b)
        self.assertEqual(result.kind, "unique")
        self.assertEqual(list(result.solution), [2, 3, -1])
        self.assertEqual(L.solve_system(sp.Matrix([[1, 1], [2, 2]]), sp.Matrix([1, 2])).kind,
                         "infinite")
        self.assertEqual(L.solve_system(sp.Matrix([[1, 1], [1, 1]]), sp.Matrix([1, 2])).kind,
                         "none")

    def test_parse_row_ops(self) -> None:
        self.assertEqual(L.parse_row_op("R1<->R2").kind, "swap")
        op = L.parse_row_op("R2 -> R2 - 3R1")
        self.assertEqual((op.kind, op.i, op.j, op.k), ("add", 1, 0, -3))
        self.assertEqual(L.parse_row_op("R3 = 1/2 R3").a, sp.Rational(1, 2))

    def test_parse_formats(self) -> None:
        expected = sp.Matrix([[1, 2], [3, 4]])
        for text in ["[1 2; 3 4]", "[[1, 2], [3, 4]]", "1 2\n3 4",
                     r"\begin{bmatrix}1&2\\3&4\end{bmatrix}"]:
            self.assertEqual(L.parse_matrix_text(text), expected, text)

    def test_decompositions(self) -> None:
        m = sp.Matrix([[4, 3], [6, 3]])
        p, lo, up = L.lu(m)
        self.assertEqual(p * m, lo * up)
        q, r = L.qr(sp.Matrix([[1, 1], [1, 0], [0, 1]]))
        self.assertEqual(sp.simplify(q * r - sp.Matrix([[1, 1], [1, 0], [0, 1]])), sp.zeros(3, 2))
        a = sp.Matrix([[2, 0], [0, 3]])
        pp, d = L.diagonalize(a)
        self.assertEqual(sp.simplify(pp * d * pp.inv()), a)

    def test_expressions(self) -> None:
        mats = {"A": sp.Matrix([[1, 2], [3, 4]]), "B": sp.eye(2)}
        self.assertEqual(L.evaluate_matrix_expression("A*B - 2B^T", mats),
                         sp.Matrix([[-1, 2], [3, 2]]))
        self.assertEqual(L.evaluate_matrix_expression("det(A)", mats), -2)
        self.assertEqual(L.evaluate_matrix_expression("A^-1", mats), mats["A"].inv())


class TabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def make(self):
        from latex_picker.workspace.matrix_tab import MatrixTab
        tab = MatrixTab(resolve_theme("dark", 1.0))
        tab.synchronous = True
        tab.resize(1150, 680)
        return tab

    def test_row_ops_undo_redo_auto(self) -> None:
        tab = self.make()
        self.assertTrue(tab.apply_op(L.RowOp.swap(0, 1)))
        self.assertEqual(tab.work_matrix()[0, 0], -3)
        tab.undo_op()
        self.assertEqual(tab.work_matrix()[0, 0], 2)
        tab.redo_op()
        tab.reset_work()
        tab.auto("rref")
        self.assertEqual(list(tab.work_matrix()[:, 3]), [2, 3, -1])
        tab.op_edit.setText("R1 <-> R2")
        tab._apply_typed()
        self.assertEqual(tab.work_matrix()[0, 1], 1)

    def test_compute_everything(self) -> None:
        tab = self.make()
        tab._select("B")
        errors = []
        tab.status.connect(lambda m: errors.append(m) if m.startswith("Error") else None)
        for key in ["det", "cofactor", "inverse", "transpose", "rank", "trace", "ref", "rref",
                    "power", "analyze", "null", "col", "row", "leftnull", "gs", "orthonormal",
                    "eigen", "charpoly", "diag", "jordan", "lu", "qr", "svd", "adj", "cof",
                    "norms", "cond"]:
            tab.compute(key)
        self.assertEqual(errors, [])
        for key in ["add", "sub", "mul", "rmul", "scalar", "kron", "hadamard", "comm", "hjoin",
                    "vjoin"]:
            tab.x_combo.setCurrentText("B")
            tab.y_combo.setCurrentText("B")
            tab.combine(key)
        self.assertEqual(errors, [])
        tab._select("A")
        tab.solve("gj")
        tab.solve("cramer")
        tab.expr_edit.setText("B^2 - 2B")
        tab.evaluate_expression()
        self.assertEqual(errors, [])

    def test_state_round_trip(self) -> None:
        tab = self.make()
        tab.new_matrix()
        tab._import_text("[1 2; 3 4]")
        state = tab.state()
        other = self.make()
        other.restore(state)
        self.assertEqual(other.state()["matrices"], state["matrices"])
        self.assertEqual(other.matrix("C"), sp.Matrix([[1, 2], [3, 4]]))


if __name__ == "__main__":
    unittest.main()

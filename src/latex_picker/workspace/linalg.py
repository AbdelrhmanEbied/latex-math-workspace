"""Linear algebra engine with step-by-step row reduction.

Pure sympy (plus numpy for the numeric SVD / condition number); no Qt.  All
row indices in the public objects are 0-based; text and LaTeX output uses the
1-based names students write by hand (``R_1``, ``R_2`` ...).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import sympy as sp

from .mathcore import ParseError, format_float, parse, split_top_level

_SUBSCRIPT = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
LAMBDA = sp.Symbol("lamda")


# --------------------------------------------------------------------------
# Entry helpers
# --------------------------------------------------------------------------

def simplify_entry(value: Any) -> Any:
    value = sp.sympify(value)
    if value.is_Rational or value.is_Float:
        return value
    if value.is_number:
        return sp.nsimplify(sp.simplify(value)) if value.has(sp.Float) else sp.simplify(value)
    return sp.simplify(value)


def is_zero(value: Any) -> bool:
    value = sp.sympify(value)
    if value.is_Rational:
        return value == 0
    if value.is_Float:
        return abs(value) < 1e-12
    result = value.is_zero
    if result is None:
        result = sp.simplify(value) == 0
    return bool(result)


def _clean(matrix: sp.Matrix) -> sp.Matrix:
    return matrix.applyfunc(simplify_entry)


def fmt_entry(value: Any, decimal: bool = False, digits: int = 6) -> str:
    """Compact human-readable text for one matrix entry."""
    value = sp.sympify(value)
    if decimal and not value.free_symbols:
        text = format_float(value, digits)
    else:
        text = sp.sstr(value)
    text = (text.replace("**", "^").replace("sqrt", "√").replace("*", "·")
            .replace("I", "i"))
    if text.startswith("-"):
        text = "−" + text[1:]
    return text.replace(" - ", " − ")


def entry_latex(value: Any, decimal: bool = False, digits: int = 6) -> str:
    value = sp.sympify(value)
    if decimal and not value.free_symbols:
        return format_float(value, digits).replace("e", r"\times 10^{") + (
            "}" if "e" in format_float(value, digits) else "")
    return sp.latex(value)


def _num_text(k: Any) -> str:
    text = sp.sstr(k).replace("**", "^")
    return text


def _sub(i: int) -> str:
    return str(i + 1).translate(_SUBSCRIPT)


# --------------------------------------------------------------------------
# Row operations
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class RowOp:
    """An elementary (or combined) row operation.

    * ``swap``:  R_i <-> R_j
    * ``scale``: R_i <- a R_i
    * ``add``:   R_i <- R_i + k R_j
    * ``combo``: R_i <- a R_i + k R_j   (a != 1; common in hand work)
    """

    kind: str
    i: int
    j: int = -1
    a: Any = 1
    k: Any = 0

    @staticmethod
    def swap(i: int, j: int) -> RowOp:
        return RowOp("swap", i, j)

    @staticmethod
    def scale(i: int, a: Any) -> RowOp:
        return RowOp("scale", i, -1, sp.sympify(a), 0)

    @staticmethod
    def add(i: int, j: int, k: Any) -> RowOp:
        return RowOp("add", i, j, 1, sp.sympify(k))

    @staticmethod
    def combo(i: int, a: Any, j: int, k: Any) -> RowOp:
        a = sp.sympify(a)
        if a == 1:
            return RowOp.add(i, j, k)
        return RowOp("combo", i, j, a, sp.sympify(k))

    def validate(self, rows: int) -> None:
        for index in (self.i, self.j) if self.kind != "scale" else (self.i,):
            if not 0 <= index < rows:
                raise ValueError(f"Row {index + 1} doesn't exist (matrix has {rows} rows)")
        if self.kind == "swap" and self.i == self.j:
            raise ValueError("Swap needs two different rows")
        if self.kind in {"add", "combo"} and self.i == self.j:
            raise ValueError("Use a scale operation to multiply a row by itself")
        if self.kind in {"scale", "combo"} and is_zero(self.a):
            raise ValueError("Scaling a row by 0 is not an elementary operation")

    def apply(self, matrix: sp.Matrix) -> sp.Matrix:
        self.validate(matrix.rows)
        result = sp.Matrix(matrix)
        if self.kind == "swap":
            result.row_swap(self.i, self.j)
            return result
        if self.kind == "scale":
            new_row = matrix.row(self.i) * self.a
        else:
            new_row = matrix.row(self.i) * self.a + matrix.row(self.j) * self.k
        for col in range(matrix.cols):
            result[self.i, col] = simplify_entry(new_row[col])
        return result

    def inverse(self) -> RowOp:
        if self.kind == "swap":
            return self
        if self.kind == "scale":
            return RowOp.scale(self.i, 1 / self.a)
        if self.kind == "add":
            return RowOp.add(self.i, self.j, -self.k)
        raise ValueError("Combined operations have no single elementary inverse")

    # -- formatting
    @staticmethod
    def _coef_latex(k: Any, row: int, leading: bool) -> str:
        k = sp.sympify(k)
        negative = k.could_extract_minus_sign()
        magnitude = -k if negative else k
        if magnitude == 1:
            coef = ""
        elif isinstance(magnitude, sp.Add):
            coef = rf"\left({sp.latex(magnitude)}\right)"
        else:
            coef = sp.latex(magnitude)
        term = f"{coef}R_{{{row + 1}}}"
        if leading:
            return f"-{term}" if negative else term
        return f" - {term}" if negative else f" + {term}"

    @staticmethod
    def _coef_text(k: Any, row: int, leading: bool) -> str:
        k = sp.sympify(k)
        negative = k.could_extract_minus_sign()
        magnitude = -k if negative else k
        coef = "" if magnitude == 1 else _num_text(magnitude)
        if isinstance(magnitude, sp.Add) or "/" in coef or " " in coef:
            coef = f"({coef})"
        term = f"{coef}R{_sub(row)}"
        if leading:
            return f"−{term}" if negative else term
        return f" − {term}" if negative else f" + {term}"

    def latex(self) -> str:
        target = f"R_{{{self.i + 1}}}"
        if self.kind == "swap":
            return rf"R_{{{self.i + 1}}} \leftrightarrow R_{{{self.j + 1}}}"
        if self.kind == "scale":
            return rf"{target} \to {self._coef_latex(self.a, self.i, True)}"
        first = self._coef_latex(self.a, self.i, True)
        return rf"{target} \to {first}{self._coef_latex(self.k, self.j, False)}"

    def text(self) -> str:
        target = f"R{_sub(self.i)}"
        if self.kind == "swap":
            return f"R{_sub(self.i)} ↔ R{_sub(self.j)}"
        if self.kind == "scale":
            return f"{target} ← {self._coef_text(self.a, self.i, True)}"
        first = self._coef_text(self.a, self.i, True)
        return f"{target} ← {first}{self._coef_text(self.k, self.j, False)}"

    def to_state(self) -> dict:
        return {"kind": self.kind, "i": self.i, "j": self.j,
                "a": sp.srepr(sp.sympify(self.a)), "k": sp.srepr(sp.sympify(self.k))}

    @staticmethod
    def from_state(data: dict) -> RowOp:
        return RowOp(str(data["kind"]), int(data["i"]), int(data.get("j", -1)),
                     sp.sympify(data.get("a", "1")), sp.sympify(data.get("k", "0")))


@dataclass
class Step:
    op: RowOp | None
    matrix: sp.Matrix
    note: str = ""


# -- parsing typed row operations ------------------------------------------

_ROW_TERM = re.compile(
    r"\s*([+-]?)\s*(\([^()]*\)|[^R+\-()]*?)\s*\*?\s*R\s*(\d+)\s*(?:([*/])\s*(\([^()]*\)|[0-9.]+))?",
    re.IGNORECASE,
)


def _parse_coef(text: str) -> Any:
    text = text.strip()
    if not text:
        return sp.Integer(1)
    try:
        value = parse(text)
    except ParseError as exc:
        raise ValueError(f"Can't read coefficient “{text}”") from exc
    value = sp.sympify(value)
    if value.has(sp.Float):
        value = sp.nsimplify(value, rational=True)
    return value


def _parse_combination(text: str) -> dict[int, Any]:
    terms: dict[int, Any] = {}
    position = 0
    text = text.strip()
    if not text:
        raise ValueError("Missing right-hand side")
    while position < len(text):
        match = _ROW_TERM.match(text, position)
        if not match or match.end() == position:
            raise ValueError(f"Can't read “{text[position:].strip()}”")
        sign, coef, row, op, factor = match.groups()
        value = _parse_coef(coef)
        if sign == "-":
            value = -value
        if op and factor:
            fval = _parse_coef(factor)
            value = value * fval if op == "*" else value / fval
        index = int(row) - 1
        terms[index] = terms.get(index, 0) + value
        position = match.end()
    return terms


def parse_row_op(text: str, rows: int | None = None) -> RowOp:
    """Parse ``R1<->R2``, ``R2 -> R2 - 3R1``, ``R3 = 1/2 R3``, ``-R1`` ..."""
    source = (text.strip().replace("−", "-").replace("–", "-").replace("·", "*")
              .replace("×", "*").replace("↔", "<->").replace("⇄", "<->")
              .replace("←", "<-").replace("→", "->").replace("½", "1/2"))
    source = source.translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789"))
    if not source:
        raise ValueError("Type an operation such as R2 -> R2 - 3R1")

    swap = re.fullmatch(
        r"(?:swap\s*\(?\s*)?R?\s*(\d+)\s*(?:<->|<=>|<>|,|\s+|swap)\s*R?\s*(\d+)\s*\)?",
        source, re.IGNORECASE,
    )
    if swap and (re.search(r"<->|<=>|<>|swap", source, re.IGNORECASE)
                 or re.fullmatch(r"\s*R\s*\d+\s*,?\s*R\s*\d+\s*", source, re.IGNORECASE)):
        op = RowOp.swap(int(swap.group(1)) - 1, int(swap.group(2)) - 1)
        if rows is not None:
            op.validate(rows)
        return op

    assign = re.fullmatch(r"R\s*(\d+)\s*(?:->|<-|:=|=)\s*(.+)", source, re.IGNORECASE)
    if assign:
        target = int(assign.group(1)) - 1
        terms = _parse_combination(assign.group(2))
    else:
        # shorthand: "-R1", "2R1", "1/2 R3", "R1*2", "R1/2" -> scale in place
        terms = _parse_combination(source)
        if len(terms) != 1:
            raise ValueError("Write the target row, e.g. R2 -> R2 - 3R1")
        target = next(iter(terms))
    terms = {row: coef for row, coef in terms.items() if not is_zero(coef)}
    if target not in terms:
        if not terms:
            raise ValueError("That would make the row zero")
        raise ValueError(f"R{target + 1} must appear on the right-hand side")
    others = [row for row in terms if row != target]
    if len(others) > 1:
        raise ValueError("Use one source row at a time")
    a = terms[target]
    if not others:
        if a == 1:
            raise ValueError("That operation does nothing")
        op = RowOp.scale(target, a)
    else:
        op = RowOp.combo(target, a, others[0], terms[others[0]])
    if rows is not None:
        op.validate(rows)
    return op


# --------------------------------------------------------------------------
# Elimination
# --------------------------------------------------------------------------

def _pivot_limit(matrix: sp.Matrix, aug_col: int | None) -> int:
    if aug_col is None:
        return matrix.cols
    return max(0, min(matrix.cols, aug_col))


def _choose_pivot(matrix: sp.Matrix, row: int, col: int) -> int | None:
    candidates = [r for r in range(row, matrix.rows) if not is_zero(matrix[r, col])]
    if not candidates:
        return None
    for target in (1, -1):
        for r in candidates:
            if sp.sympify(matrix[r, col]) == target:
                return r
    if row in candidates:
        return row
    return candidates[0]


def _forward(matrix: sp.Matrix, aug_col: int | None, steps: list[Step]) -> tuple[sp.Matrix, list[tuple[int, int]]]:
    current = sp.Matrix(matrix)
    pivots: list[tuple[int, int]] = []
    row = 0
    for col in range(_pivot_limit(current, aug_col)):
        if row >= current.rows:
            break
        pivot_row = _choose_pivot(current, row, col)
        if pivot_row is None:
            continue
        if pivot_row != row:
            op = RowOp.swap(row, pivot_row)
            current = op.apply(current)
            steps.append(Step(op, current, f"Bring a pivot into row {row + 1}"))
        pivot = current[row, col]
        for r in range(row + 1, current.rows):
            if is_zero(current[r, col]):
                continue
            factor = simplify_entry(-current[r, col] / pivot)
            op = RowOp.add(r, row, factor)
            current = op.apply(current)
            steps.append(Step(op, current, f"Eliminate below the pivot in column {col + 1}"))
        pivots.append((row, col))
        row += 1
    return current, pivots


def ref_steps(matrix: sp.Matrix, aug_col: int | None = None) -> list[Step]:
    """Gaussian elimination to row echelon form (leading entries not scaled)."""
    matrix = sp.Matrix(matrix)
    steps = [Step(None, matrix, "Start")]
    _forward(matrix, aug_col, steps)
    return steps


def rref_steps(matrix: sp.Matrix, aug_col: int | None = None) -> list[Step]:
    """Gauss–Jordan elimination: forward phase, then scale pivots and clear above."""
    matrix = sp.Matrix(matrix)
    steps = [Step(None, matrix, "Start")]
    current, pivots = _forward(matrix, aug_col, steps)
    for row, col in reversed(pivots):
        pivot = current[row, col]
        if sp.sympify(pivot) != 1:
            op = RowOp.scale(row, simplify_entry(1 / pivot))
            current = op.apply(current)
            steps.append(Step(op, current, f"Make the pivot in row {row + 1} equal to 1"))
        for r in range(row):
            if is_zero(current[r, col]):
                continue
            op = RowOp.add(r, row, simplify_entry(-current[r, col]))
            current = op.apply(current)
            steps.append(Step(op, current, f"Eliminate above the pivot in column {col + 1}"))
    return steps


def pivot_positions(matrix: sp.Matrix, aug_col: int | None = None) -> list[tuple[int, int]]:
    """Leading-entry positions of a matrix already in echelon form."""
    positions = []
    limit = _pivot_limit(matrix, aug_col)
    for r in range(matrix.rows):
        for c in range(limit):
            if not is_zero(matrix[r, c]):
                positions.append((r, c))
                break
    return positions


def is_rref(matrix: sp.Matrix, aug_col: int | None = None) -> bool:
    final = rref_steps(matrix, aug_col)[-1].matrix
    return final.equals(matrix) if hasattr(final, "equals") else final == matrix


def next_rref_step(matrix: sp.Matrix, aug_col: int | None = None) -> Step | None:
    steps = rref_steps(matrix, aug_col)
    return steps[1] if len(steps) > 1 else None


def inverse_steps(matrix: sp.Matrix) -> tuple[list[Step], sp.Matrix | None]:
    matrix = sp.Matrix(matrix)
    if matrix.rows != matrix.cols:
        raise ValueError("Only square matrices have inverses")
    n = matrix.rows
    augmented = matrix.row_join(sp.eye(n))
    steps = rref_steps(augmented, aug_col=n)
    steps[0].note = "Augment with the identity: [A | I]"
    final = steps[-1].matrix
    if final[:, :n] == sp.eye(n):
        return steps, final[:, n:]
    return steps, None


@dataclass
class DetResult:
    steps: list[Step]
    value: Any
    explanation: str


def det_steps(matrix: sp.Matrix) -> DetResult:
    """Determinant by row reduction using only swaps and row replacements."""
    matrix = sp.Matrix(matrix)
    if matrix.rows != matrix.cols:
        raise ValueError("Determinants need a square matrix")
    n = matrix.rows
    current = matrix
    steps = [Step(None, matrix, "Start")]
    swaps = 0
    for col in range(n):
        pivot_row = _choose_pivot(current, col, col)
        if pivot_row is None:
            steps[-1].note = steps[-1].note or ""
            explanation = (rf"\text{{Column {col + 1} has no pivot, so }} \det A = 0")
            return DetResult(steps, sp.Integer(0), explanation)
        if pivot_row != col:
            op = RowOp.swap(col, pivot_row)
            current = op.apply(current)
            swaps += 1
            steps.append(Step(op, current, "Row swap: the determinant changes sign"))
        for r in range(col + 1, n):
            if is_zero(current[r, col]):
                continue
            op = RowOp.add(r, col, simplify_entry(-current[r, col] / current[col, col]))
            current = op.apply(current)
            steps.append(Step(op, current, "Row replacement: the determinant is unchanged"))
    diagonal = [current[i, i] for i in range(n)]
    value = simplify_entry(sp.Integer(-1) ** swaps * sp.Mul(*diagonal))
    factors = r" \cdot ".join(
        rf"\left({sp.latex(d)}\right)" if sp.sympify(d).could_extract_minus_sign()
        or isinstance(sp.sympify(d), sp.Add) else sp.latex(d) for d in diagonal)
    sign = f"(-1)^{{{swaps}}} \\cdot " if swaps else ""
    explanation = rf"\det A = {sign}{factors} = {sp.latex(value)}"
    return DetResult(steps, value, explanation)


def _vmatrix(matrix: sp.Matrix) -> str:
    rows = [" & ".join(sp.latex(v) for v in matrix.row(r)) for r in range(matrix.rows)]
    return r"\begin{vmatrix} " + r" \\ ".join(rows) + r" \end{vmatrix}"


def _wrap(value: Any) -> str:
    value = sp.sympify(value)
    text = sp.latex(value)
    if value.could_extract_minus_sign() or isinstance(value, sp.Add):
        return rf"\left({text}\right)"
    return text


def cofactor_expansion_latex(matrix: sp.Matrix) -> str:
    """LaTeX of a cofactor expansion along the first row (n <= 4)."""
    matrix = sp.Matrix(matrix)
    n = matrix.rows
    if n != matrix.cols:
        raise ValueError("Determinants need a square matrix")
    if n > 4:
        raise ValueError("Cofactor expansion is shown for matrices up to 4×4")
    value = simplify_entry(matrix.det())
    if n == 1:
        return rf"\det A = {sp.latex(matrix[0, 0])}"
    if n == 2:
        a, b, c, d = matrix
        return (rf"\det A = {_vmatrix(matrix)} = {_wrap(a)}{_wrap(d)} - {_wrap(b)}{_wrap(c)}"
                rf" = {sp.latex(value)}")
    general, numeric = [], []
    for col in range(n):
        entry = matrix[0, col]
        minor = matrix.minor_submatrix(0, col)
        sign = "+" if col % 2 == 0 else "-"
        minor_det = simplify_entry(minor.det())
        lead = "" if col == 0 and sign == "+" else f" {sign} "
        general.append(f"{lead}{_wrap(entry)}{_vmatrix(minor)}")
        numeric.append(f"{lead}{_wrap(entry)}{_wrap(minor_det)}")
    return (r"\begin{aligned} \det A &= " + "".join(general) + r" \\ &= "
            + "".join(numeric) + rf" \\ &= {sp.latex(value)} \end{{aligned}}")


# --------------------------------------------------------------------------
# Solving
# --------------------------------------------------------------------------

@dataclass
class SolveResult:
    kind: str                      # unique | infinite | none
    steps: list[Step]
    solution: sp.Matrix | None = None
    particular: sp.Matrix | None = None
    basis: list[sp.Matrix] = field(default_factory=list)
    params: list[sp.Symbol] = field(default_factory=list)
    least_squares: sp.Matrix | None = None
    pivots: list[tuple[int, int]] = field(default_factory=list)

    def general(self) -> sp.Matrix | None:
        if self.kind == "unique":
            return self.solution
        if self.kind == "infinite" and self.particular is not None:
            result = sp.Matrix(self.particular)
            for t, v in zip(self.params, self.basis):
                result += t * v
            return result
        return None

    def latex(self, env: str = "bmatrix") -> str:
        if self.kind == "unique":
            return r"\mathbf{x} = " + matrix_to_latex(self.solution, env)
        if self.kind == "infinite":
            parts = [matrix_to_latex(self.particular, env)]
            for t, v in zip(self.params, self.basis):
                parts.append(f"{sp.latex(t)} {matrix_to_latex(v, env)}")
            return r"\mathbf{x} = " + " + ".join(parts)
        return r"\text{The system is inconsistent (no solution)}"

    def equations_latex(self) -> str:
        general = self.general()
        if general is None:
            return ""
        lines = [rf"x_{{{i + 1}}} &= {sp.latex(sp.expand(v))}" for i, v in enumerate(general)]
        return r"\begin{aligned} " + r" \\ ".join(lines) + r" \end{aligned}"

    @property
    def summary(self) -> str:
        if self.kind == "unique":
            return "Unique solution"
        if self.kind == "infinite":
            count = len(self.params)
            return f"Infinitely many solutions ({count} free variable{'s' if count != 1 else ''})"
        return "No solution (inconsistent)"


def least_squares(A: sp.Matrix, b: sp.Matrix) -> sp.Matrix:
    A = sp.Matrix(A)
    b = sp.Matrix(b)
    normal = A.T * A
    if normal.det() != 0:
        return _clean(normal.inv() * A.T * b)
    return _clean(A.pinv() * b)


def solve_system(A: sp.Matrix, b: sp.Matrix) -> SolveResult:
    A = sp.Matrix(A)
    b = sp.Matrix(b)
    if b.rows != A.rows:
        raise ValueError(f"b needs {A.rows} rows to match A")
    if b.cols != 1:
        raise ValueError("b must be a single column")
    n = A.cols
    steps = rref_steps(A.row_join(b), aug_col=n)
    final = steps[-1].matrix
    pivots = pivot_positions(final, n)
    for r in range(final.rows):
        if all(is_zero(final[r, c]) for c in range(n)) and not is_zero(final[r, n]):
            return SolveResult("none", steps, least_squares=least_squares(A, b), pivots=pivots)
    pivot_cols = [c for _, c in pivots]
    if len(pivot_cols) == n:
        solution = sp.zeros(n, 1)
        for r, c in pivots:
            solution[c, 0] = final[r, n]
        return SolveResult("unique", steps, solution=_clean(solution), pivots=pivots)
    free = [c for c in range(n) if c not in pivot_cols]
    params = [sp.Symbol(f"t_{i + 1}") for i in range(len(free))]
    particular = sp.zeros(n, 1)
    for r, c in pivots:
        particular[c, 0] = final[r, n]
    basis = []
    for f in free:
        v = sp.zeros(n, 1)
        v[f, 0] = 1
        for r, c in pivots:
            v[c, 0] = simplify_entry(-final[r, f])
        basis.append(v)
    return SolveResult("infinite", steps, particular=_clean(particular), basis=basis,
                       params=params, pivots=pivots)


def solve_matrix_equation(A: sp.Matrix, B: sp.Matrix) -> tuple[sp.Matrix, list[sp.Symbol]]:
    """Solve A·X = B; returns (X, free parameters)."""
    A = sp.Matrix(A)
    B = sp.Matrix(B)
    if A.rows != B.rows:
        raise ValueError("A and B need the same number of rows")
    try:
        solution, params = A.gauss_jordan_solve(B)
    except ValueError as exc:
        raise ValueError("A·X = B has no solution") from exc
    return _clean(solution), list(params)


def cramer(A: sp.Matrix, b: sp.Matrix) -> tuple[sp.Matrix, str]:
    A = sp.Matrix(A)
    b = sp.Matrix(b)
    if A.rows != A.cols:
        raise ValueError("Cramer's rule needs a square matrix")
    det = simplify_entry(A.det())
    if is_zero(det):
        raise ValueError("det A = 0, so Cramer's rule does not apply")
    values, lines = [], [rf"\det A &= {sp.latex(det)}"]
    for i in range(A.cols):
        Ai = sp.Matrix(A)
        Ai[:, i] = b
        di = simplify_entry(Ai.det())
        xi = simplify_entry(di / det)
        values.append(xi)
        lines.append(rf"x_{{{i + 1}}} &= \frac{{\det A_{{{i + 1}}}}}{{\det A}} = "
                     rf"\frac{{{sp.latex(di)}}}{{{sp.latex(det)}}} = {sp.latex(xi)}")
    return sp.Matrix(values), r"\begin{aligned} " + r" \\ ".join(lines) + r" \end{aligned}"


# --------------------------------------------------------------------------
# Decompositions and properties
# --------------------------------------------------------------------------

def _require_square(matrix: sp.Matrix, what: str) -> None:
    if matrix.rows != matrix.cols:
        raise ValueError(f"{what} needs a square matrix")


def lu(matrix: sp.Matrix) -> tuple[sp.Matrix, sp.Matrix, sp.Matrix]:
    """PLU factorisation with P·A = L·U."""
    matrix = sp.Matrix(matrix)
    _require_square(matrix, "LU decomposition")
    L, U, perm = matrix.LUdecomposition()
    P = sp.eye(matrix.rows)
    for i, j in perm:
        P.row_swap(i, j)
    return P, _clean(L), _clean(U)


def qr(matrix: sp.Matrix) -> tuple[sp.Matrix, sp.Matrix]:
    matrix = sp.Matrix(matrix)
    if matrix.rank() < matrix.cols:
        raise ValueError("QR needs linearly independent columns")
    Q, R = matrix.QRdecomposition()
    return _clean(Q), _clean(R)


def cholesky(matrix: sp.Matrix) -> sp.Matrix:
    matrix = sp.Matrix(matrix)
    _require_square(matrix, "Cholesky")
    if not matrix.is_symmetric():
        raise ValueError("Cholesky needs a symmetric matrix")
    if definiteness(matrix) != "positive definite":
        raise ValueError("Cholesky needs a positive definite matrix")
    return _clean(matrix.cholesky(hermitian=False))


def _numeric(matrix: sp.Matrix):
    import numpy as np

    if matrix.free_symbols:
        raise ValueError("This needs a numeric matrix (no symbols)")
    return np.array(matrix.evalf(), dtype=complex if matrix.has(sp.I) else float)


def _from_numpy(array, digits: int = 6) -> sp.Matrix:
    import numpy as np

    array = np.asarray(array)
    if np.iscomplexobj(array) and np.allclose(array.imag, 0):
        array = array.real
    rows = [[sp.Float(round(float(v), digits)) if not isinstance(v, complex)
             else sp.Float(round(v.real, digits)) + sp.I * sp.Float(round(v.imag, digits))
             for v in row] for row in np.atleast_2d(array)]
    return sp.Matrix(rows)


def svd(matrix: sp.Matrix) -> tuple[sp.Matrix, sp.Matrix, sp.Matrix]:
    """Numeric SVD: A = U Σ Vᵀ (Σ has the shape of A)."""
    import numpy as np

    array = _numeric(sp.Matrix(matrix))
    U, S, Vt = np.linalg.svd(array)
    sigma = np.zeros(array.shape)
    for i, s in enumerate(S):
        sigma[i, i] = s
    return _from_numpy(U), _from_numpy(sigma), _from_numpy(Vt.T)


def condition_number(matrix: sp.Matrix) -> float:
    import numpy as np

    return float(np.linalg.cond(_numeric(sp.Matrix(matrix))))


def charpoly(matrix: sp.Matrix) -> Any:
    matrix = sp.Matrix(matrix)
    _require_square(matrix, "The characteristic polynomial")
    return sp.factor(matrix.charpoly(LAMBDA).as_expr())


@dataclass
class EigenEntry:
    value: Any
    algebraic: int
    geometric: int
    vectors: list[sp.Matrix]


def eigen_info(matrix: sp.Matrix) -> list[EigenEntry]:
    matrix = sp.Matrix(matrix)
    _require_square(matrix, "Eigenvalues")
    entries = []
    for value, multiplicity, vectors in matrix.eigenvects():
        cleaned = [_clean(v) for v in vectors]
        entries.append(EigenEntry(simplify_entry(value), int(multiplicity), len(cleaned), cleaned))
    return entries


def diagonalize(matrix: sp.Matrix) -> tuple[sp.Matrix, sp.Matrix]:
    matrix = sp.Matrix(matrix)
    _require_square(matrix, "Diagonalization")
    for entry in eigen_info(matrix):
        if entry.geometric < entry.algebraic:
            raise ValueError(
                f"Not diagonalizable: λ = {sp.sstr(entry.value)} has algebraic multiplicity "
                f"{entry.algebraic} but only {entry.geometric} independent eigenvector(s)"
            )
    P, D = matrix.diagonalize()
    return _clean(P), _clean(D)


def jordan(matrix: sp.Matrix) -> tuple[sp.Matrix, sp.Matrix]:
    matrix = sp.Matrix(matrix)
    _require_square(matrix, "The Jordan form")
    P, J = matrix.jordan_form()
    return _clean(P), _clean(J)


def adjugate(matrix: sp.Matrix) -> sp.Matrix:
    matrix = sp.Matrix(matrix)
    _require_square(matrix, "The adjugate")
    return _clean(matrix.adjugate())


def cofactor_matrix(matrix: sp.Matrix) -> sp.Matrix:
    matrix = sp.Matrix(matrix)
    _require_square(matrix, "The cofactor matrix")
    return _clean(matrix.cofactor_matrix())


def gram_schmidt(matrix: sp.Matrix, normalize: bool = False) -> sp.Matrix:
    """Orthogonalise the columns; dependent columns are dropped."""
    matrix = sp.Matrix(matrix)
    basis: list[sp.Matrix] = []
    for c in range(matrix.cols):
        v = matrix[:, c]
        w = sp.Matrix(v)
        for u in basis:
            w = w - (u.dot(v) / u.dot(u)) * u
        w = _clean(w)
        if all(is_zero(x) for x in w):
            continue
        basis.append(w)
    if not basis:
        raise ValueError("All columns are zero")
    if normalize:
        basis = [_clean(u / sp.sqrt(u.dot(u))) for u in basis]
    return sp.Matrix.hstack(*basis)


def nullspace(matrix: sp.Matrix) -> list[sp.Matrix]:
    return [_clean(v) for v in sp.Matrix(matrix).nullspace()]


def columnspace(matrix: sp.Matrix) -> list[sp.Matrix]:
    return [_clean(v) for v in sp.Matrix(matrix).columnspace()]


def rowspace(matrix: sp.Matrix) -> list[sp.Matrix]:
    return [_clean(v) for v in sp.Matrix(matrix).rowspace()]


def left_nullspace(matrix: sp.Matrix) -> list[sp.Matrix]:
    return [_clean(v) for v in sp.Matrix(matrix).T.nullspace()]


def basis_matrix(vectors: list[sp.Matrix]) -> sp.Matrix | None:
    if not vectors:
        return None
    columns = [v if v.cols == 1 else v.T for v in vectors]
    return sp.Matrix.hstack(*columns)


def power(matrix: sp.Matrix, n: int) -> sp.Matrix:
    matrix = sp.Matrix(matrix)
    _require_square(matrix, "Matrix powers")
    if n < 0 and is_zero(matrix.det()):
        raise ValueError("Negative powers need an invertible matrix")
    return _clean(matrix ** int(n))


def norms(matrix: sp.Matrix) -> dict[str, Any]:
    matrix = sp.Matrix(matrix)
    result = {
        "Frobenius": simplify_entry(matrix.norm()),
        "1-norm (max column sum)": simplify_entry(matrix.norm(1)),
        "∞-norm (max row sum)": simplify_entry(matrix.norm(sp.oo)),
    }
    try:
        if matrix.free_symbols:
            raise ValueError
        import numpy as np

        result["2-norm (largest singular value)"] = sp.Float(
            round(float(np.linalg.norm(_numeric(matrix), 2)), 10))
    except (ValueError, TypeError):
        pass
    return result


def definiteness(matrix: sp.Matrix) -> str:
    matrix = sp.Matrix(matrix)
    if matrix.rows != matrix.cols or not matrix.is_symmetric():
        return "n/a (not symmetric)"
    if matrix.free_symbols:
        return "unknown (symbolic)"
    if matrix.is_positive_definite:
        return "positive definite"
    if matrix.is_negative_definite:
        return "negative definite"
    if matrix.is_positive_semidefinite:
        return "positive semidefinite"
    if matrix.is_negative_semidefinite:
        return "negative semidefinite"
    return "indefinite"


def analyze(matrix: sp.Matrix) -> list[tuple[str, str]]:
    """Summary rows (label, LaTeX value)."""
    matrix = sp.Matrix(matrix)
    rows: list[tuple[str, str]] = [
        ("Shape", rf"{matrix.rows} \times {matrix.cols}"),
        ("Rank", sp.latex(matrix.rank())),
        ("Nullity", sp.latex(matrix.cols - matrix.rank())),
    ]
    square = matrix.rows == matrix.cols
    yes = r"\text{yes}"
    no = r"\text{no}"
    rows.append(("Square", yes if square else no))
    if square:
        det = simplify_entry(matrix.det())
        rows.append(("Determinant", sp.latex(det)))
        rows.append(("Trace", sp.latex(simplify_entry(matrix.trace()))))
        invertible = not is_zero(det) if not det.free_symbols else None
        rows.append(("Invertible", yes if invertible else (no if invertible is False
                                                           else r"\text{if } " + sp.latex(det) + r" \neq 0")))
        rows.append(("Symmetric", yes if matrix.is_symmetric() else no))
        rows.append(("Skew-symmetric", yes if matrix == -matrix.T else no))
        orthogonal = (matrix.T * matrix).applyfunc(simplify_entry) == sp.eye(matrix.rows)
        rows.append(("Orthogonal", yes if orthogonal else no))
        rows.append(("Diagonal", yes if matrix.is_diagonal() else no))
        rows.append(("Upper triangular", yes if matrix.is_upper else no))
        rows.append(("Lower triangular", yes if matrix.is_lower else no))
        if matrix.is_symmetric():
            rows.append(("Definiteness", r"\text{" + definiteness(matrix) + "}"))
    return rows


# --------------------------------------------------------------------------
# Parsing and formatting
# --------------------------------------------------------------------------

_NUMBER = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?(/[+-]?\d+)?")


def parse_entry(text: str) -> Any:
    text = str(text).strip().replace("−", "-")
    if not text:
        return sp.Integer(0)
    if _NUMBER.fullmatch(text):
        try:
            if "/" in text:
                num, den = text.split("/")
                return sp.Rational(sp.Rational(num), sp.Rational(den))
            return sp.Rational(text)
        except (ValueError, ZeroDivisionError, TypeError) as exc:
            raise ValueError(f"Bad entry “{text}”") from exc
    try:
        value = sp.sympify(parse(text))
    except ParseError as exc:
        raise ValueError(f"Bad entry “{text}”: {exc}") from exc
    if isinstance(value, sp.MatrixBase) or not isinstance(value, sp.Expr):
        raise ValueError(f"Entry “{text}” is not a number or expression")
    if value.has(sp.Float):
        value = sp.nsimplify(value, rational=True)
    return value


def _split_cells(line: str) -> list[str]:
    line = line.strip().strip(",;")
    if not line:
        return []
    if "," in line:
        return [c for c in (p.strip() for p in line.split(",")) if c != ""]
    if "\t" in line:
        return [c.strip() for c in line.split("\t") if c.strip()]
    return line.split()


def parse_matrix(text: str) -> tuple[sp.Matrix, int | None]:
    """Parse many textual matrix formats; returns (matrix, augmented column)."""
    source = text.strip()
    if not source:
        raise ValueError("Nothing to import")
    aug_col: int | None = None
    rows: list[list[str]]

    begin = re.search(r"\\begin\{(\w+\*?)\}", source)
    if begin:
        env = begin.group(1)
        end = source.rfind(rf"\end{{{env}}}")
        if end < 0:
            raise ValueError(f"Missing \\end{{{env}}}")
        body = source[begin.end():end]
        if env == "array":
            spec = re.match(r"\s*\{([^}]*)\}", body)
            if spec:
                letters = spec.group(1).replace(" ", "")
                if "|" in letters:
                    before = letters[:letters.rindex("|")]
                    aug_col = sum(1 for ch in before if ch in "lcr")
                body = body[spec.end():]
        body = body.replace(r"\hline", "")
        rows = [[cell.strip() for cell in split_top_level(row, "&")]
                for row in split_top_level(body, r"\\") if row.strip()]
    else:
        stripped = re.sub(r"^(?:sp\.|np\.|numpy\.|sympy\.)?(?:Matrix|array|matrix)\s*\(", "",
                          source)
        if stripped != source:
            stripped = stripped.rstrip().rstrip(")")
        stripped = stripped.strip()
        if stripped.startswith("[[") or stripped.startswith("[ ["):
            inner = re.findall(r"\[([^\[\]]*)\]", stripped)
            rows = [[c.strip() for c in group.split(",")] for group in inner]
        elif stripped.startswith("[") and stripped.endswith("]"):
            inner = stripped[1:-1]
            lines = [p for p in re.split(r";|\n", inner) if p.strip()]
            rows = [_split_cells(line) for line in lines]
        else:
            lines = [p for p in re.split(r"\n|;", stripped) if p.strip()]
            rows = []
            for line in lines:
                if "|" in line:
                    left, right = line.rsplit("|", 1)
                    left_cells = _split_cells(left)
                    if aug_col is None:
                        aug_col = len(left_cells)
                    rows.append(left_cells + _split_cells(right))
                else:
                    rows.append(_split_cells(line))
    rows = [row for row in rows if row]
    if not rows:
        raise ValueError("No entries found")
    width = len(rows[0])
    for index, row in enumerate(rows):
        if len(row) != width:
            raise ValueError(f"Row {index + 1} has {len(row)} entries; expected {width}")
    matrix = sp.Matrix([[parse_entry(cell) for cell in row] for row in rows])
    if aug_col is not None and not 0 < aug_col < matrix.cols:
        aug_col = None
    return matrix, aug_col


def parse_matrix_text(text: str) -> sp.Matrix:
    return parse_matrix(text)[0]


_DELIMS = {
    "bmatrix": (r"\left[", r"\right]"), "pmatrix": (r"\left(", r"\right)"),
    "vmatrix": (r"\left|", r"\right|"), "Vmatrix": (r"\left\|", r"\right\|"),
    "Bmatrix": (r"\left\{", r"\right\}"), "matrix": ("", ""), "array": (r"\left[", r"\right]"),
}


def matrix_to_latex(matrix: sp.Matrix, env: str = "bmatrix", aug_col: int | None = None,
                    decimal: bool = False) -> str:
    matrix = sp.Matrix(matrix)
    if env not in _DELIMS:
        env = "bmatrix"
    body = r" \\ ".join(
        " & ".join(entry_latex(matrix[r, c], decimal) for c in range(matrix.cols))
        for r in range(matrix.rows)
    )
    if aug_col is not None and 0 < aug_col < matrix.cols or env == "array":
        if aug_col is not None and 0 < aug_col < matrix.cols:
            spec = "c" * aug_col + "|" + "c" * (matrix.cols - aug_col)
        else:
            spec = "c" * matrix.cols
        left, right = _DELIMS[env]
        return rf"{left}\begin{{array}}{{{spec}}} {body} \end{{array}}{right}"
    return rf"\begin{{{env}}} {body} \end{{{env}}}"


def to_python(matrix: sp.Matrix) -> str:
    rows = ["[" + ", ".join(sp.sstr(v) for v in matrix.row(r)) + "]" for r in range(matrix.rows)]
    return "[" + ", ".join(rows) + "]"


def to_matlab(matrix: sp.Matrix) -> str:
    rows = [" ".join(sp.sstr(v).replace("**", "^").replace(" ", "")
                     for v in matrix.row(r)) for r in range(matrix.rows)]
    return "[" + "; ".join(rows) + "]"


def to_plain(matrix: sp.Matrix, aug_col: int | None = None, decimal: bool = False) -> str:
    texts = [[fmt_entry(matrix[r, c], decimal).replace("−", "-") for c in range(matrix.cols)]
             for r in range(matrix.rows)]
    widths = [max(len(texts[r][c]) for r in range(matrix.rows)) for c in range(matrix.cols)]
    lines = []
    for row in texts:
        cells = [cell.rjust(widths[c]) for c, cell in enumerate(row)]
        if aug_col is not None and 0 < aug_col < matrix.cols:
            cells.insert(aug_col, "|")
        lines.append("  ".join(cells))
    return "\n".join(lines)


def format_matrix(matrix: sp.Matrix, fmt: str, aug_col: int | None = None,
                  decimal: bool = False) -> str:
    if fmt == "plain":
        return to_plain(matrix, aug_col, decimal)
    if fmt == "python":
        return to_python(matrix.evalf(6) if decimal else matrix)
    if fmt == "matlab":
        return to_matlab(matrix.evalf(6) if decimal else matrix)
    return matrix_to_latex(matrix, fmt, aug_col, decimal)


def steps_to_latex(steps: list[Step], env: str = "bmatrix", aug_col: int | None = None,
                   decimal: bool = False) -> str:
    if not steps:
        return ""
    lines = []
    for index, step in enumerate(steps):
        body = matrix_to_latex(step.matrix, env, aug_col, decimal)
        if index == 0 or step.op is None:
            lines.append(f"& {body}")
        else:
            lines.append(rf"\xrightarrow{{{step.op.latex()}}} \; & {body}")
    return "\\begin{aligned}\n" + " \\\\\n".join(lines) + "\n\\end{aligned}"


# --------------------------------------------------------------------------
# Matrix expressions
# --------------------------------------------------------------------------

def evaluate_matrix_expression(expr: str, matrices: dict[str, sp.Matrix]) -> Any:
    """Evaluate e.g. ``A*B - 2C^T``, ``A^-1``, ``inv(A)``, ``det(A)``."""
    source = expr.strip()
    if not source:
        raise ValueError("Type an expression such as A*B - 2C^T")
    source = re.sub(r"(\w|\))\s*\^\s*\{?\s*T\s*\}?(?![A-Za-z0-9_])", r"\1.T", source)
    source = re.sub(r"(\w|\))'", r"\1.T", source)
    source = re.sub(r"\^\s*\{\s*(-?\d+)\s*\}", r"^(\1)", source)
    env = {name: sp.ImmutableMatrix(m) for name, m in matrices.items()}
    env.update({
        "det": lambda m: sp.Matrix(m).det(),
        "inv": lambda m: sp.Matrix(m).inv() if isinstance(m, sp.MatrixBase) else 1 / m,
        "transpose": lambda m: sp.Matrix(m).T,
        "rref": lambda m: sp.Matrix(m).rref()[0],
        "rank": lambda m: sp.Matrix(m).rank(),
        "trace": lambda m: sp.Matrix(m).trace(),
        "tr": lambda m: sp.Matrix(m).trace(),
        "adj": lambda m: sp.Matrix(m).adjugate(),
        "kron": lambda a, b: sp.kronecker_product(sp.Matrix(a), sp.Matrix(b)),
        "eye": sp.eye, "zeros": sp.zeros, "ones": sp.ones,
    })
    try:
        value = parse(source, env)
    except ParseError as exc:
        raise ValueError(str(exc)) from exc
    except sp.ShapeError as exc:
        raise ValueError(f"Shape mismatch: {exc}") from exc
    except (sp.NonInvertibleMatrixError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    if isinstance(value, sp.MatrixBase):
        return _clean(sp.Matrix(value))
    return simplify_entry(value) if isinstance(value, sp.Basic) else value

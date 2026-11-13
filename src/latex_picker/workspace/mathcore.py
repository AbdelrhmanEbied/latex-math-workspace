"""Expression parsing, LaTeX translation and the calculator session.

Everything in this module is GUI-free so it can be unit tested directly.  The
calculator accepts friendly input (``2x^2 + 3x``, ``sin(30)`` in degree mode,
``|x-1|``, ``5!``, ``√2``, ``f(x) = x^2``) as well as pasted LaTeX
(``\\frac{1}{2} + \\sqrt{x}``), which is translated by :func:`latex_to_python`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import sympy as sp
from sympy.parsing.sympy_parser import (
    convert_xor,
    factorial_notation,
    function_exponentiation,
    implicit_application,
    implicit_multiplication,
    parse_expr,
    split_symbols_custom,
    standard_transformations,
)

# --------------------------------------------------------------------------
# Namespace
# --------------------------------------------------------------------------

GREEK = [
    "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta", "eta",
    "theta", "vartheta", "iota", "kappa", "lamda", "mu", "nu", "xi", "omicron",
    "rho", "sigma", "tau", "upsilon", "phi", "varphi", "chi", "psi", "omega",
    "Gamma", "Delta", "Theta", "Lambda", "Xi", "Sigma", "Upsilon", "Phi", "Psi",
    "Omega",
]

UNICODE_INPUT = {
    "−": "-", "–": "-", "×": "*", "·": "*", "⋅": "*", "÷": "/", "π": "pi",
    "∞": "oo", "θ": "theta", "α": "alpha", "β": "beta", "γ": "gamma",
    "δ": "delta", "λ": "lamda", "μ": "mu", "σ": "sigma", "φ": "phi",
    "ω": "omega", "τ": "tau", "ρ": "rho", "ε": "epsilon", "Δ": "Delta",
    "²": "^2", "³": "^3", "⁴": "^4", "⁻¹": "^(-1)", "≤": "<=", "≥": ">=",
    "≠": "!=", "√": "sqrt", "∛": "cbrt", "°": "*deg", "ℯ": "e", "ⅈ": "i",
}


def _mean(*values):
    items = _flatten(values)
    return sp.Add(*items) / len(items)


def _flatten(values) -> list:
    items: list = []
    for value in values:
        if isinstance(value, (list, tuple, sp.Tuple)):
            items.extend(_flatten(value))
        elif isinstance(value, sp.MatrixBase):
            items.extend(list(value))
        else:
            items.append(sp.sympify(value))
    if not items:
        raise ValueError("needs at least one value")
    return items


def _median(*values):
    items = sorted(_flatten(values), key=lambda v: float(sp.N(v)))
    n = len(items)
    mid = n // 2
    return items[mid] if n % 2 else (items[mid - 1] + items[mid]) / 2


def _variance(*values):
    items = _flatten(values)
    if len(items) < 2:
        raise ValueError("variance needs at least two values")
    mean = sp.Add(*items) / len(items)
    return sp.Add(*[(v - mean) ** 2 for v in items]) / (len(items) - 1)


def _pvariance(*values):
    items = _flatten(values)
    mean = sp.Add(*items) / len(items)
    return sp.Add(*[(v - mean) ** 2 for v in items]) / len(items)


def _stdev(*values):
    return sp.sqrt(_variance(*values))


def _pstdev(*values):
    return sp.sqrt(_pvariance(*values))


def _default_var(expr) -> sp.Symbol:
    free = sorted(getattr(expr, "free_symbols", set()), key=lambda s: s.name)
    for name in ("x", "t", "y", "z", "n"):
        for symbol in free:
            if symbol.name == name:
                return symbol
    return free[0] if free else sp.Symbol("x")


def _diff(expr, *args):
    expr = sp.sympify(expr)
    if not args:
        args = (_default_var(expr),)
    return sp.diff(expr, *args)


def _integrate(expr, *args):
    expr = sp.sympify(expr)
    if not args:
        return sp.integrate(expr, _default_var(expr))
    if len(args) == 3 and isinstance(args[0], sp.Symbol):
        return sp.integrate(expr, (args[0], args[1], args[2]))
    if len(args) == 2 and not isinstance(args[0], sp.Symbol):
        var = _default_var(expr)
        return sp.integrate(expr, (var, args[0], args[1]))
    return sp.integrate(expr, *args)


def _limit(expr, *args):
    expr = sp.sympify(expr)
    if len(args) == 1:
        var, point = _default_var(expr), args[0]
    elif len(args) >= 2:
        var, point = args[0], args[1]
    else:
        raise ValueError("limit needs a point, e.g. limit(sin(x)/x, x, 0)")
    if len(args) == 3 and isinstance(args[2], (str, sp.Symbol)):
        return sp.limit(expr, var, point, str(args[2]))
    if point in (sp.oo, -sp.oo):
        return sp.limit(expr, var, point)
    try:
        return sp.limit(expr, var, point, "+-")
    except ValueError:
        left = sp.limit(expr, var, point, "-")
        right = sp.limit(expr, var, point, "+")
        raise ValueError(
            f"one-sided limits differ: left = {sp.sstr(left)}, right = {sp.sstr(right)}"
        ) from None


def _sum(expr, *args):
    expr = sp.sympify(expr)
    if len(args) == 3:
        return sp.summation(expr, (args[0], args[1], args[2]))
    if len(args) == 1 and isinstance(args[0], (tuple, sp.Tuple)):
        return sp.summation(expr, tuple(args[0]))
    if not args and isinstance(expr, (sp.Tuple, tuple, list)):
        return sp.Add(*expr)
    raise ValueError("use sum(expr, n, start, end)")


def _product(expr, *args):
    expr = sp.sympify(expr)
    if len(args) == 3:
        return sp.product(expr, (args[0], args[1], args[2]))
    raise ValueError("use product(expr, n, start, end)")


def _taylor(expr, *args):
    expr = sp.sympify(expr)
    var = args[0] if args else _default_var(expr)
    point = args[1] if len(args) > 1 else 0
    order = int(args[2]) if len(args) > 2 else 6
    return sp.series(expr, var, point, order).removeO()


def _series(expr, *args):
    expr = sp.sympify(expr)
    var = args[0] if args else _default_var(expr)
    point = args[1] if len(args) > 1 else 0
    order = int(args[2]) if len(args) > 2 else 6
    return sp.series(expr, var, point, order)


def _solve(expr, *args):
    if isinstance(expr, (list, tuple, sp.Tuple)):
        eqs = list(expr)
    else:
        eqs = [expr]
    eqs = [e if isinstance(e, sp.Basic) else sp.sympify(e) for e in eqs]
    if args:
        return sp.solve(eqs if len(eqs) > 1 else eqs[0], *args, dict=len(eqs) > 1)
    free = set().union(*[e.free_symbols for e in eqs])
    if len(eqs) == 1 and len(free) > 1 and sp.Symbol("x") in free:
        return sp.solve(eqs[0], sp.Symbol("x"))
    return sp.solve(eqs if len(eqs) > 1 else eqs[0], sorted(free, key=lambda s: s.name),
                    dict=len(eqs) > 1 or len(free) > 1)


def _nsolve(expr, *args):
    expr = sp.sympify(expr)
    if isinstance(expr, sp.Equality):
        expr = expr.lhs - expr.rhs
    if len(args) == 1:
        return sp.nsolve(expr, _default_var(expr), args[0])
    return sp.nsolve(expr, *args)


def _roots(expr, *args):
    expr = sp.sympify(expr)
    if isinstance(expr, sp.Equality):
        expr = expr.lhs - expr.rhs
    var = args[0] if args else _default_var(expr)
    return sp.roots(sp.Poly(expr, var))


def _nroots(expr, *args):
    expr = sp.sympify(expr)
    if isinstance(expr, sp.Equality):
        expr = expr.lhs - expr.rhs
    var = args[0] if args else _default_var(expr)
    return sp.Poly(expr, var).nroots()


def _log(x, base=None):
    if base is None:
        return sp.log(x, 10)
    return sp.log(x, base)


def _npr(n, r):
    return sp.factorial(n) / sp.factorial(n - r)


def _matrix(*rows):
    if len(rows) == 1 and isinstance(rows[0], (list, tuple)):
        return sp.Matrix(rows[0])
    return sp.Matrix(list(rows))


def _vec(*items):
    return sp.Matrix(list(items))


def _cross(a, b):
    return sp.Matrix(a).cross(sp.Matrix(b))


def _dot(a, b):
    return sp.Matrix(a).dot(sp.Matrix(b))


def _norm(a):
    if isinstance(a, sp.MatrixBase):
        return a.norm()
    return sp.Abs(a)


def _tangent(expr, *args):
    expr = sp.sympify(expr)
    var = _default_var(expr)
    point = args[0] if args else 0
    slope = sp.diff(expr, var).subs(var, point)
    return sp.expand(expr.subs(var, point) + slope * (var - point))


def _deg(x):
    return x * 180 / sp.pi


def _rad(x):
    return x * sp.pi / 180


def _bin(n):
    return sp.Symbol(bin(int(n)))


def _hex(n):
    return sp.Symbol(hex(int(n)))


def _oct(n):
    return sp.Symbol(oct(int(n)))


def _round(x, digits=0):
    value = sp.N(x, 50)
    return sp.Float(round(float(value), int(digits))) if digits else sp.Integer(round(float(value)))


def base_namespace() -> dict[str, Any]:
    ns: dict[str, Any] = {}
    for name in [
        "sin", "cos", "tan", "cot", "sec", "csc", "asin", "acos", "atan", "acot",
        "asec", "acsc", "sinh", "cosh", "tanh", "coth", "sech", "csch", "asinh",
        "acosh", "atanh", "exp", "sqrt", "cbrt", "factorial", "binomial", "gamma",
        "beta", "erf", "gcd", "lcm", "Mod", "re", "im", "conjugate", "arg", "sign",
        "Min", "Max", "floor", "ceiling", "Abs", "simplify", "expand", "factor",
        "apart", "together", "cancel", "trigsimp", "expand_trig", "powsimp",
        "radsimp", "nsimplify", "collect", "Rational", "Integer", "Float", "Symbol",
        "symbols", "Eq", "Ne", "Lt", "Le", "Gt", "Ge", "Piecewise", "isprime",
        "factorint", "primefactors", "prime", "nextprime", "prevprime", "divisors",
        "totient", "fibonacci", "lucas", "catalan", "harmonic", "zeta", "det",
        "Matrix", "eye", "zeros", "ones", "diag", "Integral", "Derivative", "Sum",
        "Product", "Limit", "solveset", "linsolve", "dsolve", "Function",
        "Heaviside", "DiracDelta", "LambertW", "real_root", "root", "atan2",
        "summation", "product", "series", "S", "N", "Interval", "Union",
        "FiniteSet", "laplace_transform", "inverse_laplace_transform",
        "fourier_transform", "residue", "degree", "Poly", "quo", "rem", "div",
        "discriminant", "resultant", "srepr", "latex", "fraction", "numer",
        "denom", "evalf", "And", "Or", "Not", "Xor", "Implies", "Lambda",
    ]:
        if hasattr(sp, name):
            ns[name] = getattr(sp, name)
    ns.update({
        "pi": sp.pi, "e": sp.E, "E": sp.E, "i": sp.I, "I": sp.I, "j": sp.I,
        "oo": sp.oo, "inf": sp.oo, "infinity": sp.oo, "infty": sp.oo,
        "phi_golden": sp.GoldenRatio, "golden": sp.GoldenRatio,
        "EulerGamma": sp.EulerGamma, "deg": sp.pi / 180, "tau_const": 2 * sp.pi,
        "ln": sp.log, "log": _log, "log10": lambda x: sp.log(x, 10),
        "log2": lambda x: sp.log(x, 2), "lg": lambda x: sp.log(x, 10),
        "arcsin": sp.asin, "arccos": sp.acos, "arctan": sp.atan, "arccot": sp.acot,
        "arcsinh": sp.asinh, "arccosh": sp.acosh, "arctanh": sp.atanh,
        "abs": sp.Abs, "ceil": sp.ceiling, "round": _round, "mod": sp.Mod,
        "nCr": sp.binomial, "choose": sp.binomial, "nPr": _npr, "perm": _npr,
        "comb": sp.binomial, "fact": sp.factorial,
        "diff": _diff, "derivative": _diff, "d": _diff,
        "integrate": _integrate, "integral": _integrate, "int_": _integrate,
        "limit": _limit, "lim": _limit, "sum": _sum, "prod": _product,
        "taylor": _taylor, "series": _series, "solve": _solve, "nsolve": _nsolve,
        "roots": _roots, "nroots": _nroots, "tangent": _tangent,
        "mean": _mean, "avg": _mean, "median": _median, "var": _variance,
        "variance": _variance, "pvar": _pvariance, "std": _stdev, "stdev": _stdev,
        "pstd": _pstdev, "todeg": _deg, "torad": _rad, "bin": _bin, "hex": _hex,
        "oct": _oct, "matrix": _matrix, "vec": _vec, "vector": _vec,
        "cross": _cross, "dot": _dot, "norm": _norm,
        "inv": lambda m: m.inv() if isinstance(m, sp.MatrixBase) else 1 / m,
        "transpose": lambda m: m.T, "rref": lambda m: m.rref()[0],
        "rank": lambda m: m.rank(), "trace": lambda m: m.trace(),
        "eigenvals": lambda m: m.eigenvals(), "eigenvects": lambda m: m.eigenvects(),
        "nullspace": lambda m: m.nullspace(), "charpoly": lambda m: m.charpoly(
            sp.Symbol("lamda")).as_expr(),
        "identity": sp.eye, "I_n": sp.eye,
    })
    for name in GREEK:
        ns.setdefault(name, sp.Symbol(name))
    # ``beta`` and ``gamma`` are both Greek letters and special functions.  As
    # bare names they are symbols; ``gamma(5)`` still works through sympy's
    # function call fallback below.
    ns["beta"] = sp.Symbol("beta")
    ns["gamma"] = sp.Symbol("gamma")
    ns["Gamma"] = sp.gamma
    ns["Beta"] = sp.beta
    return ns


class _DisplayLog(sp.Function):
    """Unevaluated logarithm that prints with its base (display only)."""

    nargs = (1, 2)

    def _latex(self, printer):
        arg = printer._print(self.args[0])
        if len(self.args) == 1:
            return rf"\log{{\left({arg}\right)}}"
        return rf"\log_{{{printer._print(self.args[1])}}}{{\left({arg}\right)}}"


def _display_log(x, b=None, **_kw):
    return _DisplayLog(x) if b is None else _DisplayLog(x, b)


def _named(name):
    def build(*args, **_kw):
        return sp.Function(name)(*args)
    return build


DISPLAY_OVERRIDES = {
    "diff": lambda f, *a, **_kw: sp.Derivative(f, *(a or (_default_var(sp.sympify(f)),))),
    "derivative": lambda f, *a, **_kw: sp.Derivative(f, *(a or (_default_var(sp.sympify(f)),))),
    "integrate": lambda f, *a, **_kw: _display_integral(f, *a),
    "integral": lambda f, *a, **_kw: _display_integral(f, *a),
    "limit": lambda f, *a, **_kw: _display_limit(f, *a),
    "lim": lambda f, *a, **_kw: _display_limit(f, *a),
    "sum": lambda f, *a, **_kw: sp.Sum(f, (a[0], a[1], a[2])) if len(a) == 3 else _named("sum")(f, *a),
    "prod": lambda f, *a, **_kw: sp.Product(f, (a[0], a[1], a[2])) if len(a) == 3 else _named("prod")(f, *a),
    "log": _display_log,
    "log10": lambda x, **_kw: _DisplayLog(x),
    "lg": lambda x, **_kw: _DisplayLog(x),
    "log2": lambda x, **_kw: _DisplayLog(x, 2),
}


def clean_display(expr: Any) -> Any:
    """Remove ``1 *`` factors that ``evaluate=False`` parsing leaves behind."""
    if not isinstance(expr, sp.Basic) or not expr.args or isinstance(expr, sp.MatrixBase):
        return expr
    try:
        args = [clean_display(arg) for arg in expr.args]
        if isinstance(expr, sp.Mul):
            kept = [a for a in args if a != sp.S.One]
            if not kept:
                return sp.S.One
            numeric = [a for a in kept if a.is_Number and a != sp.S.NegativeOne
                       or (isinstance(a, sp.Pow) and a.base.is_Number)]
            if len(numeric) <= 1:
                # Nothing numeric to fold, so evaluating only fixes sign/fraction
                # layout (e.g. "(-1) x / 2" -> "-x/2") without changing the input.
                return sp.Mul(*kept)
            if len(kept) == 1:
                return kept[0]
            return sp.Mul(*kept, evaluate=False)
        if args == list(expr.args):
            return expr
        if isinstance(expr, (sp.Add, sp.Pow)):
            return expr.func(*args, evaluate=False)
        return expr.func(*args)
    except Exception:  # noqa: BLE001 - purely cosmetic
        return expr


def _display_integral(f, *args):
    f = sp.sympify(f)
    if not args:
        return sp.Integral(f, _default_var(f))
    if len(args) == 3 and isinstance(args[0], sp.Symbol):
        return sp.Integral(f, (args[0], args[1], args[2]))
    if len(args) == 2 and not isinstance(args[0], sp.Symbol):
        return sp.Integral(f, (_default_var(f), args[0], args[1]))
    return sp.Integral(f, *args)


def _display_limit(f, *args):
    f = sp.sympify(f)
    if len(args) == 1:
        return sp.Limit(f, _default_var(f), args[0], "+-")
    if len(args) == 3 and str(args[2]) in {"+", "-"}:
        return sp.Limit(f, args[0], args[1], str(args[2]))
    if len(args) >= 2:
        return sp.Limit(f, args[0], args[1], "+-")
    raise ValueError("limit needs a point")


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

_PROTECTED = set(GREEK) | {"lamda", "lambda", "oo", "pi", "inf", "deg"}


def _splittable(token: str) -> bool:
    if token in _PROTECTED or "_" in token or any(ch.isdigit() for ch in token):
        return False
    return len(token) > 1


TRANSFORMS = standard_transformations + (
    convert_xor,
    factorial_notation,
    split_symbols_custom(_splittable),
    implicit_multiplication,
    implicit_application,
    function_exponentiation,
)


class ParseError(ValueError):
    pass


def looks_like_latex(text: str) -> bool:
    return bool(re.search(r"\\[a-zA-Z]+|\\[{}]", text))


def _replace_abs_bars(text: str) -> str:
    # Pair |...| from the inside out.  Nested bars such as ||x|-1| resolve too.
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"\|([^|]*?[^|\s(+\-*/^,][^|]*?)\|", r"Abs(\1)", text, count=1)
    return text


def normalise_input(text: str) -> str:
    text = text.strip()
    text = re.sub(r"√\s*(\d+(?:\.\d+)?|[A-Za-z]\w*)(?!\s*\()", r"sqrt(\1)", text)
    text = re.sub(r"∛\s*(\d+(?:\.\d+)?|[A-Za-z]\w*)(?!\s*\()", r"cbrt(\1)", text)
    for key, value in UNICODE_INPUT.items():
        text = text.replace(key, value)
    text = re.sub(r"\blambda\b", "lamda", text)
    text = _replace_abs_bars(text)
    # Postfix percent: 15% -> 15/100
    text = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", text)
    # "**" stays; a lone "^" becomes power via convert_xor.
    return text


def parse(text: str, env: dict[str, Any] | None = None, *, evaluate: bool = True,
          display: bool = False) -> Any:
    """Parse user input into a sympy object."""
    if "__" in text or "import" in text.split():
        raise ParseError("Unsupported input")
    source = normalise_input(latex_to_python(text) if looks_like_latex(text) else text)
    if not source:
        raise ParseError("Empty expression")
    namespace = base_namespace()
    if display:
        namespace.update(DISPLAY_OVERRIDES)
    if env:
        namespace.update(env)
    try:
        return parse_expr(source, local_dict=namespace, transformations=TRANSFORMS,
                          evaluate=evaluate)
    except ParseError:
        raise
    except SyntaxError as exc:
        raise ParseError(f"Syntax error in “{source}”") from exc
    except Exception as exc:  # noqa: BLE001 - tokenizer errors etc.
        if type(exc).__name__ == "TokenError":
            raise ParseError("Incomplete expression: check the parentheses") from exc
        if isinstance(exc, (sp.PolynomialError, sp.polys.polyerrors.PolificationFailed,
                            RuntimeError, OverflowError)):
            raise ParseError(_clean_error(exc)) from exc
        raise
    except (TypeError, ValueError, AttributeError, NotImplementedError,
            ZeroDivisionError, sp.SympifyError, IndexError, KeyError) as exc:
        raise ParseError(_clean_error(exc)) from exc


def _clean_error(exc: Exception) -> str:
    message = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    return message[:240]


# --------------------------------------------------------------------------
# LaTeX -> Python (sympy syntax) translation
# --------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"\\[a-zA-Z]+\*?|\\.|\d+(?:\.\d+)?|\.\d+|[a-zA-Z]|\S")

_LATEX_FUNCS = {
    "sin": "sin", "cos": "cos", "tan": "tan", "cot": "cot", "sec": "sec", "csc": "csc",
    "arcsin": "asin", "arccos": "acos", "arctan": "atan", "sinh": "sinh",
    "cosh": "cosh", "tanh": "tanh", "coth": "coth", "exp": "exp", "ln": "ln",
    "log": "log", "lg": "log", "det": "det", "gcd": "gcd", "max": "Max",
    "min": "Min", "arg": "arg", "Re": "re", "Im": "im", "sgn": "sign",
    "deg": "deg_fn", "dim": "dim", "ker": "ker", "Pr": "Pr", "tr": "trace",
    "operatorname": None,
}
_INVERSE = {"sin": "asin", "cos": "acos", "tan": "atan", "sinh": "asinh",
            "cosh": "acosh", "tanh": "atanh", "cot": "acot", "sec": "asec", "csc": "acsc"}

_LATEX_SYMBOLS = {
    "pi": "pi", "infty": "oo", "lambda": "lamda", "Lambda": "Lambda",
    "varepsilon": "epsilon", "epsilon": "epsilon", "varphi": "phi",
    "vartheta": "theta", "e": "e",
}
_OPS = {
    "cdot": "*", "times": "*", "ast": "*", "div": "/", "pm": "+", "mp": "-",
    "le": "<=", "leq": "<=", "leqslant": "<=", "ge": ">=", "geq": ">=",
    "geqslant": ">=", "neq": "!=", "ne": "!=", "lt": "<", "gt": ">",
    "%": "%", "{": "(", "}": ")",
}
_SKIP = {",", ";", "!", ":", " ", "quad", "qquad", "displaystyle", "textstyle",
         "limits", "nolimits", "left.", "right.", "big", "Big", "bigg", "Bigg",
         "bigl", "bigr", "Bigl", "Bigr", "biggl", "biggr", "nonumber", "notag",
         "enspace", "thinspace", "medspace", "thickspace", "negthinspace",
         "mathstrut", "strut"}
_FONT_CMDS = {"mathrm", "text", "textrm", "mathit", "mathbf", "boldsymbol", "bm",
              "mathsf", "mathtt", "textit", "textbf", "mathcal", "mathbb",
              "mathfrak", "operatorname", "operatorname*", "vec", "mathnormal"}
_OPEN = {"(": ")", "[": "]", "\\{": "\\}", "\\lbrace": "\\rbrace", "|": "|",
         "\\lvert": "\\rvert", "\\vert": "\\vert", "\\lfloor": "\\rfloor",
         "\\lceil": "\\rceil", "\\langle": "\\rangle", "\\|": "\\|",
         "\\Vert": "\\Vert", "\\lVert": "\\rVert", ".": "."}
_MATRIX_ENVS = {"matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix",
                "smallmatrix", "array"}


def split_top_level(text: str, separator: str) -> list[str]:
    """Split LaTeX source at *separator* outside braces and environments."""
    parts: list[str] = []
    depth = 0
    env_depth = 0
    start = 0
    i = 0
    while i < len(text):
        if text.startswith("\\begin{", i) or text.startswith("\\end{", i):
            # Skip the whole "\begin{name}" / "\end{name}" token so the name's
            # closing brace is not counted as a group brace.
            env_depth += 1 if text.startswith("\\begin{", i) else -1
            close = text.find("}", i)
            i = len(text) if close < 0 else close + 1
            continue
        ch = text[i]
        if ch == "\\" and not text.startswith(separator, i):
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif depth == 0 and env_depth == 0 and text.startswith(separator, i):
            parts.append(text[start:i])
            i += len(separator)
            start = i
            continue
        i += 1
    parts.append(text[start:])
    return parts


class _LatexTranslator:
    def __init__(self, source: str) -> None:
        self.source = source
        self.tokens: list[str] = []
        self.spans: list[tuple[int, int]] = []
        for match in _TOKEN_RE.finditer(source):
            self.tokens.append(match.group())
            self.spans.append(match.span())
        self.pos = 0

    # -- token helpers
    def peek(self, offset: int = 0) -> str | None:
        index = self.pos + offset
        return self.tokens[index] if index < len(self.tokens) else None

    def take(self) -> str:
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def expect(self, token: str) -> None:
        if self.peek() != token:
            raise ParseError(f"Expected {token!r} in LaTeX")
        self.pos += 1

    def raw_group(self) -> str:
        """Return the raw source of the next {...} group (or single token)."""
        if self.peek() != "{":
            return self.take()
        start_index = self.pos
        depth = 0
        while self.pos < len(self.tokens):
            token = self.take()
            if token == "{":
                depth += 1
            elif token == "}":
                depth -= 1
                if depth == 0:
                    begin = self.spans[start_index][1]
                    end = self.spans[self.pos - 1][0]
                    return self.source[begin:end]
        raise ParseError("Unbalanced braces in LaTeX")

    def group(self) -> str:
        if self.peek() == "{":
            self.take()
            body = self.sequence(lambda t: t == "}")
            self.expect("}")
            return f"({body})"
        return self.atom(postfix=False)

    # -- grammar
    def sequence(self, stop) -> str:
        parts: list[str] = []
        while self.pos < len(self.tokens):
            token = self.peek()
            if stop(token):
                break
            item = self.item(stop)
            if item:
                parts.append(item)
        return " ".join(parts)

    def item(self, stop) -> str:
        token = self.peek()
        if token in {"+", "-", "*", "/", "=", "<", ">", ",", "!"}:
            self.take()
            if token == "<" and self.peek() == "=":
                self.take()
                return "<="
            if token == ">" and self.peek() == "=":
                self.take()
                return ">="
            return token
        if token in {"&", "\\\\"}:
            raise ParseError("Alignment characters can't be evaluated")
        if token in {"\\int", "\\iint", "\\oint"}:
            return self.integral(stop)
        if token in {"\\sum", "\\prod"}:
            return self.big_operator(stop)
        if token == "\\lim":
            return self.limit(stop)
        if token in {"\\frac", "\\dfrac", "\\tfrac"} and self._is_derivative():
            return self.derivative(stop)
        return self.atom()

    def _is_derivative(self) -> bool:
        save = self.pos
        try:
            self.take()
            num = self.raw_group().replace(" ", "")
            den = self.raw_group().replace(" ", "")
        except (ParseError, IndexError):
            return False
        finally:
            self.pos = save
        return bool(re.fullmatch(r"(d|\\partial)(\^\{?\d+\}?)?", num)) and bool(
            re.fullmatch(r"(d|\\partial)[a-zA-Z](\^\{?\d+\}?)?", den)
        )

    def derivative(self, stop) -> str:
        self.take()
        num = self.raw_group().replace(" ", "")
        den = self.raw_group().replace(" ", "")
        order_match = re.search(r"\^\{?(\d+)\}?", num)
        order = int(order_match.group(1)) if order_match else 1
        var = re.sub(r"^(d|\\partial)", "", den)[0]
        body = self.sequence(lambda t: stop(t) or t in {"+", "-", "="})
        if not body.strip():
            raise ParseError("Derivative needs an expression after d/dx")
        return f"diff(({body}), {var}, {order})"

    def _limits(self) -> tuple[str | None, str | None]:
        lower = upper = None
        for _ in range(2):
            if self.peek() == "\\limits":
                self.take()
            if self.peek() == "_":
                self.take()
                lower = self.raw_group()
            elif self.peek() == "^":
                self.take()
                upper = self.raw_group()
        return lower, upper

    def integral(self, stop) -> str:
        self.take()
        lower, upper = self._limits()

        def is_diff(token: str | None) -> bool:
            if token == "d" and self.peek(1) and re.fullmatch(r"[a-zA-Z]", self.peek(1) or ""):
                return True
            if token in {"\\mathrm", "\\text"} and self.peek(1) == "{" and self.peek(2) == "d":
                return True
            return False

        body = self.sequence(lambda t: stop(t) or is_diff(t))
        var = "x"
        if is_diff(self.peek()):
            if self.peek() == "d":
                self.take()
                var = self.take()
            else:
                self.take()
                self.raw_group()
                var = self.take()
        if not body.strip():
            body = "1"
        if lower is not None and upper is not None:
            low = translate_fragment(lower)
            high = translate_fragment(upper)
            return f"integrate(({body}), {var}, {low}, {high})"
        return f"integrate(({body}), {var})"

    def big_operator(self, stop) -> str:
        name = "sum" if self.take() == "\\sum" else "prod"
        lower, upper = self._limits()
        if lower is None or upper is None or "=" not in lower:
            raise ParseError("Sums need bounds like \\sum_{n=1}^{N}")
        var, start = lower.split("=", 1)
        body = self.sequence(lambda t: stop(t) or t in {"+", "-", "="})
        return (f"{name}(({body}), {translate_fragment(var)}, "
                f"{translate_fragment(start)}, {translate_fragment(upper)})")

    def limit(self, stop) -> str:
        self.take()
        lower, _ = self._limits()
        if not lower:
            raise ParseError("Limits need \\lim_{x \\to a}")
        match = re.match(r"\s*([a-zA-Z])\s*(\\to|\\rightarrow|\\longrightarrow|->)\s*(.+)$",
                         lower)
        if not match:
            raise ParseError("Limits need \\lim_{x \\to a}")
        var, point = match.group(1), match.group(3).strip()
        direction = ""
        if point.endswith("^+") or point.endswith("^{+}"):
            direction, point = "+", re.sub(r"\^\{?\+\}?$", "", point)
        elif point.endswith("^-") or point.endswith("^{-}"):
            direction, point = "-", re.sub(r"\^\{?-\}?$", "", point)
        body = self.sequence(lambda t: stop(t) or t in {"+", "-", "="})
        point_py = translate_fragment(point)
        if direction:
            return f"limit(({body}), {var}, {point_py}, '{direction}')"
        return f"limit(({body}), {var}, {point_py})"

    def atom(self, postfix: bool = True) -> str:
        if self.pos >= len(self.tokens):
            raise ParseError("Unexpected end of LaTeX")
        token = self.take()
        result: str
        if token == "{":
            body = self.sequence(lambda t: t == "}")
            self.expect("}")
            result = f"({body})"
        elif token in {"(", "["}:
            closer = ")" if token == "(" else "]"
            body = self.sequence(lambda t: t == closer)
            self.expect(closer)
            result = f"({body})"
        elif token == "|":
            body = self.sequence(lambda t: t == "|")
            self.expect("|")
            result = f"Abs({body})"
        elif token == "\\left":
            result = self.left_right()
        elif token in {"\\lvert", "\\vert", "\\|", "\\Vert", "\\lVert"}:
            closer = {"\\lvert": "\\rvert", "\\vert": "\\vert", "\\|": "\\|",
                      "\\Vert": "\\Vert", "\\lVert": "\\rVert"}[token]
            body = self.sequence(lambda t: t == closer)
            self.expect(closer)
            result = f"Abs({body})" if token in {"\\lvert", "\\vert"} else f"norm({body})"
        elif token in {"\\lfloor", "\\lceil"}:
            closer = "\\rfloor" if token == "\\lfloor" else "\\rceil"
            body = self.sequence(lambda t: t == closer)
            self.expect(closer)
            func_name = "floor" if token == "\\lfloor" else "ceiling"
            result = f"{func_name}({body})"
        elif token in {"\\frac", "\\dfrac", "\\tfrac", "\\cfrac"}:
            num = self.group()
            den = self.group()
            result = f"({num}/{den})"
        elif token == "\\binom":
            n = self.group()
            k = self.group()
            result = f"binomial({n}, {k})"
        elif token == "\\sqrt":
            index = None
            if self.peek() == "[":
                self.take()
                index = self.sequence(lambda t: t == "]")
                self.expect("]")
            body = self.group()
            result = f"root({body}, {index})" if index else f"sqrt({body})"
        elif token == "\\begin":
            result = self.environment()
        elif token[1:] in _FONT_CMDS:
            raw = self.raw_group()
            name = re.sub(r"[^A-Za-z0-9_]", "", raw)
            if token == "\\mathbb":
                result = {"R": "Reals", "Z": "Integers", "N": "Naturals",
                          "Q": "Rationals", "C": "Complexes"}.get(name, name)
            elif not name:
                result = ""
            elif name == "d":
                result = "d_"
            else:
                result = name
        elif token[1:] in _LATEX_FUNCS:
            result = self.function(token[1:])
        elif token[1:] in _SKIP or token in {"\\,", "\\;", "\\!", "\\:", "\\ "}:
            return ""
        elif token[1:] in _OPS:
            result = _OPS[token[1:]]
        elif token in {"\\to", "\\rightarrow"}:
            raise ParseError("Arrows can only appear inside limits")
        elif token.startswith("\\"):
            name = token[1:]
            result = _LATEX_SYMBOLS.get(name, name if name.isalpha() else "")
            if not result:
                raise ParseError(f"Can't evaluate {token}")
        elif token in {"^", "_"}:
            raise ParseError(f"Unexpected {token}")
        elif token == "'":
            raise ParseError("Primes aren't supported; use \\frac{d}{dx}")
        else:
            result = token
            if re.fullmatch(r"[a-zA-Z]", token) and self.peek() == "_":
                self.take()
                sub = re.sub(r"[^A-Za-z0-9]", "", self.raw_group())
                result = f"{token}_{sub}" if sub else token
        if postfix:
            result = self.postfix(result)
        return result

    def postfix(self, base: str) -> str:
        while self.peek() in {"^", "_", "!", "'"}:
            token = self.take()
            if token == "^":
                if self.peek() == "\\circ":
                    self.take()
                    base = f"({base}*deg)"
                    continue
                exponent = self.group()
                base = f"({base})**{exponent}"
            elif token == "_":
                self.raw_group()  # subscripts on non-letters are decorative
            elif token == "!":
                base = f"factorial({base})"
            else:
                raise ParseError("Primes aren't supported; use \\frac{d}{dx}")
        return base

    def left_right(self) -> str:
        opener = self.take()
        if opener not in _OPEN:
            raise ParseError(f"Unsupported delimiter \\left{opener}")
        body = self.sequence(lambda t: t == "\\right")
        self.expect("\\right")
        self.take()  # closing delimiter
        if opener in {"|", "\\lvert", "\\vert"}:
            return f"Abs({body})"
        if opener in {"\\|", "\\Vert", "\\lVert"}:
            return f"norm({body})"
        if opener == "\\lfloor":
            return f"floor({body})"
        if opener == "\\lceil":
            return f"ceiling({body})"
        return f"({body})"

    def function(self, name: str) -> str:
        if name == "operatorname":
            name = re.sub(r"[^A-Za-z]", "", self.raw_group())
        target = _LATEX_FUNCS.get(name) or name
        power = None
        base = None
        if self.peek() == "_" and name == "log":
            self.take()
            base = translate_fragment(self.raw_group())
        if self.peek() == "^":
            self.take()
            power = self.raw_group().replace(" ", "")
            if power in {"-1", "{-1}"} and name in _INVERSE:
                target = _INVERSE[name]
                power = None
        if self.peek() in {"(", "\\left", "{"}:
            argument = self.atom(postfix=False)
        else:
            pieces = []
            while self.peek() is not None and (
                re.fullmatch(r"[a-zA-Z0-9.]+", self.peek() or "")
                or self.peek() in {"\\pi", "\\theta", "\\alpha", "\\beta", "\\phi",
                                   "\\frac", "\\sqrt", "^"}
            ):
                if self.peek() == "^":
                    pieces[-1] = self.postfix(pieces[-1]) if pieces else ""
                    continue
                pieces.append(self.atom(postfix=False))
            if not pieces:
                raise ParseError(f"\\{name} needs an argument")
            argument = "(" + " ".join(pieces) + ")"
        if base is not None:
            call = f"log({argument}, {base})"
        elif target == "log":
            call = f"ln({argument})" if name == "ln" else f"log({argument})"
        else:
            call = f"{target}({argument})"
        if power:
            call = f"({call})**({translate_fragment(power)})"
        return call

    def environment(self) -> str:
        name = self.raw_group().strip()
        if name not in _MATRIX_ENVS:
            raise ParseError(f"Can't evaluate the {name} environment")
        if name == "array" and self.peek() == "{":
            self.raw_group()
        start = self.spans[self.pos][0] if self.pos < len(self.tokens) else len(self.source)
        depth = 1
        while self.pos < len(self.tokens):
            token = self.take()
            if token == "\\begin":
                depth += 1
            elif token == "\\end":
                depth -= 1
                if depth == 0:
                    end = self.spans[self.pos - 1][0]
                    self.raw_group()
                    body = self.source[start:end]
                    rows = [r for r in split_top_level(body, "\\\\") if r.strip()]
                    cells = [
                        "[" + ", ".join(translate_fragment(c.replace("\\hline", ""))
                                        for c in split_top_level(row.replace("\\hline", ""), "&"))
                        + "]"
                        for row in rows
                    ]
                    matrix = f"Matrix([{', '.join(cells)}])"
                    if name == "vmatrix":
                        return f"det({matrix})"
                    return matrix
        raise ParseError(f"Missing \\end{{{name}}}")


def translate_fragment(latex: str) -> str:
    translator = _LatexTranslator(latex.strip())
    result = translator.sequence(lambda t: False)
    return f"({result})" if result.strip() else "0"


def latex_to_python(latex: str) -> str:
    """Translate a LaTeX math expression to sympy-parsable Python syntax."""
    text = latex.strip()
    for wrapper in (("$$", "$$"), ("\\[", "\\]"), ("\\(", "\\)"), ("$", "$")):
        if text.startswith(wrapper[0]) and text.endswith(wrapper[1]) and len(text) > 2:
            text = text[len(wrapper[0]):-len(wrapper[1])].strip()
            break
    text = re.sub(r"\\(begin|end)\{(equation|equation\*|displaymath)\}", "", text)
    translator = _LatexTranslator(text)
    result = translator.sequence(lambda t: False)
    result = re.sub(r"\s+", " ", result).strip()
    if not result:
        raise ParseError("Nothing to evaluate")
    return result


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------

def to_latex(obj: Any, order: str | None = None) -> str:
    """LaTeX for any calculator value.  ``order="none"`` keeps argument order
    (used to display unevaluated input exactly as typed)."""
    if isinstance(obj, bool):
        return r"\text{true}" if obj else r"\text{false}"
    if isinstance(obj, dict):
        items = [f"{to_latex(k)} = {to_latex(v)}" for k, v in obj.items()]
        return r",\; ".join(items) if items else r"\varnothing"
    if isinstance(obj, (list, tuple)):
        if not obj:
            return r"\varnothing"
        if all(isinstance(item, dict) for item in obj):
            return r"\quad\text{or}\quad ".join(to_latex(item) for item in obj)
        return r"\left\{ " + ",\\; ".join(to_latex(item, order) for item in obj) + r" \right\}"
    if isinstance(obj, str):
        return r"\text{" + obj.replace("_", r"\_") + "}"
    try:
        if order:
            return sp.latex(obj, ln_notation=True, order=order)
        return sp.latex(obj, ln_notation=True)
    except Exception:  # noqa: BLE001
        return sp.latex(obj)


def to_plain(obj: Any) -> str:
    if isinstance(obj, dict):
        return ", ".join(f"{to_plain(k)} = {to_plain(v)}" for k, v in obj.items())
    if isinstance(obj, (list, tuple)):
        if all(isinstance(item, dict) for item in obj) and obj:
            return " or ".join(f"({to_plain(item)})" for item in obj)
        return "{" + ", ".join(to_plain(item) for item in obj) + "}"
    text = sp.sstr(obj) if isinstance(obj, sp.Basic) else str(obj)
    return text.replace("**", "^")


def format_float(value: Any, digits: int = 12) -> str:
    try:
        number = sp.N(value, digits)
    except Exception:  # noqa: BLE001
        return str(value)
    if isinstance(number, sp.Float):
        text = sp.sstr(number, full_prec=False)
        if "e" not in text and "." in text:
            text = text.rstrip("0").rstrip(".")
        return text
    return sp.sstr(number, full_prec=False).replace("**", "^")


def approximate(obj: Any, digits: int = 12) -> Any:
    if isinstance(obj, dict):
        return {k: approximate(v, digits) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return type(obj)(approximate(item, digits) for item in obj)
    if isinstance(obj, sp.MatrixBase):
        return obj.evalf(digits)
    if isinstance(obj, sp.Basic):
        try:
            return obj.evalf(digits)
        except Exception:  # noqa: BLE001
            return obj
    return obj


def _strip_float_zeros(text: str) -> str:
    return re.sub(r"(\d+\.\d*?[1-9])0+\b|(\d+)\.0+\b", lambda m: m.group(1) or m.group(2), text)


# --------------------------------------------------------------------------
# Calculator session
# --------------------------------------------------------------------------

@dataclass
class CalcResult:
    ok: bool
    input_text: str
    input_latex: str = ""
    value: Any = None
    result_latex: str = ""
    result_plain: str = ""
    approx_latex: str = ""
    approx_plain: str = ""
    error: str = ""
    kind: str = "value"   # value | assign | function | equation | inequality
    note: str = ""

    @property
    def full_latex(self) -> str:
        if not self.ok:
            return ""
        if self.kind in {"assign", "function"}:
            return self.result_latex
        joiner = r"\;\Rightarrow\; " if self.kind in {"equation", "inequality"} else " = "
        if self.input_latex and self.input_latex != self.result_latex:
            return f"{self.input_latex}{joiner}{self.result_latex}"
        return self.result_latex


_ASSIGN_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*:?=(?!=)\s*(.+)$")
_FUNC_RE = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*\(\s*([A-Za-z][A-Za-z0-9_]*(?:\s*,\s*[A-Za-z][A-Za-z0-9_]*)*)\s*\)"
    r"\s*:?=(?!=)\s*(.+)$"
)
_RESERVED = set(base_namespace()) - set(GREEK) - {"beta", "gamma"}


def _split_equation(text: str) -> tuple[str, str] | None:
    depth = 0
    for index, ch in enumerate(text):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "=" and depth == 0:
            prev = text[index - 1] if index else ""
            nxt = text[index + 1] if index + 1 < len(text) else ""
            if prev in "<>!=:" or nxt == "=":
                continue
            return text[:index], text[index + 1:]
    return None


def _split_commas(text: str) -> list[str]:
    parts, depth, start = [], 0, 0
    for index, ch in enumerate(text):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


_TRIG = {sp.sin, sp.cos, sp.tan, sp.cot, sp.sec, sp.csc}
_ATRIG = {sp.asin, sp.acos, sp.atan, sp.acot, sp.asec, sp.acsc}


def degree_functions() -> dict[str, Any]:
    """Trig functions that take / return degrees (for DEG mode)."""
    to_rad = sp.pi / 180
    env: dict[str, Any] = {}
    for name, func in (("sin", sp.sin), ("cos", sp.cos), ("tan", sp.tan),
                       ("cot", sp.cot), ("sec", sp.sec), ("csc", sp.csc)):
        env[name] = (lambda f: lambda x, **_kw: f(x * to_rad))(func)
    for names, func in ((("asin", "arcsin"), sp.asin), (("acos", "arccos"), sp.acos),
                        (("atan", "arctan"), sp.atan), (("acot", "arccot"), sp.acot),
                        (("asec",), sp.asec), (("acsc",), sp.acsc)):
        wrapper = (lambda f: lambda x, **_kw: f(x) / to_rad)(func)
        for name in names:
            env[name] = wrapper
    return env


def apply_degrees(expr: Any) -> Any:
    if not isinstance(expr, sp.Basic):
        return expr
    for func in _TRIG:
        expr = expr.replace(func, lambda arg, f=func: f(arg * sp.pi / 180))
    for func in _ATRIG:
        expr = expr.replace(func, lambda arg, f=func: f(arg) * 180 / sp.pi)
    return expr


@dataclass
class CalcSession:
    variables: dict[str, Any] = field(default_factory=dict)
    functions: dict[str, tuple[list[str], str]] = field(default_factory=dict)
    angle_mode: str = "rad"   # rad | deg
    digits: int = 12

    def env(self) -> dict[str, Any]:
        env: dict[str, Any] = {}
        for name, (params, body) in self.functions.items():
            symbols = [sp.Symbol(p) for p in params]
            try:
                env[name] = sp.Lambda(tuple(symbols), parse(body, self._value_env()))
            except ParseError:
                continue
        env.update(self._value_env())
        return env

    def _value_env(self) -> dict[str, Any]:
        env: dict[str, Any] = degree_functions() if self.angle_mode == "deg" else {}
        env.update(self.variables)
        return env

    def _finish(self, obj: Any) -> Any:
        if isinstance(obj, (sp.Integral, sp.Derivative, sp.Limit, sp.Sum, sp.Product)):
            obj = obj.doit()
        return obj

    def _display(self, text: str) -> str:
        try:
            display_env = {name: sp.Function(name) for name in self.functions}
            shown = clean_display(parse(text, display_env, evaluate=False, display=True))
            latex = to_latex(shown, "none")
            latex = re.sub(r"(?<![\d.}])1 \\cdot (?=\\frac)", "", latex)
            return latex
        except Exception:  # noqa: BLE001 - display is cosmetic
            return r"\texttt{" + re.sub(r"([#$%&_{}])", r"\\\1", text) + "}"

    def preview(self, text: str) -> tuple[str, str]:
        """LaTeX for what the user typed, without evaluating it.

        Returns ``(latex, error)``; exactly one of them is non-empty unless the
        input is blank.
        """
        raw = text.strip()
        if not raw:
            return "", ""
        display_env = {name: sp.Function(name) for name in self.functions}

        def show(part: str) -> str:
            return to_latex(clean_display(parse(part, display_env, evaluate=False,
                                                display=True)), "none")

        try:
            source = latex_to_python(raw) if looks_like_latex(raw) else raw
            match = _FUNC_RE.match(source)
            if match and match.group(1) not in _RESERVED:
                name, params, body = match.groups()
                args = ", ".join(sp.latex(sp.Symbol(p.strip())) for p in params.split(","))
                return f"{name}({args}) = {show(body)}", ""
            match = _ASSIGN_RE.match(source)
            if match and match.group(1) not in _RESERVED:
                return f"{sp.latex(sp.Symbol(match.group(1)))} = {show(match.group(2))}", ""
            parts = _split_commas(source)
            if len(parts) > 1 and all(_split_equation(p) for p in parts):
                rows = [" = ".join(show(x) for x in _split_equation(p))  # type: ignore[union-attr]
                        for p in parts]
                return r"\begin{cases} " + r" \\ ".join(rows) + r" \end{cases}", ""
            equation = _split_equation(source)
            if equation is not None:
                return f"{show(equation[0])} = {show(equation[1])}", ""
            return show(source), ""
        except ParseError as exc:
            return "", str(exc)
        except RecursionError:
            return "", "Expression is nested too deeply"
        except Exception as exc:  # noqa: BLE001
            return "", _clean_error(exc)

    def evaluate(self, text: str) -> CalcResult:
        raw = text.strip()
        result = CalcResult(ok=False, input_text=raw)
        if not raw:
            result.error = "Type an expression"
            return result
        try:
            source = latex_to_python(raw) if looks_like_latex(raw) else raw
            return self._evaluate(source, result)
        except ParseError as exc:
            result.error = str(exc)
        except RecursionError:
            result.error = "Expression is nested too deeply"
        except Exception as exc:  # noqa: BLE001 - surface any CAS failure
            result.error = _clean_error(exc)
        return result

    def _evaluate(self, source: str, result: CalcResult) -> CalcResult:
        func_match = _FUNC_RE.match(source)
        if func_match and func_match.group(1) not in _RESERVED:
            name, params_raw, body = func_match.groups()
            params = [p.strip() for p in params_raw.split(",")]
            body_expr = parse(body, self._value_env())
            symbols = tuple(sp.Symbol(p) for p in params)
            self.functions[name] = (params, body.strip())
            result.ok = True
            result.kind = "function"
            result.value = sp.Lambda(symbols, body_expr)
            args = ", ".join(sp.latex(s) for s in symbols)
            result.result_latex = f"{name}({args}) = {to_latex(body_expr)}"
            result.result_plain = f"{name}({', '.join(params)}) = {to_plain(body_expr)}"
            result.input_latex = result.result_latex
            result.note = f"Defined function {name}"
            return result

        assign_match = _ASSIGN_RE.match(source)
        if assign_match and assign_match.group(1) not in _RESERVED:
            name, body = assign_match.groups()
            value = self._finish(parse(body, self.env()))
            self.variables[name] = value
            self.functions.pop(name, None)
            result.ok = True
            result.kind = "assign"
            result.value = value
            symbol = sp.latex(sp.Symbol(name))
            result.input_latex = f"{symbol} = {self._display(body)}"
            result.result_latex = f"{symbol} = {to_latex(value)}"
            result.result_plain = f"{name} = {to_plain(value)}"
            self._attach_approx(result, value)
            result.note = f"Stored in {name}"
            return result

        parts = _split_commas(source)
        if len(parts) > 1 and all(_split_equation(p) for p in parts):
            equations = []
            for part in parts:
                lhs, rhs = _split_equation(part)  # type: ignore[misc]
                equations.append(sp.Eq(self._finish(parse(lhs, self.env())),
                                       self._finish(parse(rhs, self.env()))))
            unknowns = sorted(set().union(*[e.free_symbols for e in equations]),
                              key=lambda s: s.name)
            solution = sp.solve(equations, unknowns, dict=True)
            result.ok = True
            result.kind = "equation"
            result.input_latex = r"\begin{cases} " + r" \\ ".join(
                to_latex(e) for e in equations) + r" \end{cases}"
            self._set_solution(result, solution, unknowns)
            return result

        equation = _split_equation(source)
        if equation is not None:
            lhs = self._finish(parse(equation[0], self.env()))
            rhs = self._finish(parse(equation[1], self.env()))
            eq = sp.Eq(lhs, rhs, evaluate=False)
            unknowns = sorted((lhs - rhs).free_symbols, key=lambda s: s.name)
            result.ok = True
            result.kind = "equation"
            result.input_latex = f"{to_latex(lhs)} = {to_latex(rhs)}"
            if not unknowns:
                truth = sp.simplify(lhs - rhs) == 0
                result.value = truth
                result.result_latex = to_latex(bool(truth))
                result.result_plain = str(bool(truth))
                return result
            target = [s for s in unknowns if s.name == "x"] or unknowns
            if len(target) == 1:
                solution = sp.solve(sp.Eq(lhs, rhs), target[0])
            else:
                solution = sp.solve(sp.Eq(lhs, rhs), target, dict=True)
            self._set_solution(result, solution, target)
            return result

        value = self._finish(parse(source, self.env()))
        if isinstance(value, sp.Rel) and not isinstance(value, (sp.Equality, sp.Unequality)) \
                and value.free_symbols:
            symbols = sorted(value.free_symbols, key=lambda s: s.name)
            solved = sp.reduce_inequalities([value], symbols)
            result.ok = True
            result.kind = "inequality"
            result.input_latex = to_latex(value)
            result.value = solved
            result.result_latex = to_latex(solved)
            result.result_plain = to_plain(solved)
            return result
        if isinstance(value, sp.Lambda):
            raise ParseError("That's a function; call it, e.g. f(2)")
        self.variables["ans"] = value
        result.ok = True
        result.kind = "value"
        result.value = value
        result.input_latex = self._display(source)
        result.result_latex = to_latex(value)
        result.result_plain = to_plain(value)
        self._attach_approx(result, value)
        return result

    def _set_solution(self, result: CalcResult, solution: Any, unknowns: list) -> None:
        if isinstance(solution, list) and solution and not isinstance(solution[0], dict) \
                and len(unknowns) == 1:
            var = sp.latex(unknowns[0])
            result.result_latex = ",\\quad ".join(f"{var} = {to_latex(s)}" for s in solution)
            result.result_plain = ", ".join(f"{unknowns[0]} = {to_plain(s)}" for s in solution)
            approx = [approximate(s, self.digits) for s in solution]
            approx_plain = ", ".join(f"{unknowns[0]} ≈ {format_float(a, self.digits)}"
                                     for a in approx)
            if any(not s.free_symbols and not s.is_Integer for s in solution
                   if isinstance(s, sp.Basic)):
                result.approx_plain = approx_plain
                result.approx_latex = ",\\quad ".join(
                    f"{var} \\approx {_strip_float_zeros(sp.latex(a))}" for a in approx)
        elif not solution:
            result.result_latex = r"\text{no solution}"
            result.result_plain = "no solution"
        else:
            result.result_latex = to_latex(solution)
            result.result_plain = to_plain(solution)
        result.value = solution
        if solution and isinstance(solution, list) and len(unknowns) == 1:
            self.variables["ans"] = solution[0] if len(solution) == 1 else sp.Tuple(*solution)

    def _attach_approx(self, result: CalcResult, value: Any) -> None:
        if isinstance(value, (sp.MatrixBase, bool, dict, list, tuple)):
            if isinstance(value, sp.MatrixBase) and not value.free_symbols and any(
                    not entry.is_Integer for entry in value):
                approx = value.evalf(self.digits)
                result.approx_latex = _strip_float_zeros(sp.latex(approx))
                result.approx_plain = _strip_float_zeros(to_plain(approx))
            return
        if not isinstance(value, sp.Basic) or isinstance(value, (sp.Integer, sp.Float)):
            return
        if value.has(sp.zoo, sp.nan):
            result.note = "Undefined (division by zero or indeterminate form)"
            return
        try:
            approx = value.evalf(self.digits)
        except Exception:  # noqa: BLE001
            return
        if approx == value or sp.sstr(approx) == sp.sstr(value):
            return
        if isinstance(approx, sp.Number) or not approx.free_symbols:
            result.approx_plain = format_float(value, self.digits)
            result.approx_latex = _strip_float_zeros(sp.latex(approx))
        elif any(float(f) != int(float(f)) for f in approx.atoms(sp.Float)):
            result.approx_plain = _strip_float_zeros(to_plain(approx))
            result.approx_latex = _strip_float_zeros(sp.latex(approx))

    # -- persistence
    def to_state(self) -> dict[str, Any]:
        variables = {}
        for name, value in self.variables.items():
            try:
                variables[name] = sp.srepr(value)
            except Exception:  # noqa: BLE001
                continue
        return {
            "variables": variables,
            "functions": {k: [v[0], v[1]] for k, v in self.functions.items()},
            "angle_mode": self.angle_mode,
            "digits": self.digits,
        }

    @classmethod
    def from_state(cls, data: dict[str, Any]) -> CalcSession:
        session = cls()
        if not isinstance(data, dict):
            return session
        session.angle_mode = "deg" if data.get("angle_mode") == "deg" else "rad"
        try:
            session.digits = min(50, max(4, int(data.get("digits", 12))))
        except (TypeError, ValueError):
            session.digits = 12
        for name, raw in (data.get("variables") or {}).items():
            if isinstance(name, str) and isinstance(raw, str) and "__" not in raw:
                try:
                    session.variables[name] = sp.sympify(raw)
                except Exception:  # noqa: BLE001
                    continue
        for name, value in (data.get("functions") or {}).items():
            if (isinstance(value, list) and len(value) == 2
                    and isinstance(value[0], list) and isinstance(value[1], str)):
                session.functions[name] = ([str(p) for p in value[0]], value[1])
        return session


def default_variable(expr: Any) -> sp.Symbol:
    return _default_var(expr)

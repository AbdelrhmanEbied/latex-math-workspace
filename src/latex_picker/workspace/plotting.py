"""Graph expression classification, sampling, analysis and pgfplots export.

GUI-free.  A line of user input is classified into a :class:`PlotSpec`:

* ``explicit``    ``y = f(x)``, a bare ``f(x)`` or a named ``f(x) = ...``
* ``explicit_y``  ``x = g(y)``
* ``vline``       ``x = 3``
* ``parametric``  ``(x(t), y(t))`` optionally followed by ``; t = a..b``
* ``polar``       ``r = f(theta)`` (``θ``/``theta``/``t``)
* ``implicit``    an equation in ``x`` and ``y`` (drawn as a contour)
* ``inequality``  ``y > x^2``, ``x^2 + y^2 <= 4`` (shaded region)
* ``points``      ``(1, 2)`` or ``(1, 2), (3, 4)``

Symbols other than the plotting variables become slider parameters.
"""

from __future__ import annotations

import math
import re
import warnings
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import sympy as sp

from . import mathcore

X, Y, T, THETA, R = sp.symbols("x y t theta r")
PLOT_VARS = {X, Y, T, THETA, R}
DEFAULT_PARAM_RANGE = (-10.0, 10.0)

KIND_LABELS = {
    "explicit": "y = f(x)",
    "explicit_y": "x = g(y)",
    "vline": "vertical line",
    "parametric": "parametric",
    "polar": "polar",
    "implicit": "implicit",
    "inequality": "inequality",
    "points": "points",
    "empty": "",
    "error": "error",
}


@dataclass
class PlotSpec:
    kind: str
    source: str
    expr: Any = None                 # f(x), g(y), (xt, yt), r(theta), F(x,y), value
    params: list[str] = field(default_factory=list)
    error: str = ""
    name: str | None = None          # named function, e.g. "f"
    t_range: tuple[float, float] = (0.0, 2 * math.pi)
    op: str = ""                     # inequality operator: < <= > >=
    boundary: Any = None             # inequality with explicit boundary y op f(x)
    boundary_var: str = ""           # "y" when the inequality reads y op f(x)
    points: list[tuple[float, float]] = field(default_factory=list)
    latex: str = ""

    @property
    def ok(self) -> bool:
        return self.kind not in {"error", "empty"}

    @property
    def is_function(self) -> bool:
        return self.kind == "explicit"

    @property
    def label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------

_RANGE_RE = re.compile(
    r"^(?P<body>.*?)\s*[;,]\s*\{?\s*(?P<var>t|theta|θ)\s*(?:=|∈|in)\s*\[?\s*"
    r"(?P<a>[^,\]]+?)\s*(?:\.\.|,)\s*(?P<b>[^\]\}]+?)\s*\]?\}?\s*$"
)
_NAMED_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*\(\s*x\s*\)\s*$")


def _parse(text: str) -> Any:
    text = text.replace("θ", "theta")
    return mathcore.parse(text)


def _num(text: str) -> float:
    return float(sp.N(_parse(text)))


def _free(*exprs: Any) -> set:
    free: set = set()
    for expr in exprs:
        if isinstance(expr, sp.Basic):
            free |= expr.free_symbols
    return free


def _params(exprs: list[Any], variables: set) -> list[str]:
    names = {s.name for s in _free(*exprs) - variables if isinstance(s, sp.Symbol)}
    return sorted(names)


def _top_level_relation(text: str) -> tuple[str, str, str] | None:
    depth = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif depth == 0 and ch in "<>≤≥":
            if ch == "≤":
                return text[:i], "<=", text[i + 1:]
            if ch == "≥":
                return text[:i], ">=", text[i + 1:]
            if i + 1 < len(text) and text[i + 1] == "=":
                return text[:i], ch + "=", text[i + 2:]
            return text[:i], ch, text[i + 1:]
        i += 1
    return None


def _tuple_items(value: Any) -> list | None:
    if isinstance(value, (tuple, list, sp.Tuple)):
        return list(value)
    return None


def classify(text: str) -> PlotSpec:
    source = text
    text = (text or "").strip()
    if not text:
        return PlotSpec("empty", source)
    text = text.replace("θ", "theta").replace("≤", "<=").replace("≥", ">=")
    try:
        return _classify(text, source)
    except mathcore.ParseError as exc:
        return PlotSpec("error", source, error=str(exc))
    except Exception as exc:  # noqa: BLE001 - surface any parse/CAS problem
        message = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        return PlotSpec("error", source, error=message[:200])


def _classify(text: str, source: str) -> PlotSpec:
    t_range = (0.0, 2 * math.pi)
    match = _RANGE_RE.match(text)
    if match and (match.group("body").lstrip().startswith("(")
                  or match.group("body").lstrip().startswith("r")):
        text = match.group("body").strip()
        t_range = (_num(match.group("a")), _num(match.group("b")))
        if not t_range[1] > t_range[0]:
            raise ValueError("parameter range must be increasing")

    # Tuples: parametric curves and points ---------------------------------
    if text.startswith("("):
        value = None
        try:
            value = _parse(text)
        except mathcore.ParseError:
            value = None
        items = _tuple_items(value)
        if items is not None:
            if all(_tuple_items(item) is not None and len(_tuple_items(item)) == 2
                   for item in items):
                pts = [(float(sp.N(a)), float(sp.N(b))) for a, b in
                       (_tuple_items(item) for item in items)]
                return PlotSpec("points", source, points=pts,
                                latex=", ".join(f"({_fmt(a)}, {_fmt(b)})" for a, b in pts))
            if len(items) == 2:
                xt, yt = (sp.sympify(item) for item in items)
                free = _free(xt, yt)
                if not (free - {T}) - _free(xt, yt) and not free & {T, THETA} and not \
                        _params([xt, yt], set()):
                    pt = (float(sp.N(xt)), float(sp.N(yt)))
                    return PlotSpec("points", source, points=[pt],
                                    latex=f"({_fmt(pt[0])}, {_fmt(pt[1])})")
                if free & {X, Y}:
                    raise ValueError("parametric curves use t, e.g. (cos t, sin t)")
                if THETA in free and T not in free:
                    xt, yt = xt.subs(THETA, T), yt.subs(THETA, T)
                return PlotSpec(
                    "parametric", source, expr=(xt, yt), t_range=t_range,
                    params=_params([xt, yt], {T, THETA}),
                    latex=rf"\left({sp.latex(xt)},\; {sp.latex(yt)}\right)",
                )

    # Inequalities -----------------------------------------------------------
    relation = _top_level_relation(text)
    if relation is not None:
        lhs_text, op, rhs_text = relation
        lhs, rhs = _parse(lhs_text), _parse(rhs_text)
        spec = PlotSpec("inequality", source, expr=sp.expand(lhs - rhs), op=op,
                        latex=f"{sp.latex(lhs)} {_OP_LATEX[op]} {sp.latex(rhs)}")
        spec.params = _params([lhs, rhs], {X, Y})
        if lhs == Y and Y not in _free(rhs):
            spec.boundary, spec.boundary_var = rhs, "y"
        elif rhs == Y and Y not in _free(lhs):
            spec.boundary, spec.boundary_var = lhs, "y"
            spec.op = _FLIP[op]
        return spec

    # Equations --------------------------------------------------------------
    equation = mathcore._split_equation(text)
    if equation is not None:
        lhs_text, rhs_text = (part.strip() for part in equation)
        named = _NAMED_RE.match(lhs_text)
        if lhs_text == "y" or named:
            rhs = _parse(rhs_text)
            if Y in _free(rhs):
                return _implicit(source, Y, rhs)
            name = named.group(1) if named else None
            prefix = f"{name}(x)" if name else "y"
            return PlotSpec("explicit", source, expr=sp.sympify(rhs), name=name,
                            params=_params([rhs], {X, Y}),
                            latex=f"{prefix} = {sp.latex(rhs)}")
        if lhs_text == "x":
            rhs = sp.sympify(_parse(rhs_text))
            free = _free(rhs)
            if X in free:
                return _implicit(source, X, rhs)
            if Y in free:
                return PlotSpec("explicit_y", source, expr=rhs,
                                params=_params([rhs], {X, Y}),
                                latex=f"x = {sp.latex(rhs)}")
            return PlotSpec("vline", source, expr=rhs, params=_params([rhs], {X, Y}),
                            latex=f"x = {sp.latex(rhs)}")
        if lhs_text == "r":
            rhs = sp.sympify(_parse(rhs_text))
            if T in _free(rhs) and THETA not in _free(rhs):
                rhs = rhs.subs(T, THETA)
            if _free(rhs) & {X, Y}:
                raise ValueError("polar curves use theta, e.g. r = 1 + cos(theta)")
            return PlotSpec("polar", source, expr=rhs, t_range=t_range,
                            params=_params([rhs], {THETA}),
                            latex=rf"r = {sp.latex(rhs)}")
        lhs, rhs = _parse(lhs_text), _parse(rhs_text)
        return _implicit(source, lhs, rhs)

    # Bare expressions ---------------------------------------------------------
    expr = sp.sympify(_parse(text))
    if isinstance(expr, sp.Equality):
        return _implicit(source, expr.lhs, expr.rhs)
    if not isinstance(expr, sp.Expr):
        raise ValueError("can't plot that")
    free = _free(expr)
    if Y in free:
        return _implicit(source, expr, sp.Integer(0))
    if THETA in free and X not in free:
        return PlotSpec("polar", source, expr=expr, t_range=t_range,
                        params=_params([expr], {THETA}), latex=f"r = {sp.latex(expr)}")
    return PlotSpec("explicit", source, expr=expr, params=_params([expr], {X, Y}),
                    latex=f"y = {sp.latex(expr)}")


def _implicit(source: str, lhs: Any, rhs: Any) -> PlotSpec:
    lhs, rhs = sp.sympify(lhs), sp.sympify(rhs)
    return PlotSpec("implicit", source, expr=sp.expand(lhs - rhs),
                    params=_params([lhs, rhs], {X, Y}),
                    latex=f"{sp.latex(lhs)} = {sp.latex(rhs)}")


_OP_LATEX = {"<": "<", ">": ">", "<=": r"\leq", ">=": r"\geq"}
_FLIP = {"<": ">", ">": "<", "<=": ">=", ">=": "<="}


def _fmt(value: float) -> str:
    if value is None or not np.isfinite(value):
        return "undefined"
    if abs(value) < 1e-12:
        value = 0.0
    text = f"{value:.6g}"
    return "0" if text == "-0" else text


format_number = _fmt


# --------------------------------------------------------------------------
# Numeric evaluation
# --------------------------------------------------------------------------

def _modules() -> list:
    modules: list = [{"factorial": _np_factorial, "ceiling": np.ceil, "Abs": np.abs,
                      "sign": np.sign}, "numpy"]
    try:
        import scipy  # noqa: F401

        modules.append("scipy")
    except ImportError:
        pass
    return modules


def _np_factorial(value):
    from math import gamma

    return np.vectorize(lambda v: gamma(v + 1) if v > -1 or v != int(v) else np.nan)(value)


def compile_expr(expr: Any, variables: list[sp.Symbol], params: list[str]) -> Callable:
    """Return a numpy function ``f(*variables, **params)``."""
    param_symbols = [sp.Symbol(name) for name in params]
    func = sp.lambdify(list(variables) + param_symbols, expr, modules=_modules())

    def call(*values, **param_values):
        args = list(values) + [float(param_values.get(name, 1.0)) for name in params]
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                out = func(*args)
            except (ZeroDivisionError, ValueError, OverflowError, TypeError):
                out = np.nan
        shape = np.shape(values[0]) if values else ()
        out = np.asarray(out)
        if np.iscomplexobj(out):
            real = out.real.astype(float)
            real[np.abs(out.imag) > 1e-9 * (1 + np.abs(real))] = np.nan
            out = real
        out = out.astype(float, copy=False)
        if out.shape != shape:
            out = np.broadcast_to(out, shape).copy()
        out[~np.isfinite(out)] = np.nan
        return out

    return call


def make_function(spec: PlotSpec, params: dict[str, float] | None = None) -> Callable:
    """Vectorised ``f(x)`` for explicit specs (``g(y)`` for explicit_y)."""
    params = params or {}
    var = Y if spec.kind == "explicit_y" else X
    if spec.kind == "inequality" and spec.boundary is not None:
        expr = spec.boundary
    elif spec.kind in {"explicit", "explicit_y"}:
        expr = spec.expr
    else:
        raise ValueError("not a function of one variable")
    compiled = compile_expr(expr, [var], spec.params)
    return lambda values: compiled(np.asarray(values, dtype=float), **params)


def _break_discontinuities(xs: np.ndarray, ys: np.ndarray, func: Callable,
                           view_height: float) -> tuple[np.ndarray, np.ndarray]:
    if len(xs) < 3:
        return xs, ys
    dy = np.abs(np.diff(ys))
    candidates = np.where(np.isfinite(dy) & (dy > 0.25 * view_height))[0]
    if len(candidates) == 0:
        return xs, ys
    mids_x = (xs[candidates] + xs[candidates + 1]) / 2
    mids_y = func(mids_x)
    low = np.minimum(ys[candidates], ys[candidates + 1])
    high = np.maximum(ys[candidates], ys[candidates + 1])
    tol = 0.05 * (high - low) + 1e-12
    outside = ~((mids_y >= low - tol) & (mids_y <= high + tol))
    y0, y1 = ys[candidates], ys[candidates + 1]
    pole = (y0 * y1 < 0) & (np.minimum(np.abs(y0), np.abs(y1)) > 0.25 * view_height) \
        & (dy[candidates] > view_height)
    broken = candidates[outside | pole]
    if len(broken) == 0:
        return xs, ys
    xs = np.insert(xs, broken + 1, np.nan)
    ys = np.insert(ys, broken + 1, np.nan)
    return xs, ys


def sample_explicit(spec: PlotSpec, params: dict[str, float], xmin: float, xmax: float,
                    ymin: float, ymax: float, n: int = 1500) -> tuple[np.ndarray, np.ndarray]:
    """Sample ``y = f(x)`` (or ``x = g(y)``, returned as (x, y)) over the view."""
    func = make_function(spec, params)
    if spec.kind == "explicit_y":
        ys = np.linspace(ymin, ymax, n)
        xs = func(ys)
        ys2, xs2 = _break_discontinuities(ys, xs, func, xmax - xmin)
        return xs2, ys2
    xs = np.linspace(xmin, xmax, n)
    ys = func(xs)
    return _break_discontinuities(xs, ys, func, ymax - ymin)


def sample_parametric(spec: PlotSpec, params: dict[str, float],
                      n: int = 2000) -> tuple[np.ndarray, np.ndarray]:
    t0, t1 = spec.t_range
    ts = np.linspace(t0, t1, n)
    if spec.kind == "polar":
        r = compile_expr(spec.expr, [THETA], spec.params)(ts, **params)
        return r * np.cos(ts), r * np.sin(ts)
    xt, yt = spec.expr
    xs = compile_expr(xt, [T], spec.params)(ts, **params)
    ys = compile_expr(yt, [T], spec.params)(ts, **params)
    return xs, ys


def sample_grid(spec: PlotSpec, params: dict[str, float], xmin: float, xmax: float,
                ymin: float, ymax: float, n: int = 320):
    xs = np.linspace(xmin, xmax, n)
    ys = np.linspace(ymin, ymax, n)
    gx, gy = np.meshgrid(xs, ys)
    func = compile_expr(spec.expr, [X, Y], spec.params)
    gz = func(gx, gy, **params)
    return gx, gy, gz


def inequality_mask(spec: PlotSpec, gz: np.ndarray) -> np.ndarray:
    op = spec.op
    with np.errstate(invalid="ignore"):
        if op == "<":
            mask = gz < 0
        elif op == "<=":
            mask = gz <= 0
        elif op == ">":
            mask = gz > 0
        else:
            mask = gz >= 0
    return mask & np.isfinite(gz)


def vline_value(spec: PlotSpec, params: dict[str, float]) -> float:
    value = compile_expr(spec.expr, [X], spec.params)(np.array([0.0]), **params)
    return float(value[0])


def contour_lines(gx, gy, gz) -> list[np.ndarray]:
    """Zero-level contour polylines (each an (n, 2) array)."""
    try:
        import contourpy

        z = np.ma.masked_invalid(gz)
        generator = contourpy.contour_generator(gx, gy, z)
        return [line for line in generator.lines(0.0) if len(line) > 1]
    except Exception:  # noqa: BLE001
        return []


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------

def _dedupe(values: list[float], tol: float) -> list[float]:
    result: list[float] = []
    for value in sorted(values):
        if not result or abs(value - result[-1]) > tol:
            result.append(value)
    return result


def find_roots(func: Callable, a: float, b: float, n: int = 2000) -> list[float]:
    from scipy.optimize import brentq, minimize_scalar

    xs = np.linspace(a, b, n)
    ys = func(xs)
    roots: list[float] = []
    span = b - a
    finite = np.isfinite(ys)
    scale = np.nanmax(np.abs(ys[finite])) if finite.any() else 1.0
    for i in range(n - 1):
        y0, y1 = ys[i], ys[i + 1]
        if not (np.isfinite(y0) and np.isfinite(y1)):
            continue
        if y0 == 0:
            roots.append(float(xs[i]))
            continue
        if y0 * y1 < 0:
            try:
                root = brentq(lambda v: float(func(np.array([v]))[0]), xs[i], xs[i + 1],
                              xtol=1e-12, maxiter=200)
            except (ValueError, RuntimeError):
                continue
            value = float(func(np.array([root]))[0])
            # Reject sign changes caused by poles (tan, 1/x).
            if np.isfinite(value) and abs(value) < 1e-6 * (1 + scale):
                roots.append(float(root))
    if np.isfinite(ys[-1]) and ys[-1] == 0:
        roots.append(float(xs[-1]))
    # Touching roots (x^2 at 0): local minima of |f| that reach zero.
    absy = np.abs(ys)
    for i in range(1, n - 1):
        if not (np.isfinite(absy[i - 1]) and np.isfinite(absy[i]) and np.isfinite(absy[i + 1])):
            continue
        if absy[i] <= absy[i - 1] and absy[i] <= absy[i + 1] and ys[i - 1] * ys[i + 1] > 0:
            res = minimize_scalar(lambda v: abs(float(func(np.array([v]))[0])),
                                  bounds=(xs[i - 1], xs[i + 1]), method="bounded",
                                  options={"xatol": 1e-12})
            if res.success and res.fun < 1e-9 * (1 + scale):
                roots.append(float(res.x))
    roots = [0.0 if abs(r) < 1e-10 * (1 + span) else r for r in roots]
    return _dedupe(roots, span * 1e-6 + 1e-9)


def find_extrema(spec: PlotSpec, params: dict[str, float], a: float, b: float,
                 n: int = 2000) -> list[tuple[float, float, str]]:
    from scipy.optimize import minimize_scalar

    func = make_function(spec, params)
    results: list[tuple[float, float, str]] = []
    try:
        deriv = compile_expr(sp.diff(spec.expr, X), [X], spec.params)
        dfunc = lambda v: deriv(np.asarray(v, dtype=float), **params)  # noqa: E731
    except Exception:  # noqa: BLE001
        dfunc = None
    if dfunc is not None:
        for root in find_roots(dfunc, a, b, n):
            h = max(1e-6, (b - a) * 1e-4)
            left, mid, right = func(np.array([root - h, root, root + h]))
            if not all(np.isfinite([left, mid, right])):
                continue
            if mid >= left and mid >= right and not (mid == left == right):
                results.append((root, float(mid), "max"))
            elif mid <= left and mid <= right and not (mid == left == right):
                results.append((root, float(mid), "min"))
        return results
    xs = np.linspace(a, b, n)
    ys = func(xs)
    for i in range(1, n - 1):
        window = ys[i - 1:i + 2]
        if not np.all(np.isfinite(window)):
            continue
        for kind, sign in (("min", 1), ("max", -1)):
            if sign * ys[i] < sign * ys[i - 1] and sign * ys[i] <= sign * ys[i + 1]:
                res = minimize_scalar(lambda v, s=sign: s * float(func(np.array([v]))[0]),
                                      bounds=(xs[i - 1], xs[i + 1]), method="bounded")
                if res.success:
                    results.append((float(res.x), sign * float(res.fun), kind))
    return results


def y_intercept(spec: PlotSpec, params: dict[str, float]) -> float | None:
    value = float(make_function(spec, params)(np.array([0.0]))[0])
    return value if np.isfinite(value) else None


def find_intersections(spec_a: PlotSpec, spec_b: PlotSpec, params: dict[str, float],
                       a: float, b: float) -> list[tuple[float, float]]:
    fa = make_function(spec_a, params)
    fb = make_function(spec_b, params)
    roots = find_roots(lambda v: fa(v) - fb(v), a, b)
    points = []
    for root in roots:
        value = float(fa(np.array([root]))[0])
        if np.isfinite(value):
            points.append((root, value))
    return points


def definite_integral(spec: PlotSpec, params: dict[str, float], a: float,
                      b: float) -> tuple[float, float]:
    from scipy.integrate import quad

    func = make_function(spec, params)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        value, error = quad(lambda v: float(func(np.array([v]))[0]), a, b, limit=200)
    return float(value), float(error)


def derivative_spec(spec: PlotSpec) -> PlotSpec:
    if spec.kind != "explicit":
        raise ValueError("derivatives need y = f(x)")
    deriv = sp.diff(spec.expr, X)
    name = f"{spec.name}'" if spec.name else "y'"
    return PlotSpec("explicit", f"d/dx ({spec.source})", expr=deriv, params=list(spec.params),
                    name=None, latex=f"{name} = {sp.latex(deriv)}")


def tangent_line(spec: PlotSpec, params: dict[str, float],
                 x0: float) -> tuple[float, float, str]:
    """Return (slope, intercept, latex) of the tangent at ``x0``."""
    func = make_function(spec, params)
    y0 = float(func(np.array([x0]))[0])
    try:
        deriv = compile_expr(sp.diff(spec.expr, X), [X], spec.params)
        slope = float(deriv(np.array([float(x0)]), **params)[0])
    except Exception:  # noqa: BLE001
        h = 1e-6
        slope = float((func(np.array([x0 + h]))[0] - func(np.array([x0 - h]))[0]) / (2 * h))
    if not (np.isfinite(y0) and np.isfinite(slope)):
        raise ValueError("the function is not differentiable there")
    intercept = y0 - slope * x0
    sign = "-" if intercept < 0 else "+"
    latex = f"y = {_fmt(slope)}x {sign} {_fmt(abs(intercept))}"
    return slope, intercept, latex


def value_table(spec: PlotSpec, params: dict[str, float], start: float, step: float,
                count: int = 11) -> list[tuple[float, float | None]]:
    func = make_function(spec, params)
    xs = np.array([start + i * step for i in range(count)], dtype=float)
    ys = func(xs)
    return [(float(x), float(y) if np.isfinite(y) else None) for x, y in zip(xs, ys)]


# --------------------------------------------------------------------------
# pgfplots export
# --------------------------------------------------------------------------

_PGF_FUNCS = {
    "sin": "sin", "cos": "cos", "tan": "tan", "cot": "cot", "sec": "sec", "csc": "cosec",
    "asin": "asin", "acos": "acos", "atan": "atan", "sinh": "sinh", "cosh": "cosh",
    "tanh": "tanh", "exp": "exp", "log": "ln", "Abs": "abs", "floor": "floor",
    "ceiling": "ceil", "sign": "sign",
}


def to_pgf(expr: Any) -> str:
    """Convert a sympy expression in ``x`` to pgfplots math syntax."""
    expr = sp.sympify(expr)

    def wrap(e) -> str:
        text = conv(e)
        if e.is_Atom and not (e.is_Number and e < 0):
            return text
        if isinstance(e, sp.Function):
            return text
        return f"({text})"

    def conv(e) -> str:
        if e is sp.pi:
            return "pi"
        if e is sp.E:
            return "e"
        if e.is_Integer:
            return str(int(e))
        if e.is_Rational:
            return f"({e.p}/{e.q})"
        if e.is_Float:
            return f"{float(e):.10g}"
        if e.is_Symbol:
            if e != X:
                raise ValueError(f"unexpected symbol {e}")
            return "x"
        if e.is_Add:
            parts: list[str] = []
            for i, term in enumerate(sp.Add.make_args(e)):
                text = conv(term)
                if i and not text.startswith("-"):
                    parts.append("+")
                parts.append(text)
            return " ".join(parts)
        if e.is_Mul:
            coeff, rest = e.as_coeff_Mul()
            if coeff == -1:
                return "-" + wrap(rest)
            num, den = sp.fraction(e)
            if den != 1:
                return f"{wrap(num)}/{wrap(den)}"
            return "*".join(wrap(arg) for arg in sp.Mul.make_args(e))
        if e.is_Pow:
            base, exponent = e.as_base_exp()
            if exponent == sp.Rational(1, 2):
                return f"sqrt({conv(base)})"
            if exponent == -1:
                return f"1/{wrap(base)}"
            if base is sp.E:
                return f"exp({conv(exponent)})"
            return f"{wrap(base)}^{wrap(exponent)}"
        if isinstance(e, sp.Function):
            name = type(e).__name__
            if name not in _PGF_FUNCS:
                raise ValueError(f"pgfplots has no {name}")
            return f"{_PGF_FUNCS[name]}({', '.join(conv(a) for a in e.args)})"
        raise ValueError(f"can't convert {e}")

    return conv(expr)


def _coords(xs: np.ndarray, ys: np.ndarray, limit: int = 400) -> list[str]:
    """Split sampled data at NaNs into pgfplots coordinate blocks."""
    blocks: list[str] = []
    current: list[str] = []
    step = max(1, len(xs) // limit)
    for x, y in zip(xs[::step], ys[::step]):
        if np.isfinite(x) and np.isfinite(y):
            current.append(f"({x:.5g},{y:.5g})")
        elif current:
            blocks.append(" ".join(current))
            current = []
    if current:
        blocks.append(" ".join(current))
    return blocks


def pgfplots_code(items: list[tuple[PlotSpec, str]], params: dict[str, float],
                  view: tuple[float, float, float, float], grid: bool = True,
                  equal: bool = False) -> str:
    """Build a tikzpicture/axis snippet for ``(spec, hex_color)`` items."""
    xmin, xmax, ymin, ymax = view
    lines = ["% Requires \\usepackage{pgfplots} and \\pgfplotsset{compat=1.18}"]
    colors: list[str] = []
    for index, (_spec, color) in enumerate(items):
        name = f"plotc{index + 1}"
        colors.append(name)
        lines.append(f"\\definecolor{{{name}}}{{HTML}}{{{color.lstrip('#').upper()}}}")
    options = [
        "axis lines=middle", f"xmin={xmin:.4g}", f"xmax={xmax:.4g}",
        f"ymin={ymin:.4g}", f"ymax={ymax:.4g}", "xlabel={$x$}", "ylabel={$y$}",
        "samples=200", "trig format plots=rad", "width=10cm", "height=7cm",
        "restrict y to domain*={:.4g}:{:.4g}".format(ymin - 3 * (ymax - ymin),
                                                   ymax + 3 * (ymax - ymin)),
    ]
    if grid:
        options.append("grid=major")
    if equal:
        options.append("axis equal image")
    lines.append("\\begin{tikzpicture}")
    lines.append("\\begin{axis}[")
    lines.append(",\n".join(f"    {opt}" for opt in options))
    lines.append("]")
    for (spec, _color), cname in zip(items, colors):
        subs = {sp.Symbol(k): v for k, v in params.items()}
        style = f"thick, color={cname}"
        lines.append(f"% {spec.source.strip()}")
        if spec.kind == "explicit":
            try:
                expr = to_pgf(sp.sympify(spec.expr).subs(subs))
                lines.append(f"\\addplot[{style}, domain={xmin:.4g}:{xmax:.4g}] {{{expr}}};")
                continue
            except ValueError:
                pass
        if spec.kind in {"explicit", "explicit_y"}:
            xs, ys = sample_explicit(spec, params, xmin, xmax, ymin, ymax, 600)
            blocks = _coords(xs, ys)
        elif spec.kind in {"parametric", "polar"}:
            xs, ys = sample_parametric(spec, params, 800)
            blocks = _coords(xs, ys)
        elif spec.kind == "vline":
            value = vline_value(spec, params)
            blocks = [f"({value:.5g},{ymin:.5g}) ({value:.5g},{ymax:.5g})"]
        elif spec.kind == "points":
            pts = " ".join(f"({x:.5g},{y:.5g})" for x, y in spec.points)
            lines.append(f"\\addplot[only marks, mark=*, color={cname}] coordinates {{{pts}}};")
            continue
        elif spec.kind in {"implicit", "inequality"}:
            gx, gy, gz = sample_grid(spec, params, xmin, xmax, ymin, ymax, 200)
            blocks = [" ".join(f"({x:.5g},{y:.5g})" for x, y in line[:: max(1, len(line) // 300)])
                      for line in contour_lines(gx, gy, gz)]
            if spec.kind == "inequality":
                style += ", dashed" if spec.op in {"<", ">"} else ""
                lines.append("% (shaded region not exported; boundary only)")
        else:
            continue
        for block in blocks:
            lines.append(f"\\addplot[{style}] coordinates {{{block}}};")
    lines.append("\\end{axis}")
    lines.append("\\end{tikzpicture}")
    return "\n".join(lines)

"""Button palettes for the LaTeX editor.

Each button has a Unicode label (what the button shows), a LaTeX template
(what is inserted) and a name used for tooltips and search.  ``⬚`` (U+2B1A)
marks a placeholder: after insertion the first placeholder is selected and
Tab jumps to the next one.  When text is selected while a template is
inserted, the selection replaces the first placeholder.
"""

from __future__ import annotations

from dataclasses import dataclass

PH = "⬚"


@dataclass(frozen=True)
class PaletteButton:
    label: str
    latex: str
    name: str = ""
    keywords: str = ""
    kind: str = "key"  # key | op | wide | builder

    def search_text(self) -> str:
        return f"{self.label} {self.latex} {self.name} {self.keywords}".casefold()


@dataclass(frozen=True)
class PaletteCategory:
    id: str
    name: str
    icon: str
    buttons: tuple[PaletteButton, ...]


def _b(label: str, latex: str, name: str = "", keywords: str = "", kind: str = "key") -> PaletteButton:
    return PaletteButton(label, latex, name or label, keywords, kind)


def _op(label: str, latex: str, name: str = "", keywords: str = "") -> PaletteButton:
    return PaletteButton(label, latex, name or label, keywords, "op")


def _w(label: str, latex: str, name: str = "", keywords: str = "") -> PaletteButton:
    return PaletteButton(label, latex, name or label, keywords, "wide")


def _matrix(env: str, rows: int, cols: int, fill: str = PH) -> str:
    body = r" \\ ".join(" & ".join(fill for _ in range(cols)) for _ in range(rows))
    return f"\\begin{{{env}}} {body} \\end{{{env}}}"


def _augmented(rows: int, cols: int) -> str:
    spec = "c" * (cols - 1) + "|c"
    body = r" \\ ".join(" & ".join(PH for _ in range(cols)) for _ in range(rows))
    return f"\\left[\\begin{{array}}{{{spec}}} {body} \\end{{array}}\\right]"


BASIC = (
    *[_b(str(d), str(d), f"digit {d}") for d in (7, 8, 9)],
    _op("+", "+", "plus"), _op("−", "-", "minus"),
    *[_b(str(d), str(d), f"digit {d}") for d in (4, 5, 6)],
    _op("×", r"\times ", "times", "multiply"), _op("÷", r"\div ", "divide"),
    *[_b(str(d), str(d), f"digit {d}") for d in (1, 2, 3)],
    _op("·", r"\cdot ", "dot product", "multiply cdot"), _op("=", "=", "equals"),
    _b("0", "0", "digit 0"), _b(".", ".", "decimal point"), _b(",", ",", "comma"),
    _op("≠", r"\neq ", "not equal"), _op("±", r"\pm ", "plus minus"),
    _b("( )", r"\left( " + PH + r" \right)", "parentheses", "brackets"),
    _b("[ ]", r"\left[ " + PH + r" \right]", "square brackets"),
    _b("{ }", r"\left\{ " + PH + r" \right\}", "braces", "curly"),
    _b("(", "(", "open parenthesis"), _b(")", ")", "close parenthesis"),
    _b("|x|", r"\left| " + PH + r" \right|", "absolute value", "abs"),
    _b("!", "!", "factorial"),
    _b("a/b", r"\frac{" + PH + "}{" + PH + "}", "fraction", "frac divide"),
    _b("xⁿ", "^{" + PH + "}", "power", "superscript exponent"),
    _b("x²", "^{2}", "squared", "power"),
    _b("xₙ", "_{" + PH + "}", "subscript", "index"),
    _b("√", r"\sqrt{" + PH + "}", "square root", "sqrt"),
    *[_b(ch, ch, f"variable {ch}") for ch in "xyznabc"],
    _b("i", "i", "imaginary unit"), _b("e", "e", "Euler's number"),
    _b("π", r"\pi ", "pi"), _b("∞", r"\infty ", "infinity"),
    _op("<", "<", "less than"), _op(">", ">", "greater than"),
    _op("≤", r"\leq ", "less or equal"), _op("≥", r"\geq ", "greater or equal"),
    _op("≈", r"\approx ", "approximately"),
)

STRUCTURES = (
    _b("a⁄b", r"\frac{" + PH + "}{" + PH + "}", "fraction", "frac"),
    _b("a/b", PH + "/" + PH, "inline fraction", "slash"),
    _b("d⁄frac", r"\dfrac{" + PH + "}{" + PH + "}", "display fraction", "dfrac"),
    _b("xⁿ", PH + "^{" + PH + "}", "power", "superscript"),
    _b("xₙ", PH + "_{" + PH + "}", "subscript"),
    _b("xₙᵐ", PH + "_{" + PH + "}^{" + PH + "}", "sub and superscript", "both scripts"),
    _b("eˣ", "e^{" + PH + "}", "exponential", "e power"),
    _b("10ˣ", r"10^{" + PH + "}", "power of ten"),
    _b("√x", r"\sqrt{" + PH + "}", "square root", "sqrt"),
    _b("ⁿ√x", r"\sqrt[" + PH + "]{" + PH + "}", "nth root", "root"),
    _b("∛x", r"\sqrt[3]{" + PH + "}", "cube root"),
    _b("(x)", r"\left( " + PH + r" \right)", "auto-sized parentheses", "left right"),
    _b("[x]", r"\left[ " + PH + r" \right]", "auto-sized brackets"),
    _b("{x}", r"\left\{ " + PH + r" \right\}", "auto-sized braces"),
    _b("⟨x⟩", r"\left\langle " + PH + r" \right\rangle", "angle brackets"),
    _b("|x|", r"\left| " + PH + r" \right|", "absolute value", "abs"),
    _b("‖x‖", r"\left\| " + PH + r" \right\|", "norm"),
    _b("⌊x⌋", r"\left\lfloor " + PH + r" \right\rfloor", "floor"),
    _b("⌈x⌉", r"\left\lceil " + PH + r" \right\rceil", "ceiling", "ceil"),
    _b("(ⁿₖ)", r"\binom{" + PH + "}{" + PH + "}", "binomial coefficient", "choose binom"),
    _b("x̄", r"\overline{" + PH + "}", "overline", "conjugate mean"),
    _b("x̲", r"\underline{" + PH + "}", "underline"),
    _b("x̂", r"\hat{" + PH + "}", "hat", "unit vector"),
    _b("x̂̂", r"\widehat{" + PH + "}", "wide hat"),
    _b("x̄₁", r"\bar{" + PH + "}", "bar"),
    _b("x⃗", r"\vec{" + PH + "}", "vector arrow", "vec"),
    _b("AB⃗", r"\overrightarrow{" + PH + "}", "over right arrow", "vector"),
    _b("ẋ", r"\dot{" + PH + "}", "dot accent", "time derivative"),
    _b("ẍ", r"\ddot{" + PH + "}", "double dot accent"),
    _b("x̃", r"\tilde{" + PH + "}", "tilde"),
    _b("x̃̃", r"\widetilde{" + PH + "}", "wide tilde"),
    _b("x′", PH + "'", "prime", "derivative"),
    _b("x″", PH + "''", "double prime"),
    _w("⏟ label", r"\underbrace{" + PH + "}_{" + PH + "}", "underbrace with label"),
    _w("⏞ label", r"\overbrace{" + PH + "}^{" + PH + "}", "overbrace with label"),
    _b("ᵃ=", r"\overset{" + PH + "}{" + PH + "}", "overset"),
    _b("=ₐ", r"\underset{" + PH + "}{" + PH + "}", "underset"),
    _b("≝", r"\stackrel{" + PH + "}{" + PH + "}", "stackrel"),
    _w("text", r"\text{" + PH + "}", "text", "words roman"),
    _w("□ box", r"\boxed{" + PH + "}", "boxed", "answer"),
    _w("cancel", r"\cancel{" + PH + "}", "cancel", "strike"),
    _w("cases 2", r"\begin{cases} " + PH + r" & \text{if } " + PH + r" \\ " + PH
       + r" & \text{otherwise} \end{cases}", "cases (2 rows)", "piecewise"),
    _w("cases 3", r"\begin{cases} " + PH + " & " + PH + r" \\ " + PH + " & " + PH
       + r" \\ " + PH + " & " + PH + r" \end{cases}", "cases (3 rows)", "piecewise"),
    _w("aligned", r"\begin{aligned} " + PH + " &= " + PH + r" \\ &= " + PH
       + r" \end{aligned}", "aligned equations", "align steps"),
    _w("substack", r"\substack{" + PH + r" \\ " + PH + "}", "substack", "multi-line limits"),
    _b("f(x)", PH + r"\left( " + PH + r" \right)", "function application"),
    _b("f∘g", PH + r" \circ " + PH, "composition"),
)

_GREEK_LOWER = [
    ("α", "alpha"), ("β", "beta"), ("γ", "gamma"), ("δ", "delta"), ("ϵ", "epsilon"),
    ("ε", "varepsilon"), ("ζ", "zeta"), ("η", "eta"), ("θ", "theta"), ("ϑ", "vartheta"),
    ("ι", "iota"), ("κ", "kappa"), ("λ", "lambda"), ("μ", "mu"), ("ν", "nu"),
    ("ξ", "xi"), ("ο", "omicron"), ("π", "pi"), ("ϖ", "varpi"), ("ρ", "rho"),
    ("ϱ", "varrho"), ("σ", "sigma"), ("ς", "varsigma"), ("τ", "tau"), ("υ", "upsilon"),
    ("ϕ", "phi"), ("φ", "varphi"), ("χ", "chi"), ("ψ", "psi"), ("ω", "omega"),
]
_GREEK_UPPER = [
    ("Γ", "Gamma"), ("Δ", "Delta"), ("Θ", "Theta"), ("Λ", "Lambda"), ("Ξ", "Xi"),
    ("Π", "Pi"), ("Σ", "Sigma"), ("Υ", "Upsilon"), ("Φ", "Phi"), ("Ψ", "Psi"),
    ("Ω", "Omega"),
]
GREEK = tuple(
    _b(ch, "o" if name == "omicron" else f"\\{name} ", name, "greek")
    for ch, name in _GREEK_LOWER + _GREEK_UPPER
)

RELATIONS = tuple(_op(label, latex + " ", name, kw) for label, latex, name, kw in [
    ("=", "=", "equals", ""), ("≠", r"\neq", "not equal", ""),
    ("<", "<", "less than", ""), (">", ">", "greater than", ""),
    ("≤", r"\leq", "less or equal", "le"), ("≥", r"\geq", "greater or equal", "ge"),
    ("⩽", r"\leqslant", "slanted less or equal", ""), ("⩾", r"\geqslant", "slanted greater or equal", ""),
    ("≪", r"\ll", "much less", ""), ("≫", r"\gg", "much greater", ""),
    ("≈", r"\approx", "approximately", ""), ("≡", r"\equiv", "equivalent", "congruent mod"),
    ("≅", r"\cong", "congruent", "isomorphic"), ("∼", r"\sim", "similar", "distributed"),
    ("≃", r"\simeq", "asymptotically equal", ""), ("∝", r"\propto", "proportional", ""),
    ("≺", r"\prec", "precedes", ""), ("≻", r"\succ", "succeeds", ""),
    ("⪯", r"\preceq", "precedes or equal", ""), ("⪰", r"\succeq", "succeeds or equal", ""),
    ("⊥", r"\perp", "perpendicular", "orthogonal"), ("∥", r"\parallel", "parallel", ""),
    ("∣", r"\mid", "divides", "such that"), ("∤", r"\nmid", "does not divide", ""),
    ("⊂", r"\subset", "subset", ""), ("⊆", r"\subseteq", "subset or equal", ""),
    ("⊊", r"\subsetneq", "proper subset", ""), ("⊃", r"\supset", "superset", ""),
    ("⊇", r"\supseteq", "superset or equal", ""), ("∈", r"\in", "element of", "in"),
    ("∉", r"\notin", "not element of", ""), ("∋", r"\ni", "contains", ""),
    ("≔", r":=", "defined as", "colon equals"), ("≜", r"\triangleq", "defined equal", ""),
    ("≐", r"\doteq", "approaches the limit", ""), ("≍", r"\asymp", "asymptotic", ""),
    ("⊢", r"\vdash", "proves", "turnstile"), ("⊨", r"\models", "models", "entails"),
    ("≮", r"\not<", "not less", ""), ("≰", r"\nleq", "not less or equal", ""),
    ("≁", r"\nsim", "not similar", ""), ("≇", r"\ncong", "not congruent", ""),
])

OPERATORS = tuple(_op(label, latex + " ", name, kw) for label, latex, name, kw in [
    ("+", "+", "plus", ""), ("−", "-", "minus", ""), ("±", r"\pm", "plus minus", ""),
    ("∓", r"\mp", "minus plus", ""), ("×", r"\times", "times", "cross product"),
    ("÷", r"\div", "divide", ""), ("·", r"\cdot", "center dot", "dot product"),
    ("∘", r"\circ", "composition", "ring"), ("∗", r"\ast", "asterisk", "convolution"),
    ("⋆", r"\star", "star", ""), ("•", r"\bullet", "bullet", ""),
    ("⊕", r"\oplus", "direct sum", "xor"), ("⊖", r"\ominus", "circled minus", ""),
    ("⊗", r"\otimes", "tensor product", "kronecker"), ("⊙", r"\odot", "circled dot", "hadamard"),
    ("⊘", r"\oslash", "circled slash", ""), ("∪", r"\cup", "union", ""),
    ("∩", r"\cap", "intersection", ""), ("∖", r"\setminus", "set minus", "difference"),
    ("⊔", r"\sqcup", "disjoint union", ""), ("△", r"\triangle", "symmetric difference", "triangle"),
    ("∧", r"\wedge", "and", "wedge"), ("∨", r"\vee", "or", "vee"), ("¬", r"\neg", "not", "negation"),
    ("†", r"\dagger", "dagger", "adjoint"), ("‡", r"\ddagger", "double dagger", ""),
    ("⋉", r"\ltimes", "semidirect product", ""), ("≀", r"\wr", "wreath product", ""),
    ("⨿", r"\amalg", "amalgamation", "coproduct"), ("mod", r"\bmod", "modulo", "mod"),
    ("∑", r"\sum", "sum", ""), ("∏", r"\prod", "product", ""), ("∐", r"\coprod", "coproduct", ""),
    ("⋃", r"\bigcup", "big union", ""), ("⋂", r"\bigcap", "big intersection", ""),
    ("⨁", r"\bigoplus", "big direct sum", ""), ("⨂", r"\bigotimes", "big tensor", ""),
    ("⋁", r"\bigvee", "big or", ""), ("⋀", r"\bigwedge", "big and", ""),
])

CALCULUS = (
    _b("∫", r"\int " + PH + r" \, d" + PH, "integral", "indefinite"),
    _b("∫ₐᵇ", r"\int_{" + PH + "}^{" + PH + "} " + PH + r" \, d" + PH, "definite integral", "bounds"),
    _b("∫₀^∞", r"\int_{0}^{\infty} " + PH + r" \, d" + PH, "integral 0 to infinity"),
    _b("∬", r"\iint_{" + PH + "} " + PH + r" \, dA", "double integral"),
    _b("∭", r"\iiint_{" + PH + "} " + PH + r" \, dV", "triple integral"),
    _b("∮", r"\oint_{" + PH + "} " + PH + r" \, d" + PH, "contour integral", "line"),
    _b("d/dx", r"\frac{d}{dx} ", "derivative d/dx"),
    _b("d⁄d⬚", r"\frac{d" + PH + "}{d" + PH + "}", "derivative dy/dx", "leibniz"),
    _b("dⁿ/dxⁿ", r"\frac{d^{" + PH + "}" + PH + "}{d" + PH + "^{" + PH + "}}", "nth derivative"),
    _b("∂/∂x", r"\frac{\partial " + PH + r"}{\partial " + PH + "}", "partial derivative"),
    _b("∂²/∂x²", r"\frac{\partial^2 " + PH + r"}{\partial " + PH + "^2}", "second partial derivative"),
    _b("∂²/∂x∂y", r"\frac{\partial^2 " + PH + r"}{\partial " + PH + r" \, \partial " + PH + "}",
       "mixed partial derivative"),
    _b("f′(x)", PH + "'(" + PH + ")", "prime derivative", "f prime"),
    _b("f″(x)", PH + "''(" + PH + ")", "second derivative", "double prime"),
    _b("ẏ", r"\dot{" + PH + "}", "time derivative", "dot"),
    _b("dx", r"\, dx", "differential dx"),
    _b("∇", r"\nabla ", "nabla", "gradient del"),
    _b("∇·", r"\nabla \cdot ", "divergence"),
    _b("∇×", r"\nabla \times ", "curl"),
    _b("∇²", r"\nabla^2 ", "laplacian"),
    _b("Δ", r"\Delta ", "Delta", "change laplacian"),
    _b("∂", r"\partial ", "partial"),
    _b("lim", r"\lim_{" + PH + r" \to " + PH + "} ", "limit"),
    _b("lim∞", r"\lim_{" + PH + r" \to \infty} ", "limit to infinity"),
    _b("lim⁺", r"\lim_{" + PH + r" \to " + PH + "^{+}} ", "right-hand limit"),
    _b("lim⁻", r"\lim_{" + PH + r" \to " + PH + "^{-}} ", "left-hand limit"),
    _b("lim sup", r"\limsup_{" + PH + r" \to \infty} ", "limit superior"),
    _b("Σ", r"\sum ", "sum"),
    _b("Σᵢ₌₁ⁿ", r"\sum_{" + PH + "=" + PH + "}^{" + PH + "} ", "sum with bounds"),
    _b("Σ∞", r"\sum_{n=1}^{\infty} ", "infinite series"),
    _b("Π", r"\prod_{" + PH + "=" + PH + "}^{" + PH + "} ", "product with bounds"),
    _b("∞", r"\infty ", "infinity"),
    _b("→", r"\to ", "tends to"),
    _b("|ₐᵇ", r"\Big|_{" + PH + "}^{" + PH + "}", "evaluated at", "evaluation bar"),
    _b("O(n)", r"\mathcal{O}\left( " + PH + r" \right)", "big O"),
    _b("e^x", r"e^{" + PH + "}", "exponential"),
)

FUNCTIONS = tuple(
    _b(name, f"\\{name}" + r"\left( " + PH + r" \right)", name, "function")
    for name in ["sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan",
                 "sinh", "cosh", "tanh", "coth", "ln", "log", "exp"]
) + (
    _b("logᵦ", r"\log_{" + PH + r"}\left( " + PH + r" \right)", "log base b", "logarithm"),
    _b("sin²", r"\sin^{2}\left( " + PH + r" \right)", "sine squared"),
    _b("sin⁻¹", r"\sin^{-1}\left( " + PH + r" \right)", "inverse sine"),
    *[_b(name, f"\\{name} ", name, "operator") for name in
      ["det", "dim", "ker", "deg", "max", "min", "sup", "inf", "arg", "gcd", "Pr", "hom"]],
    _b("max_x", r"\max_{" + PH + "} ", "max with subscript"),
    _b("argmax", r"\operatorname*{arg\,max}_{" + PH + "} ", "argmax"),
    _b("argmin", r"\operatorname*{arg\,min}_{" + PH + "} ", "argmin"),
    _b("mod", r"\pmod{" + PH + "}", "parenthesised mod", "pmod congruence"),
    _b("op", r"\operatorname{" + PH + "}", "custom operator name", "operatorname"),
    _b("tr", r"\operatorname{tr}", "trace"),
    _b("rank", r"\operatorname{rank}", "rank"),
    _b("sgn", r"\operatorname{sgn}", "sign"),
    _b("f(x)", r"f\left( " + PH + r" \right)", "f of x"),
    _b("f:A→B", PH + r" \colon " + PH + r" \to " + PH, "function signature", "map"),
)

SETS = (
    _b("∅", r"\emptyset ", "empty set"), _b("∅̸", r"\varnothing ", "varnothing", "empty"),
    _b("ℕ", r"\mathbb{N}", "natural numbers"), _b("ℤ", r"\mathbb{Z}", "integers"),
    _b("ℚ", r"\mathbb{Q}", "rationals"), _b("ℝ", r"\mathbb{R}", "real numbers", "reals"),
    _b("ℂ", r"\mathbb{C}", "complex numbers"), _b("ℝⁿ", r"\mathbb{R}^{" + PH + "}", "R^n"),
    _b("𝔽", r"\mathbb{F}", "field"), _b("ℙ", r"\mathbb{P}", "probability", "primes"),
    _b("𝔼", r"\mathbb{E}", "expectation"),
    _op("∀", r"\forall ", "for all"), _op("∃", r"\exists ", "exists"),
    _op("∄", r"\nexists ", "does not exist"), _op("∃!", r"\exists! ", "exists unique"),
    _op("∈", r"\in ", "element of"), _op("∉", r"\notin ", "not in"),
    _op("⊂", r"\subset ", "subset"), _op("⊆", r"\subseteq ", "subset or equal"),
    _op("∪", r"\cup ", "union"), _op("∩", r"\cap ", "intersection"),
    _op("∖", r"\setminus ", "set difference"), _op("ᶜ", "^{c}", "complement"),
    _op("⇒", r"\Rightarrow ", "implies"), _op("⇐", r"\Leftarrow ", "implied by"),
    _op("⇔", r"\Leftrightarrow ", "if and only if", "iff"),
    _op("⟹", r"\implies ", "implies (long)"), _op("⟺", r"\iff ", "iff (long)"),
    _op("∴", r"\therefore ", "therefore"), _op("∵", r"\because ", "because"),
    _op("∧", r"\land ", "logical and"), _op("∨", r"\lor ", "logical or"),
    _op("¬", r"\neg ", "not"), _op("⊤", r"\top ", "true", "top"), _op("⊥", r"\bot ", "false", "bottom"),
    _w("{x ∣ …}", r"\left\{ " + PH + r" \mid " + PH + r" \right\}", "set builder", "such that"),
    _w("{a, b}", r"\left\{ " + PH + ", " + PH + r" \right\}", "finite set"),
    _b("[a,b]", r"\left[ " + PH + ", " + PH + r" \right]", "closed interval"),
    _b("(a,b)", r"\left( " + PH + ", " + PH + r" \right)", "open interval"),
    _b("[a,b)", r"\left[ " + PH + ", " + PH + r" \right)", "half-open interval"),
    _b("|A|", r"\left| " + PH + r" \right|", "cardinality"),
    _b("𝒫(A)", r"\mathcal{P}\left( " + PH + r" \right)", "power set"),
    _b("A×B", PH + r" \times " + PH, "cartesian product"),
    _b("ℵ₀", r"\aleph_0 ", "aleph null", "cardinal"),
)

ARROWS = tuple(_op(label, latex + " ", name, kw) for label, latex, name, kw in [
    ("→", r"\to", "to", "right arrow"), ("←", r"\leftarrow", "left arrow", "gets"),
    ("↔", r"\leftrightarrow", "left right arrow", ""), ("⇒", r"\Rightarrow", "implies", ""),
    ("⇐", r"\Leftarrow", "implied by", ""), ("⇔", r"\Leftrightarrow", "iff", ""),
    ("↦", r"\mapsto", "maps to", ""), ("↪", r"\hookrightarrow", "injection", "hook"),
    ("↠", r"\twoheadrightarrow", "surjection", ""), ("⟶", r"\longrightarrow", "long right arrow", ""),
    ("⟵", r"\longleftarrow", "long left arrow", ""), ("⟷", r"\longleftrightarrow", "long left right", ""),
    ("⟹", r"\Longrightarrow", "long implies", ""), ("⟸", r"\Longleftarrow", "long implied by", ""),
    ("⟼", r"\longmapsto", "long maps to", ""), ("↑", r"\uparrow", "up arrow", ""),
    ("↓", r"\downarrow", "down arrow", ""), ("↕", r"\updownarrow", "up down arrow", ""),
    ("⇑", r"\Uparrow", "double up", ""), ("⇓", r"\Downarrow", "double down", ""),
    ("↗", r"\nearrow", "north east", "increasing"), ("↘", r"\searrow", "south east", "decreasing"),
    ("↖", r"\nwarrow", "north west", ""), ("↙", r"\swarrow", "south west", ""),
    ("⇌", r"\rightleftharpoons", "equilibrium", "reversible reaction"),
    ("⇀", r"\rightharpoonup", "harpoon", "weak convergence"),
    ("↺", r"\circlearrowleft", "counterclockwise", ""), ("↻", r"\circlearrowright", "clockwise", ""),
]) + (
    _w("→ᵃ", r"\xrightarrow{" + PH + "}", "labelled arrow", "xrightarrow"),
    _w("←ᵃ", r"\xleftarrow{" + PH + "}", "labelled left arrow", "xleftarrow"),
    _w("=ᵈᵉᶠ", r"\overset{\text{def}}{=}", "defined equals"),
)

MATRICES = (
    PaletteButton("▦ Matrix builder…", "", "Matrix builder: choose rows, columns and type",
                  "matrix builder custom size", "builder"),
    _w("(2×2)", _matrix("pmatrix", 2, 2), "2×2 matrix (parentheses)", "pmatrix"),
    _w("[2×2]", _matrix("bmatrix", 2, 2), "2×2 matrix (brackets)", "bmatrix"),
    _w("|2×2|", _matrix("vmatrix", 2, 2), "2×2 determinant", "vmatrix det"),
    _w("(3×3)", _matrix("pmatrix", 3, 3), "3×3 matrix (parentheses)", "pmatrix"),
    _w("[3×3]", _matrix("bmatrix", 3, 3), "3×3 matrix (brackets)", "bmatrix"),
    _w("|3×3|", _matrix("vmatrix", 3, 3), "3×3 determinant", "vmatrix det"),
    _w("‖2×2‖", _matrix("Vmatrix", 2, 2), "double bar matrix", "Vmatrix norm"),
    _w("{2×2}", _matrix("Bmatrix", 2, 2), "braced matrix", "Bmatrix"),
    _w("col 2", _matrix("bmatrix", 2, 1), "column vector (2)", "vector"),
    _w("col 3", _matrix("bmatrix", 3, 1), "column vector (3)", "vector"),
    _w("row 3", _matrix("bmatrix", 1, 3), "row vector (3)", "vector"),
    _w("I₃", r"\begin{bmatrix} 1 & 0 & 0 \\ 0 & 1 & 0 \\ 0 & 0 & 1 \end{bmatrix}",
       "3×3 identity matrix", "identity"),
    _w("I₂", r"\begin{bmatrix} 1 & 0 \\ 0 & 1 \end{bmatrix}", "2×2 identity matrix", "identity"),
    _w("[A|b] 2×3", _augmented(2, 3), "augmented matrix 2×3", "system augmented"),
    _w("[A|b] 3×4", _augmented(3, 4), "augmented matrix 3×4", "system augmented"),
    _w("n×n …",
       r"\begin{bmatrix} a_{11} & a_{12} & \cdots & a_{1n} \\ a_{21} & a_{22} & \cdots & a_{2n} "
       r"\\ \vdots & \vdots & \ddots & \vdots \\ a_{m1} & a_{m2} & \cdots & a_{mn} \end{bmatrix}",
       "general m×n matrix with dots", "generic"),
    _w("diag", r"\begin{bmatrix} " + PH + r" & & \\ & \ddots & \\ & & " + PH + r" \end{bmatrix}",
       "diagonal matrix", "diagonal"),
    _b("Aᵀ", "^{T}", "transpose"), _b("A⁻¹", "^{-1}", "inverse"),
    _b("A*", r"^{*}", "conjugate transpose", "adjoint"), _b("A†", r"^{\dagger}", "dagger", "hermitian"),
    _b("det", r"\det\left( " + PH + r" \right)", "determinant"),
    _b("tr", r"\operatorname{tr}\left( " + PH + r" \right)", "trace"),
    _b("rank", r"\operatorname{rank}\left( " + PH + r" \right)", "rank"),
    _b("⟨u,v⟩", r"\langle " + PH + ", " + PH + r" \rangle", "inner product"),
    _b("u·v", PH + r" \cdot " + PH, "dot product"),
    _b("u×v", PH + r" \times " + PH, "cross product"),
    _b("‖v‖", r"\| " + PH + r" \|", "norm"),
    _b("𝐯", r"\mathbf{" + PH + "}", "bold vector"),
    _b("v⃗", r"\vec{" + PH + "}", "arrow vector"),
    _b("𝟎", r"\mathbf{0}", "zero vector"),
    _b("Rᵢ↔Rⱼ", r"R_{" + PH + r"} \leftrightarrow R_{" + PH + "}", "row swap"),
    _b("Rᵢ←kRᵢ", r"R_{" + PH + r"} \leftarrow " + PH + r" R_{" + PH + "}", "row scale"),
)

FONTS = (
    _b("𝐀", r"\mathbf{" + PH + "}", "bold", "mathbf"),
    _b("𝔸", r"\mathbb{" + PH + "}", "blackboard bold", "mathbb"),
    _b("𝒜", r"\mathcal{" + PH + "}", "calligraphic", "mathcal"),
    _b("𝔄", r"\mathfrak{" + PH + "}", "fraktur", "mathfrak"),
    _b("𝒜ₛ", r"\mathscr{" + PH + "}", "script", "mathscr"),
    _b("A", r"\mathrm{" + PH + "}", "roman (upright)", "mathrm"),
    _b("𝐴", r"\mathit{" + PH + "}", "italic", "mathit"),
    _b("𝜶", r"\boldsymbol{" + PH + "}", "bold symbol", "boldsymbol greek"),
    _b("𝖠", r"\mathsf{" + PH + "}", "sans-serif", "mathsf"),
    _b("𝙰", r"\mathtt{" + PH + "}", "typewriter", "mathtt monospace"),
    _w("text", r"\text{" + PH + "}", "text"),
    _w("textbf", r"\textbf{" + PH + "}", "bold text"),
    _b("â", r"\hat{" + PH + "}", "hat"), _b("ā", r"\bar{" + PH + "}", "bar"),
    _b("ã", r"\tilde{" + PH + "}", "tilde"), _b("ȧ", r"\dot{" + PH + "}", "dot"),
    _b("ä", r"\ddot{" + PH + "}", "double dot"), _b("a⃗", r"\vec{" + PH + "}", "vector"),
    _b("ǎ", r"\check{" + PH + "}", "check"), _b("ă", r"\breve{" + PH + "}", "breve"),
    _b("á", r"\acute{" + PH + "}", "acute"), _b("à", r"\grave{" + PH + "}", "grave"),
    _b("å", r"\mathring{" + PH + "}", "ring"),
)

SPACING = (
    _w("thin \\,", r"\,", "thin space"), _w("med \\:", r"\:", "medium space"),
    _w("thick \\;", r"\;", "thick space"), _w("quad", r"\quad ", "quad space"),
    _w("qquad", r"\qquad ", "double quad space"), _w("neg \\!", r"\!", "negative thin space"),
    _w("newline \\\\", " \\\\\n", "line break"), _w("align &", " & ", "alignment point"),
    _b("⋯", r"\cdots ", "centered dots"), _b("…", r"\ldots ", "low dots"),
    _b("⋮", r"\vdots ", "vertical dots"), _b("⋱", r"\ddots ", "diagonal dots"),
    _b("°", r"^{\circ}", "degree"), _b("′", "'", "prime"),
    _b("ℓ", r"\ell ", "script l"), _b("ℏ", r"\hbar ", "h-bar"),
    _b("∠", r"\angle ", "angle"), _b("△", r"\triangle ", "triangle"),
    _b("□", r"\square ", "square"), _b("■", r"\blacksquare ", "QED", "end proof"),
    _b("✓", r"\checkmark ", "check mark"), _b("★", r"\bigstar ", "star"),
    _b("ℜ", r"\Re ", "real part"), _b("ℑ", r"\Im ", "imaginary part"),
    _b("℘", r"\wp ", "Weierstrass p"), _b("ð", r"\eth ", "eth"),
    _b("%", r"\%", "percent"), _b("$", r"\$", "dollar"), _b("#", r"\#", "hash"),
    _b("&", r"\&", "ampersand"), _b("_", r"\_", "underscore"),
    _b("{", r"\{", "literal brace"), _b("}", r"\}", "literal brace"),
    _w("tag", r"\tag{" + PH + "}", "equation tag"),
    _w("≡ (mod)", r"\equiv " + PH + r" \pmod{" + PH + "}", "congruence"),
)

PHYSICS = (
    _b("ℏ", r"\hbar ", "reduced Planck constant"),
    _b("⟨ψ|", r"\langle " + PH + r" |", "bra"),
    _b("|ψ⟩", r"| " + PH + r" \rangle", "ket"),
    _b("⟨φ|ψ⟩", r"\langle " + PH + r" | " + PH + r" \rangle", "bra-ket inner product"),
    _b("⟨A⟩", r"\langle " + PH + r" \rangle", "expectation value"),
    _b("⟨φ|A|ψ⟩", r"\langle " + PH + r" | " + PH + r" | " + PH + r" \rangle", "matrix element"),
    _b("Â", r"\hat{" + PH + "}", "operator hat"),
    _b("[A,B]", r"\left[ " + PH + ", " + PH + r" \right]", "commutator"),
    _b("∂ₜ", r"\partial_t ", "time partial"),
    _b("∂_μ", r"\partial_{\mu} ", "four-gradient"),
    _b("∇²", r"\nabla^2 ", "Laplacian"),
    _b("□", r"\Box ", "d'Alembertian"),
    _b("δᵢⱼ", r"\delta_{ij}", "Kronecker delta"),
    _b("εᵢⱼₖ", r"\varepsilon_{ijk}", "Levi-Civita"),
    _b("γ^μ", r"\gamma^{\mu}", "gamma matrix"),
    _b("Δx", r"\Delta x", "uncertainty"),
    _w("m/s", r"\,\mathrm{m/s}", "metres per second", "unit velocity"),
    _w("m/s²", r"\,\mathrm{m/s^2}", "acceleration unit"),
    _w("kg", r"\,\mathrm{kg}", "kilogram"),
    _w("N", r"\,\mathrm{N}", "newton"),
    _w("J", r"\,\mathrm{J}", "joule"),
    _w("Ω", r"\,\Omega", "ohm"),
    _w("°C", r"\,^{\circ}\mathrm{C}", "degrees Celsius"),
    _w("unit", r"\,\mathrm{" + PH + "}", "custom unit"),
    _w("×10ⁿ", r"\times 10^{" + PH + "}", "scientific notation"),
    _w("H₂O", r"\mathrm{H_2O}", "water", "chemistry"),
    _w("⇌", r"\rightleftharpoons ", "chemical equilibrium"),
    _w("→ (rxn)", r"\longrightarrow ", "reaction arrow"),
)

CATEGORIES: tuple[PaletteCategory, ...] = (
    PaletteCategory("basic", "Basic", "123", BASIC),
    PaletteCategory("structures", "Structures", "a⁄b", STRUCTURES),
    PaletteCategory("greek", "Greek", "αβ", GREEK),
    PaletteCategory("relations", "Relations", "≤", RELATIONS),
    PaletteCategory("operators", "Operators", "±", OPERATORS),
    PaletteCategory("calculus", "Calculus", "∫", CALCULUS),
    PaletteCategory("functions", "Functions", "sin", FUNCTIONS),
    PaletteCategory("sets", "Sets & Logic", "ℝ", SETS),
    PaletteCategory("arrows", "Arrows", "→", ARROWS),
    PaletteCategory("matrices", "Matrices", "▦", MATRICES),
    PaletteCategory("fonts", "Fonts & Accents", "𝐀", FONTS),
    PaletteCategory("spacing", "Spacing & Misc", "⋯", SPACING),
    PaletteCategory("physics", "Physics", "ℏ", PHYSICS),
)


def all_buttons() -> list[PaletteButton]:
    return [button for category in CATEGORIES for button in category.buttons]


def search(query: str) -> list[PaletteButton]:
    words = query.casefold().split()
    if not words:
        return []
    seen: set[tuple[str, str]] = set()
    results: list[PaletteButton] = []
    for button in all_buttons():
        if button.kind == "builder" and "matrix" not in query.casefold():
            continue
        key = (button.label, button.latex)
        if key in seen:
            continue
        text = button.search_text()
        if all(word in text for word in words):
            seen.add(key)
            results.append(button)
    return results


def known_commands() -> list[str]:
    """LaTeX commands mentioned anywhere in the palettes, for completion."""
    import re

    commands: set[str] = set()
    for button in all_buttons():
        commands.update(re.findall(r"\\[A-Za-z]+", button.latex))
    commands.update({
        r"\frac", r"\sqrt", r"\left", r"\right", r"\begin", r"\end", r"\text",
        r"\mathbb", r"\mathbf", r"\mathcal", r"\operatorname", r"\sum", r"\int",
        r"\prod", r"\lim", r"\infty", r"\partial", r"\nabla", r"\cdot", r"\times",
        r"\binom", r"\overline", r"\underline", r"\vec", r"\hat", r"\displaystyle",
    })
    return sorted(commands, key=lambda c: (c.lower(), c))


def template_for_command(command: str) -> str:
    """Best template that starts with *command* (e.g. \\frac -> \\frac{⬚}{⬚})."""
    import re

    best = ""
    for button in all_buttons():
        latex = button.latex
        if latex.startswith(command) and not re.match(r"[A-Za-z]", latex[len(command):len(command) + 1]):
            if PH in latex and (not best or len(latex) < len(best)):
                best = latex
    return best or command + ("" if command.endswith(" ") else " ")


MATRIX_ENVS = ["pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix", "matrix",
               "smallmatrix", "augmented"]
MATRIX_FILLS = ["placeholders", "zeros", "identity", "a_ij entries"]


def build_matrix(rows: int, cols: int, env: str = "bmatrix", fill: str = "placeholders",
                 name: str = "a") -> str:
    rows = max(1, min(12, int(rows)))
    cols = max(1, min(12, int(cols)))

    def entry(i: int, j: int) -> str:
        if fill == "zeros":
            return "0"
        if fill == "identity":
            return "1" if i == j else "0"
        if fill.startswith("a_ij"):
            return f"{name}_{{{i + 1}{j + 1}}}"
        return PH

    body = r" \\ ".join(" & ".join(entry(i, j) for j in range(cols)) for i in range(rows))
    if env == "augmented":
        spec = "c" * max(1, cols - 1) + ("|c" if cols > 1 else "")
        return f"\\left[\\begin{{array}}{{{spec}}} {body} \\end{{array}}\\right]"
    if env not in MATRIX_ENVS:
        env = "bmatrix"
    return f"\\begin{{{env}}} {body} \\end{{{env}}}"

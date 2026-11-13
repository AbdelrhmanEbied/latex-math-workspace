"""LaTeX-to-Unicode preview text.

This is intentionally not a TeX engine.  It understands the small, common
subset of LaTeX used by the bundled library and produces a compact, readable
plain-text approximation.  When matplotlib is available the UI additionally
renders real math typesetting; this module is the always-available fallback.
"""

from __future__ import annotations

import re
import unicodedata

# Symbols and named operators -------------------------------------------------
SYMBOLS: dict[str, str] = {
    # Greek lowercase
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ϵ",
    "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ",
    "iota": "ι", "kappa": "κ", "varkappa": "ϰ", "lambda": "λ", "mu": "μ",
    "nu": "ν", "xi": "ξ", "omicron": "ο", "pi": "π", "varpi": "ϖ", "rho": "ρ",
    "varrho": "ϱ", "sigma": "σ", "varsigma": "ς", "tau": "τ", "upsilon": "υ",
    "phi": "ϕ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    # Greek uppercase
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ",
    "Pi": "Π", "Sigma": "Σ", "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ",
    "Omega": "Ω",
    # Relations and operators
    "pm": "±", "mp": "∓", "times": "×", "div": "÷", "cdot": "⋅",
    "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠", "ne": "≠",
    "approx": "≈", "equiv": "≡", "sim": "∼", "simeq": "≃", "cong": "≅",
    "propto": "∝", "ll": "≪", "gg": "≫", "prec": "≺", "succ": "≻",
    "in": "∈", "notin": "∉", "ni": "∋", "subset": "⊂", "subseteq": "⊆",
    "supset": "⊃", "supseteq": "⊇", "cup": "∪", "cap": "∩",
    "emptyset": "∅", "varnothing": "∅", "forall": "∀", "exists": "∃",
    "nexists": "∄", "neg": "¬", "lnot": "¬", "land": "∧", "wedge": "∧",
    "lor": "∨", "vee": "∨", "implies": "⟹", "iff": "⟺", "therefore": "∴",
    "because": "∵", "infty": "∞", "partial": "∂", "nabla": "∇", "ell": "ℓ",
    "hbar": "ℏ", "Re": "ℜ", "Im": "ℑ", "aleph": "ℵ", "angle": "∠",
    "perp": "⊥", "parallel": "∥", "nparallel": "∦", "mid": "∣", "nmid": "∤",
    "to": "→", "rightarrow": "→", "leftarrow": "←", "gets": "←",
    "leftrightarrow": "↔", "mapsto": "↦", "hookrightarrow": "↪",
    "Rightarrow": "⇒", "Leftarrow": "⇐", "Leftrightarrow": "⇔",
    "longrightarrow": "⟶", "longleftarrow": "⟵", "longleftrightarrow": "⟷",
    "uparrow": "↑", "downarrow": "↓", "updownarrow": "↕",
    "oplus": "⊕", "ominus": "⊖", "otimes": "⊗", "odot": "⊙",
    "circ": "∘", "bullet": "•", "star": "⋆", "ast": "∗",
    "prime": "′", "backslash": "∖", "setminus": "∖", "smallsetminus": "∖",
    "dagger": "†", "ddagger": "‡", "S": "§", "P": "¶",
    "ldots": "…", "dots": "…", "cdots": "⋯", "vdots": "⋮", "ddots": "⋱",
    "dotsb": "⋯", "dotsc": "…",
    "quad": "  ", "qquad": "    ", ",": " ", ";": " ", ":": " ", "!": "",
    " ": " ", "\\": "\n",
    # Big operators
    "sum": "∑", "prod": "∏", "coprod": "∐", "int": "∫", "iint": "∬",
    "iiint": "∭", "oint": "∮", "oiint": "∯", "oiiint": "∰",
    "bigcup": "⋃", "bigcap": "⋂", "bigvee": "⋁", "bigwedge": "⋀",
    "bigoplus": "⨁", "bigotimes": "⨂", "bigodot": "⨀",
    # Delimiters (rendered by the regular character that follows \left/\right)
    "langle": "⟨", "rangle": "⟩", "lceil": "⌈", "rceil": "⌉",
    "lfloor": "⌊", "rfloor": "⌋", "vert": "|", "Vert": "‖",
    "lvert": "|", "rvert": "|", "lVert": "‖", "rVert": "‖",
    # Escapes
    "%": "%", "{": "{", "}": "}", "_": "_", "&": "&", "#": "#", "$": "$",
}

FUNCTIONS = {
    "sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan",
    "sinh", "cosh", "tanh", "coth", "log", "ln", "lg", "exp", "lim", "liminf",
    "limsup", "max", "min", "sup", "inf", "det", "dim", "ker", "deg", "gcd",
    "hom", "arg", "Pr", "mod", "bmod",
}

SPACING = {",", ";", ":", "!", " ", "quad", "qquad", "enspace", "thinspace",
           "medspace", "thickspace", "negthinspace"}

ACCENTS = {
    "vec": "\u20d7", "hat": "\u0302", "bar": "\u0304", "tilde": "\u0303",
    "dot": "\u0307", "ddot": "\u0308", "check": "\u030c", "breve": "\u0306",
    "acute": "\u0301", "grave": "\u0300",
}

SUPERSCRIPT = str.maketrans({
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶",
    "7": "⁷", "8": "⁸", "9": "⁹", "+": "⁺", "-": "⁻", "−": "⁻", "=": "⁼",
    "(": "⁽", ")": "⁾", "n": "ⁿ", "i": "ⁱ", "a": "ᵃ", "b": "ᵇ", "c": "ᶜ",
    "d": "ᵈ", "e": "ᵉ", "f": "ᶠ", "g": "ᵍ", "h": "ʰ", "j": "ʲ", "k": "ᵏ",
    "l": "ˡ", "m": "ᵐ", "o": "ᵒ", "p": "ᵖ", "r": "ʳ", "s": "ˢ", "t": "ᵗ",
    "u": "ᵘ", "v": "ᵛ", "w": "ʷ", "x": "ˣ", "y": "ʸ", "z": "ᶻ",
    "T": "ᵀ", "∞": "∞", "′": "′",
})

SUBSCRIPT = str.maketrans({
    "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄", "5": "₅", "6": "₆",
    "7": "₇", "8": "₈", "9": "₉", "+": "₊", "-": "₋", "−": "₋", "=": "₌",
    "(": "₍", ")": "₎", "a": "ₐ", "e": "ₑ", "h": "ₕ", "i": "ᵢ", "j": "ⱼ",
    "k": "ₖ", "l": "ₗ", "m": "ₘ", "n": "ₙ", "o": "ₒ", "p": "ₚ", "r": "ᵣ",
    "s": "ₛ", "t": "ₜ", "u": "ᵤ", "v": "ᵥ", "x": "ₓ",
})

DOUBLE_STRUCK = {
    "R": "ℝ", "N": "ℕ", "Z": "ℤ", "Q": "ℚ", "C": "ℂ", "P": "ℙ",
    "E": "𝔼", "F": "𝔽", "H": "ℍ", "O": "𝕆",
}
CALLIGRAPHIC = {
    "B": "ℬ", "E": "ℰ", "F": "ℱ", "G": "𝒢", "H": "ℋ", "I": "ℐ",
    "L": "ℒ", "M": "ℳ", "R": "ℛ", "S": "𝒮", "T": "𝒯", "X": "𝒳",
}

MATRIX_ENVS = {
    "matrix": ("", ""), "smallmatrix": ("", ""),
    "pmatrix": ("(", ")"), "bmatrix": ("[", "]"),
    "Bmatrix": ("{", "}"), "vmatrix": ("|", "|"), "Vmatrix": ("‖", "‖"),
}

MULTILINE_BRACKETS = {
    "bmatrix": ("⎡", "⎢", "⎣", "⎤", "⎥", "⎦"),
    "pmatrix": ("⎛", "⎜", "⎝", "⎞", "⎟", "⎠"),
    "Bmatrix": ("⎧", "⎪", "⎩", "⎫", "⎪", "⎭"),
    "vmatrix": ("│", "│", "│", "│", "│", "│"),
    "Vmatrix": ("║", "║", "║", "║", "║", "║"),
    "matrix": ("", "", "", "", "", ""),
    "smallmatrix": ("", "", "", "", "", ""),
}


def _display_width(text: str) -> int:
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _display_width(text))


def _read_group(text: str, index: int) -> tuple[str, int]:
    """Read a braced group (or one token) starting at *index*."""
    length = len(text)
    while index < length and text[index].isspace():
        index += 1
    if index >= length:
        return "", index
    if text[index] != "{":
        if text[index] == "\\":
            end = index + 1
            while end < length and text[end].isalpha():
                end += 1
            if end == index + 1 and end < length:
                end += 1
            return text[index:end], end
        return text[index], index + 1
    depth = 0
    start = index + 1
    while index < length:
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index], index + 1
        index += 1
    return text[start:], length


def _read_optional(text: str, index: int) -> tuple[str | None, int]:
    length = len(text)
    while index < length and text[index].isspace():
        index += 1
    if index < length and text[index] == "[":
        end = text.find("]", index + 1)
        if end != -1:
            return text[index + 1:end], end + 1
    return None, index


def _script(text: str, table: dict[int, str], marker: str) -> str:
    text = text.strip()
    if not text:
        return ""
    if all(ord(char) in table for char in text):
        return text.translate(table)
    return f"{marker}({text})"


def _fraction_part(text: str) -> str:
    text = text.strip()
    if not text:
        return "()"
    if re.search(r"[\s+\-−=<>≤≥⋅×/]", text):
        return f"({text})"
    return text


def _matrix_rows(body: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in re.split(r"\\\\", body):
        if not row.strip():
            continue
        rows.append([cell.strip() for cell in row.split("&")])
    return rows


def _render_matrix(env: str, body: str, multiline: bool) -> str:
    rows = _matrix_rows(body)
    if not rows:
        return ""
    cells = [[render_latex(cell, multiline=False) for cell in row] for row in rows]
    columns = max(len(row) for row in cells)
    for row in cells:
        row.extend([""] * (columns - len(row)))
    if not multiline:
        opener, closer = MATRIX_ENVS.get(env, ("", ""))
        inner = "; ".join(" ".join(cell for cell in row if cell) for row in cells)
        return f"{opener}{inner}{closer}"
    left_top, left_mid, left_bottom, right_top, right_mid, right_bottom = (
        MULTILINE_BRACKETS.get(env, ("", "", "", "", "", ""))
    )
    widths = [max(_display_width(row[col]) for row in cells) for col in range(columns)]
    rendered_rows = [
        "  ".join(_pad(cell, widths[col]) for col, cell in enumerate(row)).rstrip()
        for row in cells
    ]
    if left_top == "" and right_top == "":
        return "\n".join(rendered_rows)
    lines = []
    for index, row in enumerate(rendered_rows):
        if len(rendered_rows) == 1 or index == 0:
            left, right = left_top, right_top
        elif index == len(rendered_rows) - 1:
            left, right = left_bottom, right_bottom
        else:
            left, right = left_mid, right_mid
        lines.append(f"{left} {row} {right}")
    return "\n".join(lines)


def _render_cases(body: str, multiline: bool) -> str:
    rows = _matrix_rows(body)
    if not rows:
        return ""
    rendered: list[str] = []
    for row in rows:
        parts = [render_latex(cell, multiline=False) for cell in row]
        if len(parts) >= 2:
            rendered.append(f"{parts[0].rstrip(',')},  {parts[1]}")
        else:
            rendered.append(",  ".join(parts))
    if not multiline:
        return "{ " + "; ".join(rendered) + " }"
    if len(rendered) == 1:
        return f"{{ {rendered[0]}"
    lines = []
    for index, row in enumerate(rendered):
        if index == 0:
            brace = "⎧"
        elif index == len(rendered) - 1:
            brace = "⎩"
        else:
            brace = "⎨"
        lines.append(f"{brace} {row}")
    return "\n".join(lines)


def _render_aligned(body: str, multiline: bool) -> str:
    rows = _matrix_rows(body)
    rendered = ["  ".join(render_latex(cell, multiline=False) for cell in row).strip()
                for row in rows]
    if multiline:
        return "\n".join(rendered)
    return "; ".join(rendered)


def _find_end(text: str, env: str, start: int) -> tuple[str, int]:
    marker = "\\end{" + env + "}"
    end = text.find(marker, start)
    if end == -1:
        return text[start:], len(text)
    return text[start:end], end + len(marker)


def render_latex(latex: str, multiline: bool = False) -> str:
    """Return a readable Unicode approximation of a LaTeX expression."""
    rendered = _render(latex, multiline)
    # Collapse horizontal whitespace, keep intentional newlines.
    rendered = re.sub(r"[ \t]+", " ", rendered)
    rendered = re.sub(r" *\n *", "\n" if multiline else " ", rendered)
    rendered = re.sub(r"\n{3,}", "\n\n", rendered)
    return rendered.strip()


def _render(text: str, multiline: bool) -> str:
    out: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\":
            if index + 1 >= length:
                index += 1
                continue
            next_char = text[index + 1]
            if next_char == "\\":
                out.append("\n" if multiline else "; ")
                index += 2
                continue
            if next_char.isalpha():
                end = index + 1
                while end < length and text[end].isalpha():
                    end += 1
                command = text[index + 1:end]
                index = end
                command, index, value = _command(command, text, index, multiline)
                if value is not None:
                    out.append(value)
                if command == "__stop__":
                    break
                continue
            # Escaped character such as \, \{ \% or \_
            symbol = SYMBOLS.get(next_char, next_char)
            out.append(symbol)
            index += 2
            continue

        if char == "{":
            group, index = _read_group(text, index)
            out.append(_render(group, multiline))
            continue
        if char in "^_":
            atom, index = _read_group(text, index + 1)
            value = _render(atom, False)
            if char == "^":
                out.append(_script(value, SUPERSCRIPT, "^"))
            else:
                out.append(_script(value, SUBSCRIPT, "_"))
            continue
        if char == "&":
            out.append(" ")
            index += 1
            continue
        if char in "$\r\n":
            out.append("\n" if char == "\n" and multiline else " ")
            index += 1
            continue
        if char == "~":
            out.append(" ")
            index += 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _command(command: str, text: str, index: int, multiline: bool):
    """Handle one command.  Returns (command, new_index, replacement)."""
    if command in {"frac", "dfrac", "tfrac", "cfrac"}:
        numerator, index = _read_group(text, index)
        denominator, index = _read_group(text, index)
        num = _fraction_part(_render(numerator, False))
        den = _fraction_part(_render(denominator, False))
        return command, index, f"{num}/{den}"

    if command == "binom":
        top, index = _read_group(text, index)
        bottom, index = _read_group(text, index)
        return command, index, f"C({_render(top, False)}, {_render(bottom, False)})"

    if command == "sqrt":
        degree, index = _read_optional(text, index)
        radicand, index = _read_group(text, index)
        value = _render(radicand, False)
        if degree:
            degree_text = _render(degree, False)
            superscript = _script(degree_text, SUPERSCRIPT, "^")
            return command, index, f"{superscript}√({value})"
        return command, index, f"√({value})"

    if command == "begin":
        env, index = _read_group(text, index)
        env = env.strip()
        if env == "array":
            _column_spec, index = _read_group(text, index)
        body, index = _find_end(text, env, index)
        if env in MATRIX_ENVS:
            return command, index, _render_matrix(env, body, multiline)
        if env in {"cases", "dcases"}:
            return command, index, _render_cases(body, multiline)
        if env in {"aligned", "align", "align*", "gathered", "split"}:
            return command, index, _render_aligned(body, multiline)
        return command, index, _render(body, multiline)

    if command in {"text", "textrm", "textnormal", "mathrm", "mathbf", "mathit",
                   "mathsf", "mathtt", "operatorname"}:
        group, index = _read_group(text, index)
        if command in {"text", "textrm", "textnormal", "operatorname"}:
            value = re.sub(r"\\([{}%$&#_])", r"\1", group)
        else:
            value = _render(group, False)
        return command, index, value

    if command == "mathbb":
        group, index = _read_group(text, index)
        stripped = group.strip()
        if stripped in DOUBLE_STRUCK:
            return command, index, DOUBLE_STRUCK[stripped]
        return command, index, _render(group, False)

    if command in {"mathcal", "mathscr", "mathfrak"}:
        group, index = _read_group(text, index)
        stripped = group.strip()
        if stripped in CALLIGRAPHIC:
            return command, index, CALLIGRAPHIC[stripped]
        return command, index, _render(group, False)

    if command in ACCENTS:
        group, index = _read_group(text, index)
        value = _render(group, False)
        accent = ACCENTS[command]
        if command in {"hat", "bar", "tilde", "dot", "ddot", "check", "breve",
                       "acute", "grave"} and len(value) > 1:
            return command, index, "".join(ch + accent for ch in value)
        return command, index, value + accent

    if command in {"overline", "underline"}:
        group, index = _read_group(text, index)
        value = _render(group, False)
        accent = "\u0305" if command == "overline" else "\u0332"
        return command, index, "".join(ch + accent for ch in value)

    if command == "color":
        _color, index = _read_group(text, index)
        group, index = _read_group(text, index)
        return command, index, _render(group, False)

    if command == "boxed":
        group, index = _read_group(text, index)
        return command, index, f"▭ {_render(group, False)}"

    if command in {"substack", "subarray"}:
        group, index = _read_group(text, index)
        rows = _matrix_rows(group)
        return command, index, "; ".join(_render(row[0], False) for row in rows if row)

    if command in {"overset", "underset", "stackrel"}:
        first, index = _read_group(text, index)
        second, index = _read_group(text, index)
        return command, index, f"{_render(second, False)} ({_render(first, False)})"

    if command in {"left", "right", "big", "Big", "bigg", "Bigg", "bigl",
                   "bigr", "Bigl", "Bigr", "Biggl", "Biggr", "biggl", "biggr"}:
        # The delimiter following the command is handled by the main loop.
        while index < len(text) and text[index].isspace():
            index += 1
        if index < len(text) and text[index] == ".":
            index += 1
        return command, index, ""

    if command in SPACING or command in {"enspace", "thinspace", "medspace",
                                         "thickspace", "negthinspace"}:
        return command, index, " "

    if command in SYMBOLS:
        return command, index, SYMBOLS[command]

    if command in {"exp", "log", "ln", "sin", "cos", "tan", "cot", "sec",
                   "csc", "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh",
                   "coth", "det", "dim", "ker", "lim", "liminf", "limsup",
                   "max", "min", "sup", "inf", "gcd", "deg", "hom", "arg",
                   "mod", "bmod"}:
        return command, index, command

    if command in {"nonumber", "notag", "displaystyle", "textstyle",
                   "scriptstyle", "scriptscriptstyle", "limits", "nolimits"}:
        return command, index, ""

    # Unknown command: keep its name without the backslash.  This is friendlier
    # than dropping content, and makes user-authored snippets degrade well.
    return command, index, command


def compact_preview(latex: str) -> str:
    """One-line preview used in list rows."""
    return re.sub(r"\s*\n\s*", " ; ", render_latex(latex, multiline=True)).strip()


def detailed_preview(latex: str) -> str:
    """Multi-line preview used in the detail pane."""
    return render_latex(latex, multiline=True)

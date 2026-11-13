"""LaTeX -> image rendering for the workspace.

Public API (stable; other modules depend on it):

* ``render_image(latex, color, size_px=22, dpr=1.0) -> QImage`` never raises.
  On total failure it returns an image of the Unicode approximation.
* ``render_png(latex, color, size_px=22, dpr=2.0) -> bytes``
* ``render_error(latex) -> str`` empty when the expression renders exactly,
  otherwise a short explanation (used by the editor as a syntax hint).
* ``service() -> RenderService``: a background renderer whose ``rendered``
  signal delivers ``(key, QImage)`` for the latest request of each key.

Rendering uses three tiers:

1. Real LaTeX (``latex`` + ``dvipng`` with ``article.cls`` and ``amsmath``),
   only when a sufficiently complete TeX installation is present.
2. A composite renderer: matplotlib mathtext for inline math, with matrix,
   cases, array and alignment environments laid out and drawn natively with
   QPainter (cells are rendered recursively, so environments may nest).
3. A Unicode approximation drawn as plain text.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections import OrderedDict
from dataclasses import dataclass

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QPointF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)

from ..latex_preview import detailed_preview

PLACEHOLDER = "⬚"

# Substitutions for commands matplotlib mathtext does not understand.
_SUBS: list[tuple[str, str]] = [
    (r"\\tfrac", r"\\frac"), (r"\\cfrac", r"\\frac"),
    (r"\\underbrace", r"\\underline"), (r"\\overbrace", r"\\overline"),
    (r"\\lvert|\\rvert", "|"), (r"\\lVert|\\rVert", r"\\Vert "),
    (r"\\implies", r"\\Longrightarrow "), (r"\\impliedby", r"\\Longleftarrow "),
    (r"\\iff", r"\\Longleftrightarrow "), (r"\\land(?![a-zA-Z])", r"\\wedge "),
    (r"\\lor(?![a-zA-Z])", r"\\vee "),
    (r"\\displaystyle|\\textstyle|\\scriptstyle|\\scriptscriptstyle", ""),
    (r"\\limits|\\nolimits", ""), (r"\\middle", ""), (r"\\nonumber|\\notag", ""),
    (r"\\label\{[^}]*\}", ""), (r"\\coloneqq", ":="), (r"\\eqqcolon", "=:"),
    (r"\\bmod(?![a-zA-Z])", r"\\,\\mathrm{mod}\\,"),
    (r"\\operatorname\*", r"\\operatorname"),
    (r"\\square(?![a-zA-Z])|\\Box(?![a-zA-Z])", "□"),
    (r"\\dots[bcmio](?![a-zA-Z])", r"\\dots"), (r"\\hdots(?![a-zA-Z])", r"\\cdots"),
    (r"\\leqslant", r"\\leq"), (r"\\geqslant", r"\\geq"),
    (r"\\le(?![a-zA-Z])", r"\\leq "), (r"\\ge(?![a-zA-Z])", r"\\geq "),
    (r"\\stackrel", r"\\overset"), (r"\\textbf", r"\\mathbf"), (r"\\textit", r"\\mathit"),
    (r"\\textrm", r"\\mathrm"), (r"\\textsf", r"\\mathsf"), (r"\\texttt", r"\\mathtt"),
    (r"\\h?space\*?\{[^}]*\}", r"\\quad "), (r"\\&", "＆"),
    (r"\\dfrac", r"\\frac"),
    (r"\\(big|Big|bigg|Bigg)[lrm]?(?![a-zA-Z])", ""),
    (r"\\mathstrut|\\strut", ""),
    (r"\\eqref\{([^}]*)\}", r"(\1)"), (r"\\ref\{([^}]*)\}", r"\1"),
]


def _strip_wrappers(latex: str) -> str:
    text = latex.strip()
    for wrapper in (("$$", "$$"), ("\\[", "\\]"), ("\\(", "\\)"), ("$", "$")):
        if text.startswith(wrapper[0]) and text.endswith(wrapper[1]) and len(text) > 2:
            text = text[len(wrapper[0]):-len(wrapper[1])].strip()
            break
    text = re.sub(r"\\(begin|end)\{(equation|displaymath)\*?\}", "", text).strip()
    return text


def preprocess(latex: str) -> str:
    text = _strip_wrappers(latex)
    for pattern, repl in _SUBS:
        text = re.sub(pattern, repl, text)
    text = re.sub(r"\\xrightarrow\{([^{}]*)\}", r"\\overset{\1}{\\longrightarrow}", text)
    text = re.sub(r"\\xleftarrow\{([^{}]*)\}", r"\\overset{\1}{\\longleftarrow}", text)
    text = re.sub(r"\\pmod\{([^{}]*)\}", r"\\ (\\mathrm{mod}\\ \1)", text)
    text = re.sub(r"\\(boxed|cancel|bcancel|xcancel|phantom|underset\{\}|overset\{\})\{", "{",
                  text)
    text = re.sub(r"\\color\{[^}]*\}", "", text)
    text = re.sub(r"\\tag\*?\{([^{}]*)\}", r"\\qquad(\1)", text)
    text = text.replace(PLACEHOLDER, "{□}")
    text = _flatten_simple_delims(text)
    text = re.sub(r"\\(int|iint|iiint|oint)(?![a-zA-Z])(?!\s*[_^])", r"\\\1\\;", text)
    text = re.sub(r"\\(int|iint|iiint|oint)(_\{[^{}]*\}|_\S)?(\^\{[^{}]*\}|\^\S)?(?=\s*[^\s\\,])",
                  lambda m: m.group(0) + r"\;" if m.group(2) or m.group(3) else m.group(0), text)
    return text


_TALL = ("\\frac", "\\dfrac", "\\sum", "\\int", "\\prod", "\\begin", "\\sqrt", "\\binom",
         "\\lim", "\\over", "\\cfrac", "\\overset", "\\underset", "\\stackrel")


def _flatten_simple_delims(text: str) -> str:
    """Turn \\left( x \\right) into ( x ) when the content is a single line.

    Sympy wraps every function argument in \\left(\\right); mathtext sizes
    those delimiters poorly for short content, so plain parentheses look better.
    """
    pairs = {"(": ")", "[": "]"}
    out = text
    for _ in range(50):
        changed = False
        for match in re.finditer(r"\\left\s*([(\[])", out):
            opener = match.group(1)
            depth, i = 1, match.end()
            while i < len(out):
                if out.startswith("\\left", i):
                    depth += 1
                    i += 5
                elif out.startswith("\\right", i):
                    depth -= 1
                    if depth == 0:
                        break
                    i += 6
                i += 1
            if i >= len(out) or depth != 0:
                continue
            inner = out[match.end():i]
            close_at = i + len("\\right")
            rest = out[close_at:].lstrip()
            if not rest.startswith(pairs[opener]):
                continue
            close_end = len(out) - len(rest) + 1
            if "\\left" in inner or any(t in inner for t in _TALL) or re.search(r"\^\{[^{}]{4,}\}", inner):
                continue
            out = out[:match.start()] + opener + inner + pairs[opener] + out[close_end:]
            changed = True
            break
        if not changed:
            break
    return out


# ---------------------------------------------------------------------------
# Tier 1: real LaTeX
# ---------------------------------------------------------------------------

_latex_info: tuple[bool, list[str]] | None = None
_latex_lock = threading.Lock()
_latex_cache: OrderedDict[tuple, tuple[QImage | None, str]] = OrderedDict()


def latex_available() -> bool:
    return _latex_detect()[0]


def _latex_detect() -> tuple[bool, list[str]]:
    global _latex_info
    if _latex_info is not None:
        return _latex_info
    available = False
    extras: list[str] = []
    if shutil.which("latex") and shutil.which("dvipng") and shutil.which("kpsewhich"):
        try:
            found = subprocess.run(
                ["kpsewhich", "article.cls", "amsmath.sty"], capture_output=True,
                text=True, timeout=5, check=False,
            )
            lines = [line for line in found.stdout.splitlines() if line.strip()]
            available = found.returncode == 0 and len(lines) == 2
            if available:
                for package in ("mathtools", "bm", "cancel", "xcolor"):
                    probe = subprocess.run(
                        ["kpsewhich", f"{package}.sty"], capture_output=True, text=True,
                        timeout=5, check=False,
                    )
                    if probe.returncode == 0 and probe.stdout.strip():
                        extras.append(package)
        except (OSError, subprocess.TimeoutExpired):
            available = False
    _latex_info = (available, extras)
    return _latex_info


def _has_top_level(text: str, token: str) -> bool:
    return len(_split_top(text, token)) > 1


def _latex_image(latex: str, color: QColor, size_px: float) -> tuple[QImage | None, str]:
    available, extras = _latex_detect()
    if not available:
        return None, "LaTeX unavailable"
    key = (latex, color.name(), round(size_px, 1))
    with _latex_lock:
        if key in _latex_cache:
            _latex_cache.move_to_end(key)
            return _latex_cache[key]
    body = _strip_wrappers(latex).replace(PLACEHOLDER, r"\square ")
    if _has_top_level(body, "&") or _has_top_level(body, "\\\\"):
        math = "\\begin{align*}\n" + body + "\n\\end{align*}"
    else:
        math = "\\[\n" + body + "\n\\]"
    packages = ",".join(["amsmath", "amssymb", *extras])
    source = (
        "\\documentclass[12pt]{article}\n"
        f"\\usepackage{{{packages}}}\n"
        "\\pagestyle{empty}\n\\begin{document}\n" + math + "\n\\end{document}\n"
    )
    dpi = max(30, round(size_px * 72.27 / 12.0))
    result: tuple[QImage | None, str]
    with tempfile.TemporaryDirectory(prefix="latex-picker-") as tmp:
        tex_path = os.path.join(tmp, "eq.tex")
        with open(tex_path, "w", encoding="utf-8") as handle:
            handle.write(source)
        try:
            run = subprocess.run(
                ["latex", "-interaction=nonstopmode", "-halt-on-error", "eq.tex"],
                cwd=tmp, capture_output=True, timeout=8, check=False,
            )
            if run.returncode != 0:
                error = "LaTeX error"
                try:
                    with open(os.path.join(tmp, "eq.log"), encoding="utf-8",
                              errors="replace") as log:
                        for line in log:
                            if line.startswith("!"):
                                error = line[1:].strip()
                                break
                except OSError:
                    pass
                result = (None, error)
            else:
                fg = f"rgb {color.redF():.3f} {color.greenF():.3f} {color.blueF():.3f}"
                png = os.path.join(tmp, "eq.png")
                conv = subprocess.run(
                    ["dvipng", "-T", "tight", "-D", str(dpi), "-bg", "Transparent",
                     "-fg", fg, "-o", png, "eq.dvi"],
                    cwd=tmp, capture_output=True, timeout=8, check=False,
                )
                image = QImage(png) if conv.returncode == 0 else QImage()
                if image.isNull():
                    result = (None, "dvipng failed")
                else:
                    result = (image.convertToFormat(
                        QImage.Format.Format_ARGB32_Premultiplied), "")
        except (OSError, subprocess.TimeoutExpired) as exc:
            result = (None, f"LaTeX failed: {exc}")
    with _latex_lock:
        _latex_cache[key] = result
        while len(_latex_cache) > 64:
            _latex_cache.popitem(last=False)
    return result


# ---------------------------------------------------------------------------
# Tier 2: composite renderer
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_parser = None


@dataclass
class _Box:
    image: QImage | None
    width: int
    ascent: int
    descent: int

    @property
    def height(self) -> int:
        return self.ascent + self.descent


class _Ctx:
    """Collects problems found while rendering one expression."""

    def __init__(self, color: QColor) -> None:
        self.color = color
        self.errors: list[str] = []


def _new_image(width: int, height: int) -> QImage:
    image = QImage(max(1, width), max(1, height), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    return image


def _mathtext_parse(tex: str, size_px: float):
    global _parser
    with _lock:
        if _parser is None:
            import matplotlib

            matplotlib.rcParams["mathtext.fontset"] = "cm"
            from matplotlib.mathtext import MathTextParser

            _parser = MathTextParser("agg")
        import matplotlib

        # Other code (the picker preview) shares matplotlib's global rcParams;
        # pin TeX-like styling: italic letters, upright digits.
        matplotlib.rcParams["mathtext.fontset"] = "cm"
        matplotlib.rcParams["mathtext.default"] = "normal"
        dpi = 72.0 * size_px / 12.0
        return _parser.parse(f"${tex}$", dpi=dpi)


def _mathtext_box(tex: str, color: QColor, size_px: float) -> _Box:
    import numpy as np

    parsed = _mathtext_parse(tex, size_px)
    alpha = np.ascontiguousarray(np.asarray(parsed.image, dtype=np.uint8))
    height, width = alpha.shape
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    rgba[..., 0] = color.red()
    rgba[..., 1] = color.green()
    rgba[..., 2] = color.blue()
    rgba[..., 3] = alpha
    image = QImage(rgba.tobytes(), width, height, 4 * width, QImage.Format.Format_RGBA8888)
    image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    descent = min(height, max(0, round(parsed.depth)))
    return _Box(image, width, height - descent, descent)


def _mathtext_image(tex: str, color: QColor, size_px: float) -> QImage:
    """Render with matplotlib mathtext; raises on parse failure."""
    return _mathtext_box(tex, color, size_px).image  # type: ignore[return-value]


def _text_image(text: str, color: QColor, size_px: float) -> QImage:
    font = QFont("DejaVu Serif")
    font.setPixelSize(max(8, round(size_px)))
    metrics = QFontMetricsF(font)
    lines = text.splitlines() or [""]
    width = max(metrics.horizontalAdvance(line) for line in lines) + 4
    height = metrics.lineSpacing() * len(lines) + 4
    image = _new_image(int(width), int(height))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.setFont(font)
    painter.setPen(color)
    y = 2 + metrics.ascent()
    for line in lines:
        painter.drawText(2, int(y), line)
        y += metrics.lineSpacing()
    painter.end()
    return image


def _text_box(text: str, color: QColor, size_px: float) -> _Box:
    image = _text_image(text or " ", color, size_px)
    descent = round(image.height() * 0.3)
    return _Box(image, image.width(), image.height() - descent, descent)


def _empty_box(size_px: float, width: int = 0) -> _Box:
    return _Box(None, width, round(size_px * 0.7), round(size_px * 0.25))


def _split_top(text: str, separator: str) -> list[str]:
    """Split at *separator* outside braces and environments."""
    parts: list[str] = []
    depth = 0
    env = 0
    start = 0
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("\\begin{", i) or text.startswith("\\end{", i):
            env += 1 if text.startswith("\\begin{", i) else -1
            close = text.find("}", i)
            i = close + 1 if close >= 0 else n
            continue
        if depth == 0 and env == 0 and text.startswith(separator, i):
            parts.append(text[start:i])
            i += len(separator)
            start = i
            continue
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    parts.append(text[start:])
    return parts


_BEGIN_RE = re.compile(r"\\begin\s*\{([A-Za-z]+\*?)\}")
_ENV_RE = re.compile(r"\\(begin|end)\s*\{([A-Za-z]+\*?)\}")


def _segments(text: str, ctx: _Ctx) -> list[tuple]:
    """Split into ('text', src) and ('env', name, arg, body) at brace depth 0."""
    result: list[tuple] = []
    depth = 0
    i = 0
    start = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
            if depth == 0 and text.startswith("\\begin", i):
                match = _BEGIN_RE.match(text, i)
                if match:
                    name = match.group(1)
                    if start < i:
                        result.append(("text", text[start:i]))
                    pos = match.end()
                    arg = ""
                    if name == "array" and pos < n and text[pos:].lstrip().startswith("{"):
                        pos = text.index("{", pos)
                        close = _match_brace(text, pos)
                        arg = text[pos + 1:close]
                        pos = close + 1
                    body_start = pos
                    level = 1
                    end_pos = None
                    for env_match in _ENV_RE.finditer(text, pos):
                        level += 1 if env_match.group(1) == "begin" else -1
                        if level == 0:
                            end_pos = env_match
                            break
                    if end_pos is None:
                        ctx.errors.append(f"Missing \\end{{{name}}}")
                        body = text[body_start:]
                        result.append(("env", name, arg, body))
                        return result
                    if end_pos.group(2) != name:
                        ctx.errors.append(
                            f"\\begin{{{name}}} ended by \\end{{{end_pos.group(2)}}}")
                    result.append(("env", name, arg, text[body_start:end_pos.start()]))
                    i = start = end_pos.end()
                    continue
            if depth == 0 and text.startswith("\\end", i):
                match = _ENV_RE.match(text, i)
                if match:
                    ctx.errors.append(f"Unexpected \\end{{{match.group(2)}}}")
                    if start < i:
                        result.append(("text", text[start:i]))
                    i = start = match.end()
                    continue
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    if start < n:
        result.append(("text", text[start:]))
    return result


def _match_brace(text: str, open_index: int) -> int:
    depth = 0
    i = open_index
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(text) - 1


_DELIM_TOKEN = r"(\\[a-zA-Z]+|\\[{}|]|[()\[\]|./<>])"
_LEFT_TAIL = re.compile(r"\\left\s*" + _DELIM_TOKEN + r"\s*$")
_RIGHT_HEAD = re.compile(r"^\s*\\right\s*" + _DELIM_TOKEN)

_DELIM_MAP = {
    "(": "(", ")": ")", "[": "[", "]": "]", "\\{": "{", "\\}": "}",
    "\\lbrace": "{", "\\rbrace": "}", "|": "|", "\\vert": "|", "\\lvert": "|",
    "\\rvert": "|", "\\|": "‖", "\\Vert": "‖", "\\lVert": "‖", "\\rVert": "‖",
    "\\langle": "⟨", "\\rangle": "⟩", "<": "⟨", ">": "⟩", "\\lfloor": "⌊",
    "\\rfloor": "⌋", "\\lceil": "⌈", "\\rceil": "⌉", ".": "", "/": "",
    "\\lbrack": "[", "\\rbrack": "]",
}

_ENV_DELIMS = {
    "pmatrix": ("(", ")"), "bmatrix": ("[", "]"), "Bmatrix": ("{", "}"),
    "vmatrix": ("|", "|"), "Vmatrix": ("‖", "‖"), "cases": ("{", ""),
    "rcases": ("", "}"), "dcases": ("{", ""),
    "pmatrix*": ("(", ")"), "bmatrix*": ("[", "]"), "psmallmatrix": ("(", ")"),
    "bsmallmatrix": ("[", "]"), "vsmallmatrix": ("|", "|"),
}
_MATRIX_LIKE = {"matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix",
                "smallmatrix", "pmatrix*", "bmatrix*", "psmallmatrix", "bsmallmatrix",
                "vsmallmatrix", "matrix*"}
_ALIGNED = {"aligned", "align", "align*", "split", "eqnarray", "eqnarray*", "alignat",
            "alignat*", "alignedat", "flalign", "flalign*"}
_GATHER = {"gather", "gather*", "gathered", "multline", "multline*", "subarray"}
_CASES = {"cases", "dcases", "rcases"}
_KNOWN_ENVS = _MATRIX_LIKE | _ALIGNED | _GATHER | _CASES | {"array"}


def _hcat(boxes: list[_Box], size_px: float) -> _Box:
    boxes = [box for box in boxes if box.width > 0 or box.image is not None]
    if not boxes:
        return _empty_box(size_px)
    if len(boxes) == 1:
        return boxes[0]
    ascent = max(box.ascent for box in boxes)
    descent = max(box.descent for box in boxes)
    width = sum(box.width for box in boxes)
    image = _new_image(width, ascent + descent)
    painter = QPainter(image)
    x = 0
    for box in boxes:
        if box.image is not None:
            painter.drawImage(x, ascent - box.ascent, box.image)
        x += box.width
    painter.end()
    return _Box(image, width, ascent, descent)


def _pad_box(box: _Box, left: int, right: int) -> _Box:
    if left <= 0 and right <= 0:
        return box
    return _hcat([_Box(None, left, 0, 0), box, _Box(None, right, 0, 0)], 1)


def _humanise(error: str) -> str:
    error = re.sub(r"^Parse\w*Exception:\s*", "", error.strip())
    match = re.search(r"Unknown symbol: (\\[A-Za-z]+)", error)
    if match:
        return f"Unknown command {match.group(1)}"
    match = re.search(r"Expected (\\[a-z]+)\{", error)
    if match:
        return f"{match.group(1)} is missing an argument"
    if "\\right" in error and "Expected" in error and "found end of text" in error \
            and "{phantom" not in error:
        return "Missing \\right"
    if "found end of text" in error:
        return "Incomplete expression: something is missing at the end"
    match = re.search(r"found '(.+?)'\s+\(at char (\d+)\)", error)
    if match:
        return f"Unexpected “{match.group(1)}” at position {int(match.group(2)) + 1}"
    return error.split("(at char")[0].strip()[:100] or "Cannot render"


def _text_piece(src: str, ctx: _Ctx, size_px: float) -> _Box:
    tex = src.strip()
    if not tex:
        return _Box(None, round(size_px * 0.15) if src else 0, 0, 0)
    if tex[0] in "^_":
        tex = "{}" + tex
    try:
        return _mathtext_box(tex, ctx.color, size_px)
    except Exception as exc:  # noqa: BLE001
        lines = [line for line in str(exc).strip().splitlines() if line.strip()]
        error = lines[-1] if lines else "cannot render"
    stripped = re.sub(r"\\left\s*(?=[\\(\[|.<])|\\right\s*(?=[\\)\]|.>])", "", tex)
    stripped = re.sub(r"(?<![a-zA-Z\\])\\([.])", "", stripped)
    if stripped != tex:
        try:
            return _mathtext_box(stripped, ctx.color, size_px)
        except Exception:  # noqa: BLE001
            pass
    ctx.errors.append(_humanise(error))
    try:
        text = detailed_preview(src)
    except Exception:  # noqa: BLE001
        text = src
    return _text_box(text.replace("\n", " "), ctx.color, size_px * 0.9)


def _layout(src: str, ctx: _Ctx, size_px: float, top: bool = False) -> _Box:
    rows = [row for row in _split_top(src, "\\\\")]
    if len(rows) > 1 and not rows[-1].strip():
        rows = rows[:-1]
    if len(rows) > 1 or _has_top_level(src, "&"):
        name = "aligned" if any(_has_top_level(r, "&") for r in rows) else "gathered"
        return _env_box(name, "", src, ctx, size_px)
    pieces = _segments(src, ctx)
    boxes: list[_Box] = []
    index = 0
    gap = round(size_px * 0.12)
    prev_env: _Box | None = None
    while index < len(pieces):
        piece = pieces[index]
        if piece[0] == "text":
            text = piece[1]
            if prev_env is not None:
                text = text.lstrip()
                if text.startswith("^"):
                    script, text = _take_script(text[1:])
                    sup = _layout(script, ctx, size_px * 0.7)
                    target = max(0, prev_env.ascent - round(sup.ascent * 0.55))
                    boxes.append(_Box(sup.image, sup.width, target + sup.ascent,
                                      max(0, sup.descent - target)))
                if _OP_HEAD.match(text):
                    boxes.append(_Box(None, round(size_px * 0.22), 0, 0))
            if text.strip():
                boxes.append(_text_piece(text, ctx, size_px))
                if index + 1 < len(pieces) and _OP_TAIL.search(text):
                    boxes.append(_Box(None, round(size_px * 0.22), 0, 0))
            prev_env = None
            index += 1
            continue
        _, name, arg, body = piece
        left = right = ""
        if boxes and index > 0 and pieces[index - 1][0] == "text":
            prev = pieces[index - 1][1]
            match = _LEFT_TAIL.search(prev)
            if match:
                left = _DELIM_MAP.get(match.group(1), "")
                boxes.pop()
                boxes.append(_text_piece(prev[:match.start()], ctx, size_px))
        box = _env_box(name, arg, body, ctx, size_px)
        if index + 1 < len(pieces) and pieces[index + 1][0] == "text":
            nxt = pieces[index + 1][1]
            match = _RIGHT_HEAD.match(nxt)
            if match:
                right = _DELIM_MAP.get(match.group(1), "")
                pieces[index + 1] = ("text", nxt[match.end():])
        if left or right:
            box = _wrap_delims(box, left, right, ctx, size_px)
        boxes.append(_pad_box(box, gap, gap))
        prev_env = box
        index += 1
    return _hcat(boxes, size_px)


_OP_TAIL = re.compile(r"(=|\+|-|<|>|\\[a-zA-Z]*(eq|leq|geq|approx|equiv|sim|cdot|times|pm|mp"
                      r"|to|rightarrow|Rightarrow|in|cong|propto|ne|neq))\s*$")
_OP_HEAD = re.compile(r"^\s*(=|\+|-|<|>|\\(eq|leq|geq|approx|equiv|sim|cdot|times|pm|mp"
                      r"|to|rightarrow|Rightarrow|in|cong|propto|ne|neq)(?![a-zA-Z]))")


def _take_script(text: str) -> tuple[str, str]:
    """Split ``{...}rest`` or ``xrest`` into (script, rest)."""
    stripped = text.lstrip()
    if stripped.startswith("{"):
        close = _match_brace(stripped, 0)
        return stripped[1:close], stripped[close + 1:]
    match = re.match(r"\\[a-zA-Z]+|.", stripped)
    if not match:
        return "", stripped
    return match.group(), stripped[match.end():]


def _parse_colspec(spec: str) -> tuple[list[str], set[int], set[int]]:
    """Return (alignments, single vlines before col k, double vlines)."""
    aligns: list[str] = []
    vlines: set[int] = set()
    double: set[int] = set()
    i = 0
    spec = spec.replace(" ", "")
    while i < len(spec):
        ch = spec[i]
        if ch in "lcr":
            aligns.append(ch)
        elif ch in "pmbX":
            aligns.append("l")
            if i + 1 < len(spec) and spec[i + 1] == "{":
                i = _match_brace(spec, i + 1)
        elif ch == "|":
            k = len(aligns)
            if k in vlines:
                double.add(k)
            vlines.add(k)
        elif ch in "@!>< " and i + 1 < len(spec) and spec[i + 1] == "{":
            i = _match_brace(spec, i + 1)
        elif ch == "*" and i + 1 < len(spec) and spec[i + 1] == "{":
            close = _match_brace(spec, i + 1)
            count_text = spec[i + 2:close]
            i = close + 1
            if i < len(spec) and spec[i] == "{":
                close2 = _match_brace(spec, i)
                inner, ivl, _ = _parse_colspec(spec[i + 1:close2])
                try:
                    repeat = max(1, min(40, int(count_text)))
                except ValueError:
                    repeat = 1
                for _ in range(repeat):
                    base = len(aligns)
                    vlines.update(base + v for v in ivl)
                    aligns.extend(inner)
                i = close2
        i += 1
    return aligns, vlines, double


def _env_box(name: str, arg: str, body: str, ctx: _Ctx, size_px: float) -> _Box:
    if name not in _KNOWN_ENVS:
        ctx.errors.append(f"Unsupported environment {name}")
    scale = 0.7 if "small" in name else 1.0
    cell_size = size_px * scale
    em = size_px

    raw_rows = _split_top(body, "\\\\")
    rows_src: list[str] = []
    hlines: set[int] = set()
    for raw in raw_rows:
        text = raw
        text = re.sub(r"^\s*\[[^\]]*\]", "", text)  # \\[4pt]
        while True:
            stripped = text.lstrip()
            match = re.match(r"\\(hline|midrule|toprule|bottomrule)\b", stripped)
            if not match:
                break
            hlines.add(len(rows_src))
            text = stripped[match.end():]
        rows_src.append(text)
    if rows_src and not rows_src[-1].strip():
        rows_src.pop()
        # an \hline after the last \\ stays recorded at index len(rows)

    cells_src = [_split_top(row, "&") for row in rows_src] or [[""]]
    ncols = max(len(row) for row in cells_src)

    vlines: set[int] = set()
    double: set[int] = set()
    if name == "array" or name == "subarray":
        aligns, vlines, double = _parse_colspec(arg)
    elif name in _CASES:
        aligns = ["l"] * ncols
    elif name in _ALIGNED:
        aligns = ["r" if j % 2 == 0 else "l" for j in range(ncols)]
    elif name in _GATHER:
        aligns = ["c"] * ncols
    else:
        aligns = ["c"] * ncols
    while len(aligns) < ncols:
        aligns.append("c")

    grid: list[list[_Box]] = []
    for row in cells_src:
        boxes = []
        for j in range(ncols):
            text = row[j] if j < len(row) else ""
            if name in _ALIGNED and j % 2 == 1 and text.strip():
                # Relations at the start of an "&=" cell need a base for spacing.
                text = "{}" + text
            boxes.append(_layout(text, ctx, cell_size) if text.strip()
                         else _empty_box(cell_size))
        grid.append(boxes)

    nrows = len(grid)
    col_w = [max(grid[i][j].width for i in range(nrows)) for j in range(ncols)]
    strut_a = round(cell_size * 0.72)
    strut_d = round(cell_size * 0.28)
    row_a = [max(strut_a, max(b.ascent for b in grid[i])) for i in range(nrows)]
    row_d = [max(strut_d, max(b.descent for b in grid[i])) for i in range(nrows)]

    if name in _ALIGNED:
        gaps = [0 if j % 2 == 0 else round(em * 1.6) for j in range(ncols - 1)]
        row_gap = round(em * 0.4)
    elif name in _CASES:
        gaps = [round(em * 1.0)] * (ncols - 1)
        row_gap = round(em * 0.35)
    elif name in _GATHER:
        gaps = [round(em * 1.0)] * (ncols - 1)
        row_gap = round(em * 0.4)
    else:
        gaps = [round(em * 0.8 * scale)] * (ncols - 1)
        row_gap = round(em * 0.3 * scale)

    line_w = max(1.0, size_px * 0.05)
    pad_x = round(em * 0.25) if (vlines or name == "array") else 0
    col_x: list[int] = []
    x = pad_x if 0 in vlines else 0
    for j in range(ncols):
        col_x.append(x)
        x += col_w[j]
        if j < ncols - 1:
            x += gaps[j]
    width = x + (pad_x if ncols in vlines else 0)
    pad_y = round(em * 0.12) if hlines else 0
    row_y: list[int] = []
    y = pad_y
    for i in range(nrows):
        row_y.append(y)
        y += row_a[i] + row_d[i]
        if i < nrows - 1:
            y += row_gap
    height = y + pad_y
    image = _new_image(width, height)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    for i in range(nrows):
        baseline = row_y[i] + row_a[i]
        for j in range(ncols):
            box = grid[i][j]
            if box.image is None:
                continue
            align = aligns[j]
            if align == "l":
                bx = col_x[j]
            elif align == "r":
                bx = col_x[j] + col_w[j] - box.width
            else:
                bx = col_x[j] + (col_w[j] - box.width) // 2
            painter.drawImage(bx, baseline - box.ascent, box.image)
    pen = QPen(ctx.color, line_w)
    painter.setPen(pen)
    for k in vlines:
        if k == 0:
            vx = pad_x / 2
        elif k >= ncols:
            vx = width - pad_x / 2
        else:
            vx = col_x[k] - gaps[k - 1] / 2
        offsets = (-line_w * 1.2, line_w * 1.2) if k in double else (0.0,)
        for off in offsets:
            painter.drawLine(QPointF(vx + off, 0), QPointF(vx + off, height))
    for i in hlines:
        if i == 0:
            hy = pad_y / 2
        elif i >= nrows:
            hy = height - pad_y / 2
        else:
            hy = row_y[i] - row_gap / 2
        painter.drawLine(QPointF(0, hy), QPointF(width, hy))
    painter.end()

    axis = round(size_px * 0.25)
    ascent = height // 2 + axis
    box = _Box(image, width, ascent, height - ascent)
    left, right = _ENV_DELIMS.get(name, ("", ""))
    if left or right:
        box = _wrap_delims(box, left, right, ctx, size_px)
    return box


def _delim_width(kind: str, size_px: float, height: float) -> float:
    grow = min(1.6, max(1.0, height / (size_px * 2.2)))
    base = {"(": 0.34, ")": 0.34, "[": 0.26, "]": 0.26, "{": 0.42, "}": 0.42,
            "|": 0.08, "‖": 0.22, "⟨": 0.32, "⟩": 0.32, "⌊": 0.28, "⌋": 0.28,
            "⌈": 0.28, "⌉": 0.28}.get(kind, 0.0)
    return base * size_px * (grow if kind in "(){}⟨⟩" else 1.0)


def _draw_delim(painter: QPainter, kind: str, x: float, top: float, w: float, h: float,
                lw: float, color: QColor) -> None:
    bottom = top + h
    mid = top + h / 2
    mirror = kind in ")]}⟩⌋⌉"
    painter.save()
    if mirror:
        painter.translate(2 * x + w, 0)
        painter.scale(-1, 1)
    pen = QPen(color, lw)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    base = {")": "(", "]": "[", "}": "{", "⟩": "⟨", "⌋": "⌊", "⌉": "⌈"}.get(kind, kind)
    if base == "(":
        thick = lw * 1.9
        path = QPainterPath(QPointF(x + w, top))
        path.cubicTo(QPointF(x - w * 0.05, top + h * 0.2), QPointF(x - w * 0.05, top + h * 0.8),
                     QPointF(x + w, bottom))
        path.cubicTo(QPointF(x + thick - w * 0.05, top + h * 0.8),
                     QPointF(x + thick - w * 0.05, top + h * 0.2), QPointF(x + w, top))
        painter.setPen(QPen(color, lw * 0.35))
        painter.setBrush(QBrush(color))
        painter.drawPath(path)
    elif base == "[":
        painter.setPen(pen)
        off = lw / 2
        path = QPainterPath(QPointF(x + w, top + off))
        path.lineTo(x + off, top + off)
        path.lineTo(x + off, bottom - off)
        path.lineTo(x + w, bottom - off)
        painter.drawPath(path)
    elif base == "{":
        painter.setPen(pen)
        xr, xm, xl = x + w, x + w * 0.5, x + lw * 0.3
        r = min(w * 0.5, h / 4)
        path = QPainterPath(QPointF(xr, top + lw / 2))
        path.quadTo(QPointF(xm, top + lw / 2), QPointF(xm, top + r))
        path.lineTo(xm, mid - r)
        path.quadTo(QPointF(xm, mid), QPointF(xl, mid))
        path.quadTo(QPointF(xm, mid), QPointF(xm, mid + r))
        path.lineTo(xm, bottom - r)
        path.quadTo(QPointF(xm, bottom - lw / 2), QPointF(xr, bottom - lw / 2))
        painter.drawPath(path)
    elif base == "|":
        painter.setPen(pen)
        painter.drawLine(QPointF(x + w / 2, top), QPointF(x + w / 2, bottom))
    elif base == "‖":
        painter.setPen(pen)
        painter.drawLine(QPointF(x + lw, top), QPointF(x + lw, bottom))
        painter.drawLine(QPointF(x + w - lw, top), QPointF(x + w - lw, bottom))
    elif base == "⟨":
        painter.setPen(pen)
        path = QPainterPath(QPointF(x + w, top))
        path.lineTo(x + lw, mid)
        path.lineTo(x + w, bottom)
        painter.drawPath(path)
    elif base in "⌊⌈":
        painter.setPen(pen)
        off = lw / 2
        path = QPainterPath()
        if base == "⌈":
            path.moveTo(x + w, top + off)
            path.lineTo(x + off, top + off)
            path.lineTo(x + off, bottom)
        else:
            path.moveTo(x + off, top)
            path.lineTo(x + off, bottom - off)
            path.lineTo(x + w, bottom - off)
        painter.drawPath(path)
    painter.restore()


def _wrap_delims(box: _Box, left: str, right: str, ctx: _Ctx, size_px: float) -> _Box:
    pad_y = round(size_px * 0.12)
    gap = round(size_px * 0.12)
    height = box.height + 2 * pad_y
    lw_px = max(1.0, size_px * 0.055)
    lw_d = _delim_width(left, size_px, height) if left else 0.0
    rw_d = _delim_width(right, size_px, height) if right else 0.0
    lw_i = round(lw_d) + (gap if left else 0)
    rw_i = round(rw_d) + (gap if right else 0)
    width = lw_i + box.width + rw_i
    image = _new_image(width, height)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if box.image is not None:
        painter.drawImage(lw_i, pad_y, box.image)
    if left:
        _draw_delim(painter, left, 0.5, 0.5, lw_d, height - 1, lw_px, ctx.color)
    if right:
        _draw_delim(painter, right, width - rw_d - 0.5, 0.5, rw_d, height - 1, lw_px,
                    ctx.color)
    painter.end()
    return _Box(image, width, box.ascent + pad_y, box.descent + pad_y)


def _brace_error(text: str) -> str:
    depth = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return "Unbalanced braces: unexpected }"
        i += 1
    if depth > 0:
        return f"Unbalanced braces: missing {depth} closing }}"
    lefts = len(re.findall(r"\\left(?![a-zA-Z])", text))
    rights = len(re.findall(r"\\right(?![a-zA-Z])", text))
    if lefts != rights:
        return "Unbalanced \\left / \\right"
    begins = len(re.findall(r"\\begin\s*\{", text))
    ends = len(re.findall(r"\\end\s*\{", text))
    if begins != ends:
        return "Unbalanced \\begin / \\end"
    return ""


def _composite(latex: str, color: QColor, size_px: float) -> tuple[QImage | None, str]:
    tex = preprocess(latex)
    if not tex:
        return None, "empty"
    ctx = _Ctx(color)
    structural = _brace_error(tex)
    try:
        box = _layout(tex, ctx, size_px, top=True)
    except Exception as exc:  # noqa: BLE001 - never let layout bugs crash callers
        return None, f"Cannot render: {exc}"[:100]
    if box.image is None or box.width <= 0:
        return None, structural or "empty"
    error = structural or (ctx.errors[0] if ctx.errors else "")
    return box.image, error


def _try_render(latex: str, color: QColor, size_px: float) -> tuple[QImage | None, str]:
    if latex_available():
        image, error = _latex_image(latex, color, size_px)
        if image is not None:
            return image, ""
        composite, _ = _composite(latex, color, size_px)
        return composite, error
    return _composite(latex, color, size_px)


def render_image(latex: str, color: str, size_px: float = 22, dpr: float = 1.0) -> QImage:
    qcolor = QColor(color)
    scaled = size_px * dpr
    try:
        image, _error = _try_render(latex, qcolor, scaled)
    except Exception:  # noqa: BLE001
        image = None
    if image is None:
        try:
            text = detailed_preview(latex)
        except Exception:  # noqa: BLE001
            text = latex
        image = _text_image(text or " ", qcolor, scaled * 0.9)
    image.setDevicePixelRatio(dpr)
    return image


def render_error(latex: str) -> str:
    if not latex.strip():
        return ""
    try:
        _image, error = _try_render(latex, QColor("black"), 12)
    except Exception as exc:  # noqa: BLE001
        return str(exc)[:100]
    return "" if error == "empty" else error


def image_to_png(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def render_png(latex: str, color: str, size_px: float = 22, dpr: float = 2.0,
               background: str | None = None) -> bytes:
    image = render_image(latex, color, size_px, dpr)
    if background:
        pad = round(size_px * dpr * 0.5)
        canvas = QImage(image.width() + 2 * pad, image.height() + 2 * pad,
                        QImage.Format.Format_ARGB32_Premultiplied)
        canvas.fill(QColor(background))
        painter = QPainter(canvas)
        image.setDevicePixelRatio(1.0)
        painter.drawImage(pad, pad, image)
        painter.end()
        image = canvas
    return image_to_png(image)


class RenderService(QObject):
    rendered = pyqtSignal(str, QImage)

    def __init__(self) -> None:
        super().__init__()
        self._pending: OrderedDict[str, tuple[str, str, float, float]] = OrderedDict()
        self._cache: OrderedDict[tuple, QImage] = OrderedDict()
        self._cache_lock = threading.Lock()
        self._cond = threading.Condition()
        self._thread = threading.Thread(target=self._worker, name="latex-render", daemon=True)
        self._thread.start()

    def request(self, key: str, latex: str, color: str, size_px: float = 22,
                dpr: float = 1.0) -> None:
        cache_key = (latex, color, round(size_px, 1), round(dpr, 2))
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                self._cache.move_to_end(cache_key)
        if cached is not None:
            with self._cond:
                self._pending.pop(key, None)
            self.rendered.emit(key, cached)
            return
        with self._cond:
            self._pending.pop(key, None)
            self._pending[key] = (latex, color, size_px, dpr)
            self._cond.notify()

    def _worker(self) -> None:
        while True:
            with self._cond:
                while not self._pending:
                    self._cond.wait()
                key, job = self._pending.popitem(last=False)
            latex, color, size_px, dpr = job
            try:
                image = render_image(latex, color, size_px, dpr)
            except Exception:  # noqa: BLE001 - keep the worker alive
                continue
            cache_key = (latex, color, round(size_px, 1), round(dpr, 2))
            with self._cache_lock:
                self._cache[cache_key] = image
                while len(self._cache) > 400:
                    self._cache.popitem(last=False)
            self.rendered.emit(key, image)


_service: RenderService | None = None


def service() -> RenderService:
    global _service
    if _service is None:
        _service = RenderService()
    return _service

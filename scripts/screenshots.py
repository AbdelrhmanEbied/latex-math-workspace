#!/usr/bin/env python3
"""Regenerate the README screenshots in assets/screenshots/.

Renders the real application offscreen (no display needed) with demo content
in every tab, using a throwaway config/state directory so your own workspace
is never touched:

    python3 scripts/screenshots.py            # dark theme (default)
    python3 scripts/screenshots.py --light    # also writes *-light.png
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "screenshots"
SCALE = 1.5  # device pixel ratio of the captured images

_tmp = Path(tempfile.mkdtemp(prefix="latex-picker-shots-"))
(_tmp / "screen.json").write_text(json.dumps({
    "synchronousWindowSystemEvents": False,
    "windowFrameMargins": False,
    "screens": [{"name": "shot", "x": 0, "y": 0, "width": 1920, "height": 1200,
                 "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": SCALE}],
}))
os.environ["QT_QPA_PLATFORM"] = f"offscreen:configfile={_tmp / 'screen.json'}"
os.environ["XDG_STATE_HOME"] = str(_tmp / "state")
os.environ["XDG_CONFIG_HOME"] = str(_tmp / "config")
sys.path.insert(0, str(ROOT / "src"))

from PyQt6.QtWidgets import QApplication  # noqa: E402

from latex_picker.config import AppConfig, State  # noqa: E402
from latex_picker.environment import SessionInfo  # noqa: E402
from latex_picker.library import load_library  # noqa: E402
from latex_picker.preview import MathPreviewService  # noqa: E402
from latex_picker.search import SearchEngine  # noqa: E402
from latex_picker.theme import resolve_theme  # noqa: E402
from latex_picker.ui.window import LatexPickerWindow  # noqa: E402

app = QApplication([])


def pump(seconds: float = 0.6) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def make_window(theme_name: str) -> LatexPickerWindow:
    theme = resolve_theme(theme_name, 1.0)
    app.setStyleSheet(theme.stylesheet())
    library, _ = load_library()
    session = SessionInfo(session_type="wayland", desktop="Hyprland", compositor="Hyprland",
                          is_wayland=True, is_x11=False, is_hyprland=True)
    window = LatexPickerWindow(
        library=library, engine=SearchEngine(library), config=AppConfig().normalised(),
        theme=theme, state=State(recent=["int-gaussian", "frac-basic"]), session=session,
        preview_service=MathPreviewService(enabled=True), workspace={},
    )
    window.show()
    pump(0.3)
    return window


def shoot(window: LatexPickerWindow, name: str) -> None:
    pump(1.2)
    window._clear_status()
    path = OUT / f"{name}.png"
    window.grab().save(str(path))
    print(f"wrote {path.relative_to(ROOT)}")


def demo_picker(window: LatexPickerWindow) -> None:
    window.set_mode("picker")
    window.search_box.line_edit.setText("integral")
    pump(1.5)


def demo_editor(window: LatexPickerWindow) -> None:
    window.set_mode("editor")
    editor = window.tabs["editor"]
    editor.set_text(r"\det(A - \lambda I) = \begin{vmatrix} 2-\lambda & 1 \\ 1 & 2-\lambda "
                    r"\end{vmatrix} = (\lambda - 1)(\lambda - 3) = 0")
    editor._show_category("structures")


def demo_calculator(window: LatexPickerWindow) -> None:
    window.set_mode("calculator")
    calc = window.tabs["calculator"]
    calc.synchronous = True
    for text in ["2x^2 + 3x - 5 = 0", "integrate(e^(-x^2), -oo, oo)", "diff(x^3 sin(x))",
                 r"\lim_{x \to 0} \frac{\sin x}{x}", "x + y = 3, x - y = 1",
                 "taylor(cos(x), x, 0, 6)"]:
        calc.evaluate_text(text)
    calc.set_input("factor(x^4 - 1)")


def demo_graph(window: LatexPickerWindow) -> None:
    window.set_mode("graph")
    graph = window.tabs["graph"]
    for row in list(graph.rows):
        graph.remove_row(row)
    for text in ["x^3/4 - 2x", "a sin(x)", "x^2 + y^2 = 9"]:
        graph.add_expression(text)
    pump(0.4)
    graph.f_combo.setCurrentIndex(0)
    graph.analyze_extrema()
    graph.int_a.setText("-2")
    graph.int_b.setText("0")
    graph.analyze_integral()


def demo_matrix(window: LatexPickerWindow) -> None:
    window.set_mode("matrix")
    matrix = window.tabs["matrix"]
    matrix.synchronous = True
    matrix._select("A")
    matrix.auto("rref")
    matrix.output_tabs.setCurrentIndex(0)


def demo_matrix_results(window: LatexPickerWindow) -> None:
    matrix = window.tabs["matrix"]
    matrix._import_text("[2 1 0; 1 2 1; 0 1 2]") if False else None
    matrix._select("B")
    matrix.matrices["B"] = {"rows": [["2", "1"], ["1", "2"]], "aug": False}
    matrix._select("B")
    matrix.tools.setCurrentIndex(1)
    matrix.compute("eigen")
    matrix.compute("diag")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    themes = ["dark"] + (["light"] if "--light" in sys.argv else [])
    for theme in themes:
        suffix = "" if theme == "dark" else "-light"
        window = make_window(theme)
        for name, demo in [("picker", demo_picker), ("editor", demo_editor),
                           ("calculator", demo_calculator), ("graph", demo_graph),
                           ("matrix", demo_matrix), ("matrix-eigen", demo_matrix_results)]:
            demo(window)
            shoot(window, name + suffix)
        window._closed_emitted = True
        window.close()


if __name__ == "__main__":
    main()

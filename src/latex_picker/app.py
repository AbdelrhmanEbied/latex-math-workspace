"""Application bootstrap."""

from __future__ import annotations

import sys
from importlib import resources

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from .config import AppConfig, State, load_state
from .environment import SessionInfo, preview_backend
from .library import Library
from .preview import MathPreviewService
from .search import SearchEngine
from .theme import resolve_theme
from .ui.window import LatexPickerWindow


def run(
    library: Library,
    config: AppConfig,
    session: SessionInfo,
    state: State | None = None,
    warnings: list[str] | None = None,
    mode: str | None = None,
) -> int:
    state = state or load_state()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("LaTeX Picker")
    app.setApplicationDisplayName("LaTeX Picker")
    app.setOrganizationName("latex-picker")
    app.setDesktopFileName("latex-picker")
    app.setQuitOnLastWindowClosed(False)

    icon_path = resources.files("latex_picker.data").joinpath("icon.svg")
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    theme = resolve_theme(config.theme, config.font_scale)
    app.setStyleSheet(theme.stylesheet())

    renderer_available = preview_backend()[0] == "matplotlib"
    preview_service = MathPreviewService(
        enabled=config.show_preview
        and config.preview_renderer == "auto"
        and renderer_available
    )
    engine = SearchEngine(library)
    window = LatexPickerWindow(
        library=library,
        engine=engine,
        config=config,
        theme=theme,
        state=state,
        session=session,
        preview_service=preview_service,
        warnings=warnings,
        mode=mode,
    )

    def on_closed(hold_seconds: int) -> None:
        if hold_seconds > 0:
            # Keep the Qt clipboard owner alive long enough for the user to paste.
            QTimer.singleShot(hold_seconds * 1000, app.quit)
        else:
            app.quit()

    window.closed.connect(on_closed)
    window.show()
    exit_code = app.exec()
    preview_service.stop()
    return exit_code

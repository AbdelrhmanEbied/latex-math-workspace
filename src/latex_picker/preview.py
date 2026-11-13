"""Optional high-fidelity math previews rendered with matplotlib mathtext.

The renderer runs on a single background thread so opening the picker and
moving through results always stays responsive.  If matplotlib is missing, or
cannot parse an expression (matrix/cases environments are not supported by
mathtext), the UI keeps the Unicode fallback.
"""

from __future__ import annotations

import io
import queue
import threading
from collections import OrderedDict

from PyQt6.QtCore import QObject, pyqtSignal


class PreviewSignals(QObject):
    rendered = pyqtSignal(str, bytes)
    failed = pyqtSignal(str)


def _render_png(latex: str, color: str) -> bytes:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt  # noqa: F401  (sets up font manager)
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    matplotlib.rcParams["mathtext.fontset"] = "cm"
    matplotlib.rcParams["mathtext.default"] = "normal"

    expression = latex.strip()
    if not expression:
        raise ValueError("empty expression")
    if not (expression.startswith("$") and expression.endswith("$")):
        expression = f"${expression}$"
    figure = Figure(figsize=(8, 1.6), dpi=220)
    figure.patch.set_alpha(0.0)
    figure.text(0.5, 0.5, expression, color=color, fontsize=22,
                ha="center", va="center")
    FigureCanvasAgg(figure)
    buffer = io.BytesIO()
    figure.savefig(
        buffer,
        format="png",
        bbox_inches="tight",
        pad_inches=0.04,
        transparent=True,
        dpi=220,
    )
    return buffer.getvalue()


class MathPreviewService(QObject):
    def __init__(self, enabled: bool = True, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.enabled = enabled
        self.signals = PreviewSignals(self)
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._queue: queue.Queue = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if enabled:
            self._thread = threading.Thread(
                target=self._worker, name="latex-picker-preview", daemon=True
            )
            self._thread.start()

    @staticmethod
    def key(snippet_id: str, color: str) -> str:
        return f"{snippet_id}|{color}"

    def cached(self, key: str) -> bytes | None:
        value = self._cache.get(key)
        if value is not None:
            self._cache.move_to_end(key)
        return value

    def request(self, snippet_id: str, latex: str, color: str) -> None:
        if not self.enabled:
            return
        key = self.key(snippet_id, color)
        if key in self._cache:
            self.signals.rendered.emit(key, self._cache[key])
            return
        item = (key, latex, color)
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                pass

    def _remember(self, key: str, png: bytes) -> None:
        self._cache[key] = png
        self._cache.move_to_end(key)
        while len(self._cache) > 96:
            self._cache.popitem(last=False)

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                key, latex, color = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if self._stop.is_set():
                break
            try:
                png = _render_png(latex, color)
            except Exception:  # noqa: BLE001 - any mathtext failure uses the fallback
                self.signals.failed.emit(key)
                continue
            self._remember(key, png)
            self.signals.rendered.emit(key, png)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=0.2)

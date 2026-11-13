"""Clipboard integration that survives the picker process exiting.

On Wayland clipboard ownership belongs to a live client.  Since the picker
quits immediately after copying, writing through ``wl-copy`` (which forks a
small owner process) is the reliable path.  Qt's clipboard is a fallback for
X11 and for systems without wl-clipboard.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass


@dataclass
class CopyResult:
    ok: bool
    backend: str
    error: str = ""

    @property
    def warning(self) -> str:
        if self.ok and self.backend.startswith("qt"):
            return "Copied with Qt; install wl-clipboard to keep it after closing"
        return self.error


def session_type() -> str:
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def available_backends() -> dict[str, str | None]:
    return {
        "wl-copy": shutil.which("wl-copy"),
        "xclip": shutil.which("xclip"),
        "xsel": shutil.which("xsel"),
    }


def preferred_backend() -> str:
    backends = available_backends()
    session = session_type()
    if session == "wayland" and backends["wl-copy"]:
        return "wl-copy"
    if session == "x11" and backends["xclip"]:
        return "xclip"
    if session == "x11" and backends["xsel"]:
        return "xsel"
    return "qt"


def _run(command: list[str], text: str) -> tuple[bool, str]:
    # Clipboard helpers such as wl-copy fork an owner process that keeps
    # running after the helper itself exits.  A stderr=PIPE would therefore
    # stay open in the child and make subprocess.run() wait until the timeout,
    # so errors are collected in a temporary file instead.
    try:
        with tempfile.TemporaryFile() as errors:
            completed = subprocess.run(
                command,
                input=text.encode("utf-8"),
                stdout=subprocess.DEVNULL,
                stderr=errors,
                timeout=5,
                check=False,
            )
            errors.seek(0)
            stderr = errors.read().decode("utf-8", "replace").strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if completed.returncode != 0:
        return False, stderr or f"{command[0]} exited with {completed.returncode}"
    return True, ""


def copy_to_clipboard(text: str, qt_setter=None) -> CopyResult:
    """Copy *text* using the best backend available for this session.

    ``qt_setter`` is a callable such as ``QGuiApplication.clipboard().setText``.
    Supplying it enables the Qt fallback.
    """
    backend = preferred_backend()
    if backend == "wl-copy":
        ok, error = _run(["wl-copy", "--type", "text/plain;charset=utf-8"], text)
        if ok:
            return CopyResult(True, "wl-copy")
        if qt_setter is not None:
            qt_setter(text)
            return CopyResult(True, "qt-fallback", error or "wl-copy failed")
        return CopyResult(False, "wl-copy", error)

    if backend in {"xclip", "xsel"}:
        if backend == "xclip":
            command = ["xclip", "-selection", "clipboard", "-in"]
        else:
            command = ["xsel", "--clipboard", "--input"]
        ok, error = _run(command, text)
        if ok:
            return CopyResult(True, backend)
        if qt_setter is not None:
            qt_setter(text)
            return CopyResult(True, "qt-fallback", error or f"{backend} failed")
        return CopyResult(False, backend, error)

    if qt_setter is not None:
        try:
            qt_setter(text)
            return CopyResult(True, "qt")
        except Exception as exc:  # noqa: BLE001 - platform dependent
            return CopyResult(False, "qt", str(exc))
    return CopyResult(False, "none", "No clipboard backend available")


def _run_bytes(command: list[str], data: bytes) -> tuple[bool, str]:
    try:
        with tempfile.TemporaryFile() as errors:
            completed = subprocess.run(
                command, input=data, stdout=subprocess.DEVNULL, stderr=errors,
                timeout=5, check=False,
            )
            errors.seek(0)
            stderr = errors.read().decode("utf-8", "replace").strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if completed.returncode != 0:
        return False, stderr or f"{command[0]} exited with {completed.returncode}"
    return True, ""


def copy_image_to_clipboard(png: bytes, qt_setter=None) -> CopyResult:
    """Copy PNG bytes as an image.  ``qt_setter`` receives the raw PNG bytes."""
    backend = preferred_backend()
    if backend == "wl-copy":
        ok, error = _run_bytes(["wl-copy", "--type", "image/png"], png)
        if ok:
            return CopyResult(True, "wl-copy")
    elif backend == "xclip":
        ok, error = _run_bytes(["xclip", "-selection", "clipboard", "-t", "image/png", "-in"], png)
        if ok:
            return CopyResult(True, "xclip")
    else:
        error = ""
    if qt_setter is not None:
        try:
            qt_setter(png)
            return CopyResult(True, "qt")
        except Exception as exc:  # noqa: BLE001
            return CopyResult(False, "qt", str(exc))
    return CopyResult(False, backend, error or "No image clipboard backend")

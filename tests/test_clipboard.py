"""Tests for clipboard backend selection and helper-process handling."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from latex_picker import clipboard


class BackendSelectionTests(unittest.TestCase):
    def test_wayland_prefers_wl_copy(self) -> None:
        backends = {"wl-copy": "/usr/bin/wl-copy", "xclip": None, "xsel": None}
        with patch.object(clipboard, "session_type", return_value="wayland"), \
                patch.object(clipboard, "available_backends", return_value=backends):
            self.assertEqual(clipboard.preferred_backend(), "wl-copy")

    def test_x11_prefers_xclip_then_xsel(self) -> None:
        backends = {"wl-copy": "/usr/bin/wl-copy", "xclip": "/usr/bin/xclip", "xsel": None}
        with patch.object(clipboard, "session_type", return_value="x11"), \
                patch.object(clipboard, "available_backends", return_value=backends):
            self.assertEqual(clipboard.preferred_backend(), "xclip")
        backends["xclip"] = None
        backends["xsel"] = "/usr/bin/xsel"
        with patch.object(clipboard, "session_type", return_value="x11"), \
                patch.object(clipboard, "available_backends", return_value=backends):
            self.assertEqual(clipboard.preferred_backend(), "xsel")

    def test_qt_fallback_when_no_helper_exists(self) -> None:
        empty = {"wl-copy": None, "xclip": None, "xsel": None}
        with patch.object(clipboard, "session_type", return_value="wayland"), \
                patch.object(clipboard, "available_backends", return_value=empty):
            self.assertEqual(clipboard.preferred_backend(), "qt")

    def test_qt_setter_receives_text(self) -> None:
        copied: list[str] = []
        with patch.object(clipboard, "preferred_backend", return_value="qt"):
            result = clipboard.copy_to_clipboard("x^2", copied.append)
        self.assertTrue(result.ok)
        self.assertEqual(result.backend, "qt")
        self.assertEqual(copied, ["x^2"])

    def test_failed_wl_copy_falls_back_to_qt(self) -> None:
        copied: list[str] = []
        with patch.object(clipboard, "preferred_backend", return_value="wl-copy"), \
                patch.object(clipboard, "_run", return_value=(False, "nope")):
            result = clipboard.copy_to_clipboard("x^2", copied.append)
        self.assertTrue(result.ok)
        self.assertEqual(result.backend, "qt-fallback")
        self.assertEqual(copied, ["x^2"])

    def test_failed_copy_without_setter_reports_error(self) -> None:
        with patch.object(clipboard, "preferred_backend", return_value="wl-copy"), \
                patch.object(clipboard, "_run", return_value=(False, "nope")):
            result = clipboard.copy_to_clipboard("x^2")
        self.assertFalse(result.ok)
        self.assertEqual(result.backend, "wl-copy")


class HelperProcessTests(unittest.TestCase):
    def test_run_does_not_wait_for_forked_owner_process(self) -> None:
        # Simulate wl-copy: read stdin, fork an owner that keeps running and
        # inherits stderr, while the direct child exits immediately.
        script = (
            "import os,sys,time\n"
            "sys.stdin.buffer.read()\n"
            "pid=os.fork()\n"
            "if pid:\n"
            "    os._exit(0)\n"
            "time.sleep(3)\n"
        )
        started = time.monotonic()
        ok, error = clipboard._run([sys.executable, "-c", script], "payload")
        elapsed = time.monotonic() - started
        self.assertTrue(ok, error)
        self.assertLess(elapsed, 2.0, "helper waited for the forked clipboard owner")

    def test_run_reports_nonzero_exit(self) -> None:
        ok, error = clipboard._run(
            [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"],
            "",
        )
        self.assertFalse(ok)
        self.assertIn("boom", error)


if __name__ == "__main__":
    unittest.main()
